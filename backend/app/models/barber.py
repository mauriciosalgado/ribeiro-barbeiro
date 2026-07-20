"""Barbers — a user who provides haircuts."""

from sqlmodel import Field, Relationship, SQLModel

from app.models.user import User


class Barber(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="user.id", unique=True, ondelete="CASCADE")
    is_active: bool = True
    # Let customers book the same slot every week, up to max_recurring_weeks ahead.
    allow_recurring: bool = False
    max_recurring_weeks: int = 12

    user: User | None = Relationship(sa_relationship_kwargs={"lazy": "selectin"})

    def __str__(self) -> str:
        return self.user.full_name if self.user else f"Barber {self.id}"


class BarberCreate(SQLModel):
    user_id: int


class BarberRead(SQLModel):
    id: int
    name: str
    is_active: bool
    allow_recurring: bool
    max_recurring_weeks: int


class BarberUpdate(SQLModel):
    """A partial edit of a chair's booking settings; only sent fields change."""

    allow_recurring: bool | None = None
    max_recurring_weeks: int | None = Field(default=None, ge=1, le=52)
