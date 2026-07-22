"""Model exports. Importing them registers each table on SQLModel's metadata."""

from app.models.appointment import (
    Appointment,
    AppointmentCreate,
    AppointmentRead,
    BookingResult,
    ManualAppointmentCreate,
    ScheduledAppointment,
    ServiceSwitch,
)
from app.models.barber import Barber, BarberCreate, BarberRead, BarberUpdate
from app.models.closure import Closure, ClosureCreate, ClosureRead
from app.models.recurring_series import RecurringSeries, RecurringSeriesRead
from app.models.service import (
    Service,
    ServiceCreate,
    ServiceItem,
    ServiceRead,
    ServiceUpdate,
)
from app.models.setting import Setting
from app.models.user import User, UserCreate, UserRead, UserUpdate
from app.models.working_hours import Weekday, WorkingHours, WorkingHoursItem

__all__ = [
    "Appointment",
    "AppointmentCreate",
    "AppointmentRead",
    "BookingResult",
    "ManualAppointmentCreate",
    "ScheduledAppointment",
    "ServiceSwitch",
    "Barber",
    "BarberCreate",
    "BarberRead",
    "BarberUpdate",
    "Closure",
    "ClosureCreate",
    "ClosureRead",
    "RecurringSeries",
    "RecurringSeriesRead",
    "Service",
    "ServiceCreate",
    "ServiceItem",
    "ServiceRead",
    "ServiceUpdate",
    "Setting",
    "User",
    "UserCreate",
    "UserRead",
    "UserUpdate",
    "Weekday",
    "WorkingHours",
    "WorkingHoursItem",
]
