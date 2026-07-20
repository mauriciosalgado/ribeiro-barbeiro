"""Tests for lead-time, cancel cut-off, barber schedule, and normalization."""

from datetime import timedelta

from fastapi.testclient import TestClient
from sqlmodel import Session

from app.availability import shop_now
from app.database import engine
from app.models import Appointment
from tests.conftest import OWNER, auth, register
from tests.test_api import avail, book, first, slot


# --- barber schedule ----------------------------------------------------


def test_barber_sees_who_booked_with_them(
    client: TestClient, owner_headers: dict, barber: dict
):
    joe = register(client, "joe@test.com")
    book(client, joe, 1, slot(barber["open_day"]))

    schedule = client.get("/barbers/1/appointments", headers=owner_headers).json()
    assert len(schedule) == 1
    assert schedule[0]["customer_email"] == "joe@test.com"
    assert schedule[0]["customer_name"] == "Customer"


def test_customer_cannot_view_a_barber_schedule(client: TestClient, barber: dict):
    joe = register(client, "joe@test.com")
    assert client.get("/barbers/1/appointments", headers=joe).status_code == 403


def test_barbers_me_identifies_the_logged_in_barber(
    client: TestClient, owner_headers: dict, barber: dict
):
    resp = client.get("/barbers/me", headers=owner_headers)
    assert resp.status_code == 200
    assert resp.json()["id"] == 1


def test_barbers_me_404_for_a_customer(client: TestClient, barber: dict):
    joe = register(client, "joe@test.com")
    assert client.get("/barbers/me", headers=joe).status_code == 404


def test_schedule_can_be_filtered_by_date(
    client: TestClient, owner_headers: dict, barber: dict
):
    joe = register(client, "joe@test.com")
    book(client, joe, 1, slot(barber["open_day"]))

    same_day = client.get(
        f"/barbers/1/appointments?date={barber['open_day']}", headers=owner_headers
    ).json()
    other_day = client.get(
        f"/barbers/1/appointments?date={barber['closed_day']}", headers=owner_headers
    ).json()
    assert len(same_day) == 1
    assert other_day == []


# --- cancellation cut-off ----------------------------------------------


def _book_directly(client: TestClient, headers: dict, minutes_ahead: int) -> int:
    """Insert an imminent appointment straight into the DB (bypassing lead time)."""
    customer_id = client.get("/auth/me", headers=headers).json()["id"]
    with Session(engine) as session:
        appt = Appointment(
            barber_id=1,
            customer_id=customer_id,
            start_at=shop_now() + timedelta(minutes=minutes_ahead),
        )
        session.add(appt)
        session.commit()
        session.refresh(appt)
        assert appt.id is not None
        return appt.id


def test_customer_cannot_cancel_within_the_cutoff(client: TestClient, barber: dict):
    joe = register(client, "joe@test.com")
    appt_id = _book_directly(client, joe, minutes_ahead=30)
    assert client.delete(f"/appointments/{appt_id}", headers=joe).status_code == 403


def test_admin_can_cancel_within_the_cutoff(
    client: TestClient, owner_headers: dict, barber: dict
):
    joe = register(client, "joe@test.com")
    appt_id = _book_directly(client, joe, minutes_ahead=30)
    assert (
        client.delete(f"/appointments/{appt_id}", headers=owner_headers).status_code
        == 204
    )


# --- lead time ----------------------------------------------------------


def test_availability_excludes_slots_within_the_lead_time(
    client: TestClient, barber: dict
):
    today = shop_now().date()
    earliest = shop_now() + timedelta(hours=1)
    slots = avail(client, 1, today).json()
    assert all(s >= earliest.isoformat() for s in slots)


# --- normalization ------------------------------------------------------


def test_email_is_normalized_on_register_and_login(client: TestClient):
    client.post(
        "/auth/register",
        json={"email": "  JOE@Test.com ", "full_name": "Joe", "password": "secret123"},
    )
    headers = auth(client, "joe@test.com", "secret123")
    assert client.get("/auth/me", headers=headers).json()["email"] == "joe@test.com"


def test_timezone_aware_booking_is_converted_to_shop_local(
    client: TestClient, barber: dict
):
    headers = register(client, "joe@test.com")
    # Shop timezone is UTC in tests; 10:00+01:00 is 09:00 shop-local.
    resp = book(client, headers, 1, f"{barber['open_day']}T10:00:00+01:00")
    assert resp.status_code == 201
    assert first(resp)["start_at"].endswith("T09:00:00")


def test_owner_login_still_works(client: TestClient):
    headers = auth(client, OWNER["username"], OWNER["password"])
    assert client.get("/auth/me", headers=headers).status_code == 200
