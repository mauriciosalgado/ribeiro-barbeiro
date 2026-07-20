"""A barber's open slots — shared by the availability endpoint and booking."""

from datetime import date, datetime, time, timedelta
from math import gcd
from zoneinfo import ZoneInfo

from fastapi import HTTPException, status
from sqlmodel import Session, col, select

from app.config import get_settings
from app.models import Appointment, Barber, Closure, Service, Weekday, WorkingHours
from app.scheduling import Interval, free_slots

# Customers must book at least this far ahead (no last-minute walk-in slots).
BOOKING_LEAD = timedelta(hours=1)

# Cap the appointment-list endpoints so a long history never floods the UI.
# The full record is always available (paginated) in the admin console.
MAX_APPOINTMENTS = 500


def shop_now() -> datetime:
    """The current time in the shop's timezone, as a naive datetime.

    Slots and appointments are stored naive and shop-local, so comparisons
    against "now" must drop the timezone after converting.
    """
    return datetime.now(ZoneInfo(get_settings().shop_timezone)).replace(tzinfo=None)


def bookable_barber(session: Session, barber_id: int) -> Barber:
    """Return an active barber, or raise 404 (inactive barbers are hidden)."""
    barber = session.get(Barber, barber_id)
    if barber is None or not barber.is_active:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Barber not found")
    return barber


def bookable_service(session: Session, barber: Barber, service_id: int) -> Service:
    """Return one of the barber's active services, or raise 404/400."""
    service = session.get(Service, service_id)
    if service is None or not service.is_active:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Service not found")
    if service.barber_id != barber.id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Service is not this barber's")
    return service


def busy_intervals(
    session: Session,
    barber_id: int,
    day: date,
    exclude_appointment_id: int | None = None,
) -> list[Interval]:
    """Everything that blocks a day for a barber: their bookings and any closures.

    ``exclude_appointment_id`` drops one booking from the picture — used when
    re-timing that very appointment, so it doesn't clash with itself.
    """
    day_start = datetime.combine(day, time.min)
    day_end = day_start + timedelta(days=1)
    appointments = session.exec(
        select(Appointment).where(
            Appointment.barber_id == barber_id,
            Appointment.start_at >= day_start,
            Appointment.start_at < day_end,
        )
    ).all()
    intervals: list[Interval] = [
        (a.start_at, a.start_at + timedelta(minutes=a.duration_minutes))
        for a in appointments
        if a.id != exclude_appointment_id
    ]
    closures = session.exec(
        select(Closure).where(Closure.start_at < day_end, Closure.end_at > day_start)
    ).all()
    intervals += [(c.start_at, c.end_at) for c in closures]
    return intervals


def slot_step(session: Session, barber: Barber, fallback: int) -> int:
    """The grid granularity: the GCD of the barber's active service lengths.

    Laying every service on this one fine grid means a shorter booking never
    knocks longer services off a usable start time — book a 15-min service and a
    30-min one can still start 15 minutes later. Falls back to the service being
    booked when the barber has no services yet (so a slot is always offered).
    """
    durations = session.exec(
        select(Service.duration_minutes).where(
            Service.barber_id == barber.id, col(Service.is_active).is_(True)
        )
    ).all()
    step = 0
    for minutes in durations:
        step = gcd(step, minutes)
    return step or fallback


def available_slots(
    session: Session, barber: Barber, day: date, duration_minutes: int
) -> list[datetime]:
    """Open start-times for a service of a given length (empty on a day off)."""
    hours = session.exec(
        select(WorkingHours).where(
            WorkingHours.barber_id == barber.id,
            WorkingHours.weekday == Weekday.of(day),
        )
    ).first()
    if hours is None:
        return []

    assert barber.id is not None
    busy = busy_intervals(session, barber.id, day)
    earliest = shop_now() + BOOKING_LEAD
    step = slot_step(session, barber, duration_minutes)
    return free_slots(hours, day, busy, earliest, duration_minutes, step)


def slot_is_free(
    session: Session, barber: Barber, start_at: datetime, duration_minutes: int
) -> bool:
    """True if a service of the given length can start exactly at ``start_at``."""
    return start_at in available_slots(
        session, barber, start_at.date(), duration_minutes
    )


def switch_fits(
    session: Session, barber: Barber, appointment: Appointment, duration_minutes: int
) -> bool:
    """True if ``appointment`` can be re-timed to a new length without clashing.

    Keeps its start; only the length changes. Must stay inside the working day,
    clear of the break, and clear of every other booking and closure.
    """
    day = appointment.start_at.date()
    hours = session.exec(
        select(WorkingHours).where(
            WorkingHours.barber_id == barber.id,
            WorkingHours.weekday == Weekday.of(day),
        )
    ).first()
    if hours is None:
        return False

    start = appointment.start_at
    end = start + timedelta(minutes=duration_minutes)
    if start < datetime.combine(day, hours.start_time):
        return False
    if end > datetime.combine(day, hours.end_time):
        return False
    if hours.break_start is not None and hours.break_end is not None:
        break_start = datetime.combine(day, hours.break_start)
        break_end = datetime.combine(day, hours.break_end)
        if start < break_end and end > break_start:
            return False

    assert barber.id is not None
    busy = busy_intervals(
        session, barber.id, day, exclude_appointment_id=appointment.id
    )
    return all(end <= b_start or start >= b_end for b_start, b_end in busy)


def cancel_appointments_between(
    session: Session, start_at: datetime, end_at: datetime
) -> int:
    """Cancel appointments overlapping [start_at, end_at); returns how many.

    An appointment runs for its own stored length, so it overlaps the closure
    when it starts before end_at and ends after start_at.
    """
    rows = session.exec(select(Appointment).where(Appointment.start_at < end_at)).all()
    overlapping = [
        appointment
        for appointment in rows
        if appointment.start_at + timedelta(minutes=appointment.duration_minutes)
        > start_at
    ]
    for appointment in overlapping:
        session.delete(appointment)
    return len(overlapping)
