"""Barbers and their weekly working hours."""

from datetime import date, datetime, time, timedelta
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status
from sqlmodel import Session, col, select

from app.availability import (
    MAX_APPOINTMENTS,
    available_slots,
    bookable_barber,
    bookable_service,
    shop_now,
)
from app.database import SessionDep
from app.models import (
    Appointment,
    Barber,
    BarberCreate,
    BarberRead,
    BarberUpdate,
    ScheduledAppointment,
    Service,
    User,
    Weekday,
    WorkingHours,
    WorkingHoursItem,
)
from app.recurrence import ensure_materialized_for_barber
from app.security import AdminUser, CurrentUser
from app.seed import seed_default_services

router = APIRouter(prefix="/barbers", tags=["barbers"])


def _barber_read(barber: Barber, user: User) -> BarberRead:
    assert barber.id is not None
    return BarberRead(
        id=barber.id,
        name=user.full_name,
        is_active=barber.is_active,
        allow_recurring=barber.allow_recurring,
        max_recurring_weeks=barber.max_recurring_weeks,
    )


def _working_hours(session: Session, barber_id: int) -> list[WorkingHours]:
    rows = session.exec(
        select(WorkingHours).where(WorkingHours.barber_id == barber_id)
    ).all()
    order = list(Weekday)
    return sorted(rows, key=lambda w: order.index(w.weekday))


@router.post("", response_model=BarberRead, status_code=status.HTTP_201_CREATED)
def create_barber(
    data: BarberCreate, session: SessionDep, admin: AdminUser
) -> BarberRead:
    user = session.get(User, data.user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
    if session.exec(select(Barber).where(Barber.user_id == data.user_id)).first():
        raise HTTPException(status.HTTP_409_CONFLICT, "User is already a barber")
    barber = Barber(user_id=data.user_id)
    session.add(barber)
    session.commit()
    session.refresh(barber)
    assert barber.id is not None
    seed_default_services(session, barber.id)
    session.commit()
    return _barber_read(barber, user)


@router.get("", response_model=list[BarberRead])
def list_barbers(session: SessionDep) -> list[BarberRead]:
    rows = session.exec(
        select(Barber, User).join(User).where(col(Barber.is_active).is_(True))
    ).all()
    return [_barber_read(barber, user) for barber, user in rows]


@router.get("/me", response_model=BarberRead)
def my_barber(session: SessionDep, user: CurrentUser) -> BarberRead:
    """The barber profile of the logged-in user, or 404 if they aren't one."""
    barber = session.exec(select(Barber).where(Barber.user_id == user.id)).first()
    if barber is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "You are not a barber")
    return _barber_read(barber, user)


@router.patch("/{barber_id}", response_model=BarberRead)
def update_barber(
    barber_id: int, data: BarberUpdate, session: SessionDep, user: CurrentUser
) -> BarberRead:
    """Update a chair's booking settings. Admins edit anyone; a barber only their own."""
    barber = session.get(Barber, barber_id)
    if barber is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Barber not found")
    if not user.is_admin and barber.user_id != user.id:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "Cannot edit another barber's settings"
        )
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(barber, field, value)
    session.add(barber)
    session.commit()
    session.refresh(barber)
    owner = session.get(User, barber.user_id)
    assert owner is not None
    return _barber_read(barber, owner)


@router.get("/{barber_id}/working-hours", response_model=list[WorkingHoursItem])
def get_working_hours(barber_id: int, session: SessionDep) -> list[WorkingHours]:
    return _working_hours(session, barber_id)


@router.put("/{barber_id}/working-hours", response_model=list[WorkingHoursItem])
def set_working_hours(
    barber_id: int, days: list[WorkingHoursItem], session: SessionDep, user: CurrentUser
) -> list[WorkingHours]:
    barber = session.get(Barber, barber_id)
    if barber is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Barber not found")
    # An admin manages anyone's schedule; a barber manages only their own.
    if not user.is_admin and barber.user_id != user.id:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "Cannot edit another barber's schedule"
        )
    if len({d.weekday for d in days}) != len(days):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Duplicate weekday")

    for existing in session.exec(
        select(WorkingHours).where(WorkingHours.barber_id == barber_id)
    ).all():
        session.delete(existing)
    session.flush()  # apply deletes before inserts so the unique index doesn't clash
    for day in days:
        session.add(WorkingHours(barber_id=barber_id, **day.model_dump()))
    session.commit()

    return _working_hours(session, barber_id)


@router.get("/{barber_id}/appointments", response_model=list[ScheduledAppointment])
def barber_schedule(
    barber_id: int,
    session: SessionDep,
    user: CurrentUser,
    day: Annotated[date | None, Query(alias="date")] = None,
) -> list[ScheduledAppointment]:
    barber = session.get(Barber, barber_id)
    if barber is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Barber not found")
    # A barber sees only their own bookings; an admin sees anyone's.
    if not user.is_admin and barber.user_id != user.id:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "Cannot view another barber's schedule"
        )
    ensure_materialized_for_barber(session, barber_id)

    query = (
        select(Appointment, User, Service)
        .outerjoin(User, col(Appointment.customer_id) == col(User.id))
        .outerjoin(Service, col(Appointment.service_id) == col(Service.id))
        .where(Appointment.barber_id == barber_id)
    )
    if day is not None:
        day_start = datetime.combine(day, time.min)
        query = query.where(
            Appointment.start_at >= day_start,
            Appointment.start_at < day_start + timedelta(days=1),
        )
    else:
        # Default view: upcoming only, so years of history never bloat the list.
        query = query.where(
            Appointment.start_at >= datetime.combine(shop_now().date(), time.min)
        )
    rows = session.exec(
        query.order_by(col(Appointment.start_at)).limit(MAX_APPOINTMENTS)
    ).all()
    return [
        ScheduledAppointment(
            id=appointment.id,  # type: ignore[arg-type]
            start_at=appointment.start_at,
            customer_name=customer.full_name
            if customer
            else (appointment.guest_name or "Guest"),
            customer_email=customer.email if customer else "",
            customer_phone=(customer.phone or "") if customer else "",
            service_id=appointment.service_id,
            service_name=service.name if service else "",
            duration_minutes=appointment.duration_minutes,
            recurrence_group_id=appointment.recurrence_group_id,
        )
        for appointment, customer, service in rows
    ]


@router.get("/{barber_id}/availability", response_model=list[datetime])
def availability(
    barber_id: int,
    day: Annotated[date, Query(alias="date")],
    service_id: int,
    session: SessionDep,
) -> list[datetime]:
    barber = bookable_barber(session, barber_id)  # 404s if missing or inactive
    service = bookable_service(session, barber, service_id)
    return available_slots(session, barber, day, service.duration_minutes)
