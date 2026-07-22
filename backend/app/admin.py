"""Prepackaged admin UI (SQLAdmin), mounted at /admin.

CRUD over every table, gated by the same owner login used elsewhere: sign in
with an admin user's email + password. Each view is tuned for visibility —
searchable, sortable, filterable, with the things an owner needs to see up front
(who hasn't verified their email, today's appointments, and so on).
"""

from typing import Any

from fastapi import FastAPI
from markupsafe import Markup
from pydantic import ValidationError
from sqladmin import Admin, ModelView
from sqladmin.authentication import AuthenticationBackend
from sqladmin.filters import BooleanFilter
from sqlmodel import Session, select
from starlette.requests import Request
from wtforms import Form, PasswordField

from app.availability import available_slots, cancel_appointments_between
from app.config import get_settings
from app.database import engine
from app.models import (
    Appointment,
    Barber,
    Closure,
    Service,
    Setting,
    User,
    Weekday,
    WorkingHours,
    WorkingHoursItem,
)
from app.security import authenticate_user, hash_password


def _check(value: bool) -> Markup:
    """Render a boolean as a green tick or a red cross, so it reads at a glance."""
    if value:
        return Markup('<span style="color:#16a34a;font-weight:700">\u2713</span>')
    return Markup('<span style="color:#dc2626;font-weight:700">\u2717</span>')


class AdminAuth(AuthenticationBackend):
    async def login(self, request: Request) -> bool:
        form = await request.form()
        with Session(engine) as session:
            user = authenticate_user(
                session, str(form.get("username", "")), str(form.get("password", ""))
            )
        if user and user.is_admin:
            request.session["user"] = user.email
            return True
        return False

    async def logout(self, request: Request) -> bool:
        request.session.clear()
        return True

    async def authenticate(self, request: Request) -> bool:
        return "user" in request.session


class UserAdmin(ModelView, model=User):
    name = "User"
    icon = "fa-solid fa-user"
    column_list = ["id", "full_name", "email", "phone", "is_verified", "is_admin"]
    column_labels = {
        "full_name": "Name",
        "is_verified": "Verified",
        "is_admin": "Admin",
    }
    column_searchable_list = ["email", "full_name", "phone"]
    column_sortable_list = ["id", "email", "full_name", "is_verified", "is_admin"]
    column_filters = [
        BooleanFilter("is_verified", title="Verified"),
        BooleanFilter("is_admin", title="Admin"),
    ]
    # Unverified first, so accounts that never confirmed their email are obvious.
    column_default_sort = [("is_verified", False), ("id", True)]
    column_formatters = {
        "is_verified": lambda m, a: _check(m.is_verified),
        "is_admin": lambda m, a: _check(m.is_admin),
    }
    form_excluded_columns = ["hashed_password"]  # never edit the raw hash

    async def scaffold_form(self, rules: list[str] | None = None) -> type[Form]:
        form = await super().scaffold_form(rules)
        form.password = PasswordField("Password")
        return form

    async def on_model_change(
        self, data: dict[str, Any], model: Any, is_created: bool, request: Request
    ) -> None:
        password = data.pop("password", None)
        if password:
            data["hashed_password"] = hash_password(password)


class BarberAdmin(ModelView, model=Barber):
    name = "Barber"
    icon = "fa-solid fa-scissors"
    column_list = ["id", "user", "is_active", "allow_recurring"]
    column_labels = {
        "user": "Person",
        "is_active": "Active",
        "allow_recurring": "Weekly repeat",
        "max_recurring_weeks": "Max weeks",
    }
    column_sortable_list = ["id", "is_active"]
    column_filters = [BooleanFilter("is_active", title="Active")]
    column_formatters = {
        "is_active": lambda m, a: _check(m.is_active),
        "allow_recurring": lambda m, a: _check(m.allow_recurring),
    }

    async def after_model_change(
        self, data: dict[str, Any], model: Any, is_created: bool, request: Request
    ) -> None:
        """Seed default services when a barber is created via the admin console."""
        if not is_created:
            return
        from app.seed import seed_default_services

        with Session(engine) as session:
            seed_default_services(session, model.id)
            session.commit()


class ServiceAdmin(ModelView, model=Service):
    name = "Service"
    icon = "fa-solid fa-tag"
    column_list = ["id", "barber", "name", "duration_minutes", "is_active"]
    column_labels = {"duration_minutes": "Minutes", "is_active": "Active"}
    column_sortable_list = ["id", "duration_minutes"]
    column_filters = [BooleanFilter("is_active", title="Active")]
    column_formatters = {"is_active": lambda m, a: _check(m.is_active)}

    async def on_model_change(
        self, data: dict[str, Any], model: Any, is_created: bool, request: Request
    ) -> None:
        minutes = int(data.get("duration_minutes") or 0)
        if not 0 < minutes <= 240:
            raise ValueError("Minutes must be between 1 and 240")


class WorkingHoursAdmin(ModelView, model=WorkingHours):
    name_plural = "Working Hours"
    icon = "fa-solid fa-clock"
    column_list = ["id", "barber", "weekday", "start_time", "end_time"]
    column_labels = {"start_time": "Opens", "end_time": "Closes"}
    column_sortable_list = ["weekday"]

    async def on_model_change(
        self, data: dict[str, Any], model: Any, is_created: bool, request: Request
    ) -> None:
        # Validate through WorkingHoursItem, like the API. The weekday dropdown
        # is already constrained, so the placeholder weekday here is harmless.
        try:
            WorkingHoursItem(
                weekday=next(iter(Weekday)),
                start_time=data["start_time"],
                end_time=data["end_time"],
                break_start=data.get("break_start") or None,
                break_end=data.get("break_end") or None,
            )
        except ValidationError as error:
            message = error.errors()[0]["msg"].removeprefix("Value error, ")
            raise ValueError(message) from error

        # One row per barber per weekday — give a readable message instead of
        # letting the DB's UniqueConstraint surface as a raw IntegrityError.
        barber_id = int(data["barber"]) if data.get("barber") else None
        weekday = data.get("weekday")
        if barber_id and weekday:
            with Session(engine) as session:
                existing = session.exec(
                    select(WorkingHours).where(
                        WorkingHours.barber_id == barber_id,
                        WorkingHours.weekday == weekday,
                    )
                ).first()
                if existing and existing.id != model.id:
                    raise ValueError(
                        "This barber already has working hours for that day — "
                        "edit the existing entry instead of adding another."
                    )


class AppointmentAdmin(ModelView, model=Appointment):
    name = "Appointment"
    icon = "fa-solid fa-calendar-check"
    column_list = [
        "id",
        "start_at",
        "barber",
        "customer",
        "guest_name",
        "duration_minutes",
    ]
    column_labels = {
        "start_at": "When",
        "barber": "Barber",
        "customer": "Customer",
        "guest_name": "Walk-in",
        "duration_minutes": "Minutes",
    }
    column_sortable_list = ["start_at"]
    column_default_sort = [("start_at", True)]  # soonest first
    # Editing is disabled; to move an appointment, cancel it and add a new one.
    can_edit = False

    async def on_model_change(
        self, data: dict[str, Any], model: Any, is_created: bool, request: Request
    ) -> None:
        # Same rules as the booking API: a slot is for a registered customer or
        # a named walk-in, never both, and must be genuinely open.
        barber_id = int(data["barber"]) if data.get("barber") else 0
        customer_raw = data.get("customer")
        customer_id = int(customer_raw) if customer_raw else None
        guest_name = (data.get("guest_name") or "").strip() or None
        start_at = data["start_at"]
        if not barber_id:
            raise ValueError("Choose a barber")
        if customer_id is None and guest_name is None:
            raise ValueError("Choose a customer or enter a walk-in name")
        with Session(engine) as session:
            barber = session.get(Barber, barber_id)
            if barber is None or not barber.is_active:
                raise ValueError("Barber not found or inactive")
            if customer_id is not None and customer_id == barber.user_id:
                raise ValueError("A barber cannot book themselves")
            service_raw = data.get("service")
            if service_raw:
                service = session.get(Service, int(service_raw))
                if service is None or service.barber_id != barber_id:
                    raise ValueError("Service not found for this barber")
                duration = service.duration_minutes
            else:
                duration = int(data.get("duration_minutes") or 30)
            data["duration_minutes"] = duration
            if start_at not in available_slots(
                session, barber, start_at.date(), duration
            ):
                raise ValueError(
                    "Slot is not available (outside working hours, taken, closed, or in the past)"
                )
        # A linked account wins; clear any stray walk-in name so only one is set.
        data["guest_name"] = None if customer_id is not None else guest_name


class ClosureAdmin(ModelView, model=Closure):
    name = "Closure"
    icon = "fa-solid fa-door-closed"
    column_list = ["id", "start_at", "end_at", "reason"]
    column_labels = {"start_at": "From", "end_at": "Until", "reason": "Reason"}
    column_sortable_list = ["start_at", "end_at"]
    column_default_sort = [("start_at", True)]

    async def after_model_change(
        self, data: dict[str, Any], model: Any, is_created: bool, request: Request
    ) -> None:
        # Closing a period cancels any appointments already booked inside it.
        if is_created:
            with Session(engine) as session:
                cancel_appointments_between(session, model.start_at, model.end_at)
                session.commit()


class SettingAdmin(ModelView, model=Setting):
    name = "Setting"
    icon = "fa-solid fa-gear"
    column_list = ["key", "value"]
    column_sortable_list = ["key"]
    column_searchable_list = ["key"]


def setup_admin(app: FastAPI) -> None:
    """Mount the admin UI at /admin, protected by the owner login."""
    auth = AdminAuth(secret_key=get_settings().jwt_secret)
    admin = Admin(app, engine, authentication_backend=auth, title="Shop Admin")
    for view in (
        UserAdmin,
        BarberAdmin,
        ServiceAdmin,
        WorkingHoursAdmin,
        AppointmentAdmin,
        ClosureAdmin,
        SettingAdmin,
    ):
        admin.add_view(view)
