"""A barber's weekly working hours, with an optional lunch break."""

from datetime import date, time
from enum import Enum

from pydantic import model_validator
from sqlalchemy import UniqueConstraint
from sqlmodel import Field, Relationship, SQLModel

from app.models.barber import Barber


class Weekday(str, Enum):
    MONDAY = "Monday"
    TUESDAY = "Tuesday"
    WEDNESDAY = "Wednesday"
    THURSDAY = "Thursday"
    FRIDAY = "Friday"
    SATURDAY = "Saturday"
    SUNDAY = "Sunday"

    @staticmethod
    def of(day: date) -> "Weekday":
        """The weekday a calendar date falls on (this enum is Monday-first)."""
        return list(Weekday)[day.weekday()]


class WorkingHours(SQLModel, table=True):
    # One row per barber per weekday.
    __table_args__ = (UniqueConstraint("barber_id", "weekday"),)

    id: int | None = Field(default=None, primary_key=True)
    barber_id: int = Field(foreign_key="barber.id", ondelete="CASCADE")
    weekday: Weekday
    start_time: time
    end_time: time
    break_start: time | None = None
    break_end: time | None = None

    barber: Barber | None = Relationship()


class WorkingHoursItem(SQLModel):
    weekday: Weekday
    start_time: time
    end_time: time
    break_start: time | None = None
    break_end: time | None = None

    @model_validator(mode="after")
    def check(self) -> "WorkingHoursItem":
        if self.start_time >= self.end_time:
            raise ValueError("start_time must be before end_time")
        if (self.break_start is None) != (self.break_end is None):
            raise ValueError("break_start and break_end must be set together")
        if self.break_start is not None and self.break_end is not None:
            if not (
                self.start_time <= self.break_start < self.break_end <= self.end_time
            ):
                raise ValueError("the break must fall within working hours")
        return self
