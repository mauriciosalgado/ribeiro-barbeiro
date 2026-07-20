"""Services — the kinds of appointment a barber offers, and their durations."""

from fastapi import APIRouter, HTTPException, status
from sqlmodel import col, select

from app.database import SessionDep
from app.models import (
    Appointment,
    Barber,
    Service,
    ServiceCreate,
    ServiceItem,
    ServiceRead,
    ServiceUpdate,
)
from app.security import CurrentUser

router = APIRouter(tags=["services"])


def _staff_for(barber: Barber, user: CurrentUser) -> None:
    """Allow the barber whose chair it is, or any admin; else 403."""
    if not user.is_admin and barber.user_id != user.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not your chair")


@router.get("/barbers/{barber_id}/services", response_model=list[ServiceRead])
def list_services(barber_id: int, session: SessionDep) -> list[Service]:
    """A barber's active services — what a customer chooses from when booking."""
    return list(
        session.exec(
            select(Service)
            .where(Service.barber_id == barber_id, col(Service.is_active).is_(True))
            .order_by(col(Service.id))
        ).all()
    )


@router.get("/barbers/{barber_id}/services/all", response_model=list[ServiceRead])
def list_all_services(
    barber_id: int, session: SessionDep, user: CurrentUser
) -> list[Service]:
    """Every service including inactive ones — for the barber's own editor."""
    barber = session.get(Barber, barber_id)
    if barber is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Barber not found")
    _staff_for(barber, user)
    return list(
        session.exec(
            select(Service)
            .where(Service.barber_id == barber_id)
            .order_by(col(Service.id))
        ).all()
    )


@router.put("/barbers/{barber_id}/services", response_model=list[ServiceRead])
def replace_services(
    barber_id: int, items: list[ServiceItem], session: SessionDep, user: CurrentUser
) -> list[Service]:
    """Replace a barber's service menu in one shot.

    Items with an ``id`` update the existing row; items without one create a new
    service. Existing services not in the list are deleted (if unused) or
    deactivated (if already referenced by bookings).
    """
    barber = session.get(Barber, barber_id)
    if barber is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Barber not found")
    _staff_for(barber, user)

    if not items:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "A barber must have at least one service",
        )

    existing = {
        s.id: s
        for s in session.exec(
            select(Service).where(Service.barber_id == barber_id)
        ).all()
    }
    sent_ids: set[int] = set()

    result: list[Service] = []
    for item in items:
        if item.id is not None and item.id in existing:
            # Update existing service.
            svc = existing[item.id]
            svc.name = item.name
            svc.duration_minutes = item.duration_minutes
            svc.is_active = item.is_active
            session.add(svc)
            sent_ids.add(item.id)
            result.append(svc)
        else:
            # New service.
            svc = Service(
                barber_id=barber_id,
                name=item.name,
                duration_minutes=item.duration_minutes,
                is_active=item.is_active,
            )
            session.add(svc)
            result.append(svc)

    # Services not in the request: delete if unused, deactivate if referenced.
    for old_id, old_svc in existing.items():
        if old_id in sent_ids:
            continue
        in_use = session.exec(
            select(Appointment).where(Appointment.service_id == old_id).limit(1)
        ).first()
        if in_use:
            old_svc.is_active = False
            session.add(old_svc)
        else:
            session.delete(old_svc)

    session.commit()
    # Return the full current list (including newly-assigned ids).
    return list(
        session.exec(
            select(Service)
            .where(Service.barber_id == barber_id)
            .order_by(col(Service.id))
        ).all()
    )


@router.post(
    "/barbers/{barber_id}/services",
    response_model=ServiceRead,
    status_code=status.HTTP_201_CREATED,
)
def create_service(
    barber_id: int, data: ServiceCreate, session: SessionDep, user: CurrentUser
) -> Service:
    barber = session.get(Barber, barber_id)
    if barber is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Barber not found")
    _staff_for(barber, user)
    service = Service(barber_id=barber_id, **data.model_dump())
    session.add(service)
    session.commit()
    session.refresh(service)
    return service


@router.patch("/services/{service_id}", response_model=ServiceRead)
def update_service(
    service_id: int, data: ServiceUpdate, session: SessionDep, user: CurrentUser
) -> Service:
    service = session.get(Service, service_id)
    if service is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Service not found")
    barber = session.get(Barber, service.barber_id)
    assert barber is not None
    _staff_for(barber, user)
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(service, field, value)
    session.add(service)
    session.commit()
    session.refresh(service)
    return service


@router.delete("/services/{service_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_service(service_id: int, session: SessionDep, user: CurrentUser) -> None:
    """Remove a service. If bookings still use it, deactivate it instead (409)."""
    service = session.get(Service, service_id)
    if service is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Service not found")
    barber = session.get(Barber, service.barber_id)
    assert barber is not None
    _staff_for(barber, user)
    in_use = session.exec(
        select(Appointment).where(Appointment.service_id == service_id).limit(1)
    ).first()
    if in_use is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Service is in use; deactivate it instead of deleting",
        )
    session.delete(service)
    session.commit()
