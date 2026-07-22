"""Appointments — customers reserve and cancel slots."""

import logging
from collections.abc import Sequence
from datetime import datetime, time, timedelta
from uuid import uuid4

from fastapi import APIRouter, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, col, select

from app.availability import (
    MAX_APPOINTMENTS,
    bookable_barber,
    bookable_service,
    shop_now,
    slot_is_free,
    switch_fits,
)
from app.config import get_settings
from app.database import SessionDep
from app.email import send_email
from app.models import (
    Appointment,
    AppointmentCreate,
    AppointmentRead,
    Barber,
    BookingResult,
    ManualAppointmentCreate,
    RecurringSeries,
    RecurringSeriesRead,
    Service,
    ServiceSwitch,
    User,
)
from app.recurrence import ensure_materialized, ensure_materialized_for_customer
from app.security import CurrentUser

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/appointments", tags=["appointments"])

# Customers can't cancel once the appointment is this close (staff still can).
CANCEL_CUTOFF = timedelta(hours=1)

# Machine-readable error code so the frontend can recognise this specific
# conflict without matching on human-readable message text.
STANDING_SLOT_CONFLICT = "standing_slot_conflict"


def _standing_slot_conflict_error() -> HTTPException:
    return HTTPException(
        status.HTTP_409_CONFLICT,
        {
            "code": STANDING_SLOT_CONFLICT,
            "message": "You already have a standing appointment at this weekday and time",
        },
    )


def _notify_cancellation(email: str, name: str, start_at: datetime) -> None:
    """Let a registered customer know a barber or admin cancelled their slot.

    Best-effort: a mail outage must never fail the cancellation itself.
    """
    when = start_at.strftime("%d/%m/%Y às %H:%M")
    shop = get_settings().shop_name
    try:
        send_email(
            email,
            "Marcação cancelada",
            f"Olá {name},\n\n"
            f"A sua marcação em {shop} no dia {when} foi cancelada.\n\n"
            "Pode voltar a marcar quando quiser.",
        )
    except OSError as error:
        logger.warning("Could not send cancellation email to %s: %s", email, error)


def _has_standing_slot_conflict(
    session: Session, customer_id: int | None, when: datetime
) -> bool:
    """Would a new weekly series clash with a standing slot this customer already has?

    Two recurring bookings landing on the same weekday at the same time can
    never both happen (no matter the barber or service), so this is checked
    before creating any new recurring series — bounded or perpetual. Guests
    (no account) aren't tracked well enough to check reliably, so they're
    exempt, same as the one-off same-day case.
    """
    if customer_id is None:
        return False

    weekday, time_of_day = when.weekday(), when.time()

    perpetual = session.exec(
        select(RecurringSeries).where(RecurringSeries.customer_id == customer_id)
    ).all()
    if any(
        s.anchor_start_at.weekday() == weekday
        and s.anchor_start_at.time() == time_of_day
        for s in perpetual
    ):
        return True

    bounded = session.exec(
        select(Appointment).where(
            Appointment.customer_id == customer_id,
            col(Appointment.recurrence_group_id).is_not(None),
            Appointment.start_at >= shop_now(),
        )
    ).all()
    return any(
        a.start_at.weekday() == weekday and a.start_at.time() == time_of_day
        for a in bounded
    )


def _book_perpetual(
    session: Session,
    barber: Barber,
    service: Service,
    customer_id: int | None,
    guest_name: str | None,
    start_at: datetime,
    enforce_policy: bool,
) -> BookingResult:
    """Book a slot that repeats weekly, forever, until the series is cancelled.

    Only the pattern is stored as a RecurringSeries; real Appointment rows
    are created a rolling window at a time by app.recurrence.
    """
    if enforce_policy and not barber.allow_recurring:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "This barber does not allow weekly bookings"
        )
    if _has_standing_slot_conflict(session, customer_id, start_at):
        raise _standing_slot_conflict_error()
    assert barber.id is not None and service.id is not None
    if not slot_is_free(session, barber, start_at, service.duration_minutes):
        raise HTTPException(status.HTTP_409_CONFLICT, "Slot is not available")

    series = RecurringSeries(
        id=uuid4().hex,
        barber_id=barber.id,
        customer_id=customer_id,
        guest_name=guest_name,
        service_id=service.id,
        anchor_start_at=start_at,
        duration_minutes=service.duration_minutes,
        materialized_through=start_at - timedelta(weeks=1),
    )
    session.add(series)
    session.commit()
    session.refresh(series)
    ensure_materialized(session, series)

    booked = session.exec(
        select(Appointment)
        .where(Appointment.recurrence_group_id == series.id)
        .order_by(col(Appointment.start_at))
    ).all()
    return BookingResult(
        booked=[
            AppointmentRead.model_validate(a, from_attributes=True) for a in booked
        ],
        skipped=[],
    )


def _book_series(
    session: Session,
    barber: Barber,
    service: Service,
    customer_id: int | None,
    guest_name: str | None,
    start_at: datetime,
    repeat_weeks: int,
    enforce_policy: bool,
) -> BookingResult:
    """Book one slot, or the same slot every week for ``repeat_weeks`` weeks.

    Free weeks are booked and tied by a shared id; weeks already taken are
    skipped. A single booking that clashes is a clean 409.
    """
    if repeat_weeks > 1:
        if enforce_policy and not barber.allow_recurring:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN, "This barber does not allow weekly bookings"
            )
        if repeat_weeks > barber.max_recurring_weeks:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                f"At most {barber.max_recurring_weeks} weeks can be booked at once",
            )
        if _has_standing_slot_conflict(session, customer_id, start_at):
            raise _standing_slot_conflict_error()

    group_id = uuid4().hex if repeat_weeks > 1 else None
    booked: list[Appointment] = []
    skipped: list[datetime] = []
    assert barber.id is not None and service.id is not None
    for week in range(repeat_weeks):
        when = start_at + timedelta(weeks=week)
        if not slot_is_free(session, barber, when, service.duration_minutes):
            skipped.append(when)
            continue
        appointment = Appointment(
            barber_id=barber.id,
            customer_id=customer_id,
            guest_name=guest_name,
            start_at=when,
            service_id=service.id,
            duration_minutes=service.duration_minutes,
            recurrence_group_id=group_id,
        )
        session.add(appointment)
        try:
            session.commit()
        except IntegrityError:  # someone booked the same slot first
            session.rollback()
            skipped.append(when)
            continue
        session.refresh(appointment)
        booked.append(appointment)

    if not booked:
        raise HTTPException(status.HTTP_409_CONFLICT, "Slot is not available")
    return BookingResult(
        booked=[
            AppointmentRead.model_validate(a, from_attributes=True) for a in booked
        ],
        skipped=skipped,
    )


@router.post("", response_model=BookingResult, status_code=status.HTTP_201_CREATED)
def reserve(
    data: AppointmentCreate, session: SessionDep, user: CurrentUser
) -> BookingResult:
    if not user.is_verified:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "Verify your email before booking"
        )
    barber = bookable_barber(session, data.barber_id)
    if barber.user_id == user.id:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "A barber cannot book themselves"
        )
    service = bookable_service(session, barber, data.service_id)

    assert user.id is not None
    if data.perpetual:
        return _book_perpetual(
            session, barber, service, user.id, None, data.start_at, True
        )
    return _book_series(
        session, barber, service, user.id, None, data.start_at, data.repeat_weeks, True
    )


@router.post(
    "/manual", response_model=BookingResult, status_code=status.HTTP_201_CREATED
)
def reserve_manual(
    data: ManualAppointmentCreate, session: SessionDep, user: CurrentUser
) -> BookingResult:
    """Book a slot for someone else: an existing account, or a walk-in by name.

    Only the barber whose chair it is (or an admin) may do this. Give an email
    to link an existing account, or just a name for a customer with no account.
    """
    barber = bookable_barber(session, data.barber_id)
    if not user.is_admin and barber.user_id != user.id:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "You can only book for your own chair"
        )
    service = bookable_service(session, barber, data.service_id)

    customer_id: int | None = None
    guest_name: str | None = data.customer_name.strip() or None
    if data.customer_email.strip():
        customer = session.exec(
            select(User).where(User.email == data.customer_email.strip().lower())
        ).first()
        if customer is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "No account with that email")
        if customer.id == barber.user_id:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST, "A barber cannot be their own customer"
            )
        customer_id, guest_name = customer.id, None
    elif guest_name is None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "Enter a name or a registered email"
        )

    # Staff may book recurring for a customer regardless of the public toggle.
    if data.perpetual:
        return _book_perpetual(
            session, barber, service, customer_id, guest_name, data.start_at, False
        )
    return _book_series(
        session,
        barber,
        service,
        customer_id,
        guest_name,
        data.start_at,
        data.repeat_weeks,
        False,
    )


@router.patch("/{appointment_id}", response_model=AppointmentRead)
def switch_service(
    appointment_id: int, data: ServiceSwitch, session: SessionDep, user: CurrentUser
) -> Appointment:
    """Change a booking to a different service (staff only), freeing or using time.

    Shrinking always fits; growing is refused if it would overlap the next
    booking, the break, a closure, or run past closing time.
    """
    appointment = session.get(Appointment, appointment_id)
    if appointment is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Appointment not found")
    barber = session.get(Barber, appointment.barber_id)
    if barber is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Barber not found")
    if not user.is_admin and barber.user_id != user.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not your chair")

    service = bookable_service(session, barber, data.service_id)
    if not switch_fits(session, barber, appointment, service.duration_minutes):
        raise HTTPException(
            status.HTTP_409_CONFLICT, "The new service does not fit in this slot"
        )
    appointment.service_id = service.id
    appointment.duration_minutes = service.duration_minutes
    session.add(appointment)
    session.commit()
    session.refresh(appointment)
    return appointment


@router.get("", response_model=list[AppointmentRead])
def my_appointments(session: SessionDep, user: CurrentUser) -> Sequence[Appointment]:
    """A customer's upcoming bookings (past visits live in the admin console)."""
    assert user.id is not None
    ensure_materialized_for_customer(session, user.id)
    today_start = datetime.combine(shop_now().date(), time.min)
    return session.exec(
        select(Appointment)
        .where(Appointment.customer_id == user.id, Appointment.start_at >= today_start)
        .order_by(col(Appointment.start_at))
        .limit(MAX_APPOINTMENTS)
    ).all()


def _customer_label(customer: User | None, guest_name: str | None) -> str:
    if customer is not None:
        return customer.full_name
    return guest_name or "Guest"


def _own_barber(session: Session, user: User) -> Barber | None:
    return session.exec(select(Barber).where(Barber.user_id == user.id)).first()


@router.get("/recurring-series", response_model=list[RecurringSeriesRead])
def list_recurring_series(
    session: SessionDep, user: CurrentUser
) -> list[RecurringSeriesRead]:
    """Every standing weekly booking, scoped to the caller's role.

    Covers both a perpetual series (repeats forever) and a bounded weekly
    series (repeats up to the barber's max_recurring_weeks) — the two ways a
    customer can have a "standing" slot with this shop. Admins see every
    one; a barber sees their own chair's; a customer sees their own.
    """
    assert user.id is not None
    own_barber = None if user.is_admin else _own_barber(session, user)

    # --- perpetual: the pattern lives entirely in one RecurringSeries row ---
    perpetual_query = select(RecurringSeries)
    if own_barber is not None:
        perpetual_query = perpetual_query.where(
            RecurringSeries.barber_id == own_barber.id
        )
    elif not user.is_admin:
        perpetual_query = perpetual_query.where(RecurringSeries.customer_id == user.id)
    series_list = session.exec(perpetual_query).all()
    perpetual_ids = {series.id for series in series_list}

    reads: list[RecurringSeriesRead] = []
    for series in series_list:
        barber = session.get(Barber, series.barber_id)
        service = session.get(Service, series.service_id) if series.service_id else None
        customer = session.get(User, series.customer_id) if series.customer_id else None
        reads.append(
            RecurringSeriesRead(
                id=series.id,
                kind="perpetual",
                barber_id=series.barber_id,
                barber_name=barber.user.full_name if barber and barber.user else "",
                customer_name=_customer_label(customer, series.guest_name),
                customer_email=customer.email if customer else "",
                customer_phone=(customer.phone or "") if customer else "",
                service_id=series.service_id,
                service_name=service.name if service else "",
                anchor_start_at=series.anchor_start_at,
                duration_minutes=series.duration_minutes,
                ends_at=None,
            )
        )

    # --- bounded: just a shared recurrence_group_id across Appointment rows ---
    appt_query = select(Appointment).where(
        col(Appointment.recurrence_group_id).is_not(None),
        Appointment.start_at >= shop_now(),
    )
    if own_barber is not None:
        appt_query = appt_query.where(Appointment.barber_id == own_barber.id)
    elif not user.is_admin:
        appt_query = appt_query.where(Appointment.customer_id == user.id)
    rows = session.exec(appt_query.order_by(col(Appointment.start_at))).all()

    groups: dict[str, list[Appointment]] = {}
    for row in rows:
        group_id = row.recurrence_group_id
        if group_id is None or group_id in perpetual_ids:
            continue  # a perpetual series' own materialised rows, already covered
        groups.setdefault(group_id, []).append(row)

    for group_id, appointments in groups.items():
        first, last = appointments[0], appointments[-1]
        barber = session.get(Barber, first.barber_id)
        service = session.get(Service, first.service_id) if first.service_id else None
        customer = session.get(User, first.customer_id) if first.customer_id else None
        reads.append(
            RecurringSeriesRead(
                id=group_id,
                kind="bounded",
                barber_id=first.barber_id,
                barber_name=barber.user.full_name if barber and barber.user else "",
                customer_name=_customer_label(customer, first.guest_name),
                customer_email=customer.email if customer else "",
                customer_phone=(customer.phone or "") if customer else "",
                service_id=first.service_id,
                service_name=service.name if service else "",
                anchor_start_at=first.start_at,
                duration_minutes=first.duration_minutes,
                ends_at=last.start_at.date(),
            )
        )

    reads.sort(key=lambda read: read.anchor_start_at)
    return reads


@router.delete("/series/{group_id}", status_code=status.HTTP_204_NO_CONTENT)
def cancel_series(group_id: str, session: SessionDep, user: CurrentUser) -> None:
    """Cancel all upcoming appointments in a weekly series at once.

    ``group_id`` may belong to a bounded weekly series (plain Appointment
    rows only) or a perpetual RecurringSeries — either way this ends it for
    good and cancels everything still upcoming.
    """
    appointments = session.exec(
        select(Appointment).where(
            Appointment.recurrence_group_id == group_id,
            Appointment.start_at >= shop_now(),
        )
    ).all()
    series = session.get(RecurringSeries, group_id)
    if not appointments and series is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "No upcoming appointments in this series"
        )

    if series is not None:
        barber_id, customer_id = series.barber_id, series.customer_id
    else:
        barber_id, customer_id = appointments[0].barber_id, appointments[0].customer_id
    barber = session.get(Barber, barber_id)
    is_staff = user.is_admin or (barber is not None and barber.user_id == user.id)
    if not is_staff and customer_id != user.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not your series")

    if series is not None:
        session.delete(series)
    for appointment in appointments:
        session.delete(appointment)
    session.commit()


@router.delete("/{appointment_id}", status_code=status.HTTP_204_NO_CONTENT)
def cancel(appointment_id: int, session: SessionDep, user: CurrentUser) -> None:
    appointment = session.get(Appointment, appointment_id)
    if appointment is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Appointment not found")

    # Staff = an admin, or the barber whose chair this booking is on.
    barber = session.get(Barber, appointment.barber_id)
    is_staff = user.is_admin or (barber is not None and barber.user_id == user.id)
    if not is_staff and appointment.customer_id != user.id:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "Cannot cancel another customer's appointment"
        )
    if not is_staff and appointment.start_at - shop_now() < CANCEL_CUTOFF:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Too late to cancel online; please contact the shop",
        )

    # When staff cancel, email the registered customer (walk-ins have no address).
    notify = None
    if is_staff and appointment.customer is not None:
        notify = (
            appointment.customer.email,
            appointment.customer.full_name,
            appointment.start_at,
        )

    session.delete(appointment)
    session.commit()

    if notify is not None:
        _notify_cancellation(*notify)
