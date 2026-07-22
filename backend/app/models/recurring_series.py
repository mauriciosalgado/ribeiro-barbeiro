"""A perpetual weekly booking pattern — "every Monday at 10:00, forever".

Unlike a bounded weekly series (which materialises every week up front, see
``AppointmentCreate.repeat_weeks``), a perpetual series stores only the
pattern itself. Real ``Appointment`` rows for it are created lazily, a
rolling window at a time — see ``app.recurrence``.
"""

from datetime import date, datetime

from sqlmodel import Field, SQLModel


class RecurringSeries(SQLModel, table=True):
    # The id doubles as the recurrence_group_id shared by its Appointment rows.
    id: str = Field(primary_key=True)
    barber_id: int = Field(foreign_key="barber.id", ondelete="CASCADE")
    customer_id: int | None = Field(
        default=None, foreign_key="user.id", ondelete="CASCADE"
    )
    guest_name: str | None = None
    service_id: int | None = Field(
        default=None, foreign_key="service.id", ondelete="SET NULL"
    )
    # The first occurrence — its weekday and time of day define the pattern.
    anchor_start_at: datetime
    duration_minutes: int = 30
    # Appointment rows exist up to (and including) this point; extended
    # lazily by ensure_materialized() whenever it falls within the window.
    materialized_through: datetime


class RecurringSeriesRead(SQLModel):
    """One row of the "Horários Fixos" (standing-appointment) list.

    Covers both flavours of weekly recurrence: a perpetual series (no end,
    ``ends_at`` is None) and a bounded weekly series (ends on the date of its
    last upcoming occurrence).
    """

    id: str
    kind: str  # "perpetual" | "bounded"
    barber_id: int
    barber_name: str = ""
    customer_name: str = ""
    customer_email: str = ""  # empty for a walk-in with no account
    customer_phone: str = ""  # empty for a walk-in, or an account with none on file
    service_id: int | None
    service_name: str = ""
    anchor_start_at: datetime
    duration_minutes: int
    ends_at: date | None = None
