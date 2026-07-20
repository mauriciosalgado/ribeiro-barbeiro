"""Shop closures — periods when no appointments can be booked."""

from datetime import datetime

from pydantic import model_validator
from sqlmodel import Field, SQLModel


class Closure(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    start_at: datetime
    end_at: datetime
    reason: str | None = None

    def __str__(self) -> str:
        return f"{self.start_at:%Y-%m-%d %H:%M} → {self.end_at:%Y-%m-%d %H:%M}"


class ClosureCreate(SQLModel):
    start_at: datetime
    end_at: datetime
    reason: str | None = None

    @model_validator(mode="after")
    def check(self) -> "ClosureCreate":
        if self.start_at >= self.end_at:
            raise ValueError("start_at must be before end_at")
        return self


class ClosureRead(SQLModel):
    id: int
    start_at: datetime
    end_at: datetime
    reason: str | None
