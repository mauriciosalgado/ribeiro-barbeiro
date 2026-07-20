"""Appointments — a customer's booked slot with a barber."""

from datetime import datetime
from typing import Annotated
from zoneinfo import ZoneInfo

from pydantic import AfterValidator
from sqlalchemy import UniqueConstraint
from sqlmodel import Field, Relationship, SQLModel

from app.config import get_settings
from app.models.barber import Barber
from app.models.user import User


def to_shop_local_naive(value: datetime) -> datetime:
    """Store times as naive shop-local, matching how slots are generated.

    A timezone-aware time (e.g. from a phone in another zone) is converted
    into the shop's timezone; a naive time is assumed to already be local.
    """
    if value.tzinfo is None:
        return value
    return value.astimezone(ZoneInfo(get_settings().shop_timezone)).replace(tzinfo=None)


# A datetime that is always stored as naive, shop-local time.
ShopLocalDatetime = Annotated[datetime, AfterValidator(to_shop_local_naive)]


class Appointment(SQLModel, table=True):
    # A barber can't be booked twice for the same time.
    __table_args__ = (UniqueConstraint("barber_id", "start_at"),)

    id: int | None = Field(default=None, primary_key=True)
    barber_id: int = Field(foreign_key="barber.id", ondelete="CASCADE")
    # A booking is for a registered user (customer_id) or a walk-in (guest_name).
    # Exactly one is set; the barber can book either from the admin views.
    customer_id: int | None = Field(
        default=None, foreign_key="user.id", ondelete="CASCADE"
    )
    guest_name: str | None = None
    start_at: datetime
    # The chosen service and a snapshot of its length, so the slot's occupancy is
    # fixed even if the service is later re-timed. Switching service updates both.
    service_id: int | None = Field(
        default=None, foreign_key="service.id", ondelete="SET NULL"
    )
    duration_minutes: int = 30
    # Weekly-repeat bookings share one id, so a whole series can be managed together.
    recurrence_group_id: str | None = None

    barber: Barber | None = Relationship()
    customer: User | None = Relationship()


class AppointmentCreate(SQLModel):
    barber_id: int
    service_id: int
    start_at: ShopLocalDatetime
    repeat_weeks: int = Field(default=1, ge=1, le=52)  # 1 = a single booking


class ManualAppointmentCreate(SQLModel):
    """A booking the barber makes for someone else.

    Give ``customer_email`` to book an existing account, or leave it blank and
    give ``customer_name`` for a walk-in who has no account.
    """

    barber_id: int
    service_id: int
    start_at: ShopLocalDatetime
    customer_name: str = ""
    customer_email: str = ""
    repeat_weeks: int = Field(default=1, ge=1, le=52)


class ServiceSwitch(SQLModel):
    """Change a booked appointment to a different service (staff only)."""

    service_id: int


class AppointmentRead(SQLModel):
    id: int
    barber_id: int
    customer_id: int | None
    guest_name: str | None
    start_at: datetime
    service_id: int | None
    duration_minutes: int
    recurrence_group_id: str | None


class BookingResult(SQLModel):
    """The outcome of a booking: what was booked and which weeks were skipped.

    A single booking returns one appointment and no skips; a weekly series may
    skip weeks that were already taken.
    """

    booked: list[AppointmentRead]
    skipped: list[datetime]


class ScheduledAppointment(SQLModel):
    """A booked slot as the barber sees it, with who booked it."""

    id: int
    start_at: datetime
    customer_name: str
    customer_email: str = ""  # empty for a walk-in with no account
    service_id: int | None = None
    service_name: str = ""
    duration_minutes: int = 30
    recurrence_group_id: str | None = None
