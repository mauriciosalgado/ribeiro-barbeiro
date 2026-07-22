"""Perpetual recurring series: lazily materialise a rolling window of bookings.

A perpetual series (see app.models.recurring_series) only stores the pattern —
barber, service, customer, and the weekday+time it repeats on. Real
``Appointment`` rows are created a couple of weeks at a time, on demand,
whenever someone reads a schedule that a series could affect. This keeps a
"forever" booking from ever pre-creating more than a couple of weeks' worth
of rows, with no scheduler or background job needed.
"""

from datetime import timedelta

from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from app.availability import shop_now, slot_is_free
from app.models import Appointment, Barber, RecurringSeries

# How far ahead a perpetual series is kept materialised. The barber's agenda
# and the customer's own list always show at least this much of the future.
ROLLING_WINDOW = timedelta(weeks=4)


def ensure_materialized(session: Session, series: RecurringSeries) -> None:
    """Extend one series' real Appointment rows up to the rolling window."""
    cutoff = shop_now() + ROLLING_WINDOW
    when = series.materialized_through + timedelta(weeks=1)
    barber = session.get(Barber, series.barber_id)
    while when <= cutoff:
        if barber is not None and slot_is_free(
            session, barber, when, series.duration_minutes
        ):
            session.add(
                Appointment(
                    barber_id=series.barber_id,
                    customer_id=series.customer_id,
                    guest_name=series.guest_name,
                    start_at=when,
                    service_id=series.service_id,
                    duration_minutes=series.duration_minutes,
                    recurrence_group_id=series.id,
                )
            )
            try:
                session.commit()
            except IntegrityError:  # someone else booked that exact slot first
                session.rollback()
        # The week is considered handled either way — a taken slot is simply
        # skipped, same as a bounded weekly series skips a clashing week.
        series.materialized_through = when
        session.add(series)
        session.commit()
        when += timedelta(weeks=1)


def ensure_materialized_for_barber(session: Session, barber_id: int) -> None:
    """Top up every active perpetual series for one barber's chair."""
    series_list = session.exec(
        select(RecurringSeries).where(RecurringSeries.barber_id == barber_id)
    ).all()
    for series in series_list:
        ensure_materialized(session, series)


def ensure_materialized_for_customer(session: Session, customer_id: int) -> None:
    """Top up every active perpetual series booked by one customer."""
    series_list = session.exec(
        select(RecurringSeries).where(RecurringSeries.customer_id == customer_id)
    ).all()
    for series in series_list:
        ensure_materialized(session, series)
