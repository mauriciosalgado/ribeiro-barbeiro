"""Tests for shop closures: blocking slots and cancelling booked appointments."""

from fastapi.testclient import TestClient

from tests.conftest import register
from tests.test_api import avail, book, first, slot


def close(
    client: TestClient,
    headers: dict,
    start_at: str,
    end_at: str,
    reason: str = "Holiday",
):
    return client.post(
        "/closures",
        json={"start_at": start_at, "end_at": end_at, "reason": reason},
        headers=headers,
    )


def test_only_admin_can_create_a_closure(client: TestClient, barber: dict):
    headers = register(client, "joe@test.com")
    resp = close(
        client,
        headers,
        slot(barber["open_day"], "T09:00:00"),
        slot(barber["open_day"], "T12:00:00"),
    )
    assert resp.status_code == 403


def test_closure_requires_end_after_start(client: TestClient, owner_headers: dict):
    resp = close(client, owner_headers, "2030-01-07T12:00:00", "2030-01-07T09:00:00")
    assert resp.status_code == 422


def test_closure_blocks_availability_and_booking(
    client: TestClient, owner_headers: dict, barber: dict
):
    day = barber["open_day"]
    close(client, owner_headers, slot(day, "T09:00:00"), slot(day, "T11:00:00"))

    slots = avail(client, 1, day).json()
    assert slot(day, "T09:00:00") not in slots
    assert slot(day, "T10:30:00") not in slots
    assert slot(day, "T11:00:00") in slots  # closure end is exclusive

    joe = register(client, "joe@test.com")
    assert book(client, joe, 1, slot(day, "T09:30:00")).status_code == 409
    assert book(client, joe, 1, slot(day, "T11:00:00")).status_code == 201


def test_closing_a_period_cancels_existing_appointments(
    client: TestClient, owner_headers: dict, barber: dict
):
    day = barber["open_day"]
    joe = register(client, "joe@test.com")
    inside = first(book(client, joe, 1, slot(day, "T10:00:00")))
    outside = first(book(client, joe, 1, slot(day, "T14:00:00")))

    close(client, owner_headers, slot(day, "T09:00:00"), slot(day, "T12:00:00"))

    remaining = client.get("/appointments", headers=joe).json()
    ids = [a["id"] for a in remaining]
    assert inside["id"] not in ids  # cancelled by the closure
    assert outside["id"] in ids  # untouched


def test_deleting_a_closure_reopens_the_slots(
    client: TestClient, owner_headers: dict, barber: dict
):
    day = barber["open_day"]
    closure = close(
        client, owner_headers, slot(day, "T09:00:00"), slot(day, "T11:00:00")
    ).json()

    assert slot(day, "T09:00:00") not in avail(client, 1, day).json()
    assert (
        client.delete(f"/closures/{closure['id']}", headers=owner_headers).status_code
        == 204
    )
    assert slot(day, "T09:00:00") in avail(client, 1, day).json()


def test_list_closures(client: TestClient, owner_headers: dict, barber: dict):
    day = barber["open_day"]
    close(client, owner_headers, slot(day, "T09:00:00"), slot(day, "T11:00:00"))
    listed = client.get("/closures").json()
    assert len(listed) == 1
    assert listed[0]["reason"] == "Holiday"
