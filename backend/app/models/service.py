"""Services — the kinds of appointment a barber offers (e.g. haircut, beard)."""

from sqlmodel import Field, Relationship, SQLModel

from app.models.barber import Barber


class Service(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    barber_id: int = Field(foreign_key="barber.id", ondelete="CASCADE")
    # Lets SQLAdmin render a barber picker on the create/edit form — a bare
    # FK column has no related model to build a dropdown from. Mirrors the
    # same Relationship already on WorkingHours and Appointment.
    barber: Barber | None = Relationship()
    name: str
    duration_minutes: int = Field(default=30, gt=0, le=240)
    is_active: bool = True

    def __str__(self) -> str:
        return f"{self.name} ({self.duration_minutes} min)"


class ServiceItem(SQLModel):
    """One entry in the bulk PUT — an existing service (with id) or a new one (without)."""

    id: int | None = None
    name: str = Field(min_length=1, max_length=60)
    duration_minutes: int = Field(default=30, gt=0, le=240)
    is_active: bool = True


class ServiceCreate(SQLModel):
    name: str = Field(min_length=1, max_length=60)
    duration_minutes: int = Field(default=30, gt=0, le=240)


class ServiceUpdate(SQLModel):
    """A partial edit: only the fields that are sent change."""

    name: str | None = Field(default=None, min_length=1, max_length=60)
    duration_minutes: int | None = Field(default=None, gt=0, le=240)
    is_active: bool | None = None


class ServiceRead(SQLModel):
    id: int
    barber_id: int
    name: str
    duration_minutes: int
    is_active: bool
