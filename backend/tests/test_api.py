"""Integration tests for the booking API."""

from datetime import datetime, timedelta

from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.database import engine
from app.models import Appointment, Barber
from tests.conftest import register

SLOT_9 = "T09:00:00"

# Services the fixtures seed for barber 1: "Corte" (30m), "Barba" (15m).
HAIRCUT = 1
BEARD = 2


def slot(day: object, hhmmss: str = SLOT_9) -> str:
    return f"{day}{hhmmss}"


def book(
    client: TestClient,
    headers: dict,
    barber_id: int,
    start_at: str,
    service_id: int = HAIRCUT,
    repeat_weeks: int = 1,
    perpetual: bool = False,
):
    return client.post(
        "/appointments",
        json={
            "barber_id": barber_id,
            "start_at": start_at,
            "service_id": service_id,
            "repeat_weeks": repeat_weeks,
            "perpetual": perpetual,
        },
        headers=headers,
    )


def book_manual(
    client: TestClient, headers: dict, start_at: str, service_id: int = HAIRCUT, **who
):
    return client.post(
        "/appointments/manual",
        json={"barber_id": 1, "start_at": start_at, "service_id": service_id, **who},
        headers=headers,
    )


def first(resp):
    """The first booked appointment out of a BookingResult response."""
    return resp.json()["booked"][0]


def avail(client: TestClient, barber_id: int, day: object, service_id: int = HAIRCUT):
    return client.get(
        f"/barbers/{barber_id}/availability",
        params={"date": str(day), "service_id": service_id},
    )


# --- auth ---------------------------------------------------------------


def test_health(client: TestClient):
    assert client.get("/health").json()["status"] == "ok"


def test_register_login_me(client: TestClient):
    headers = register(client, "joe@test.com")
    me = client.get("/auth/me", headers=headers).json()
    assert me["email"] == "joe@test.com"
    assert me["phone"] is None
    assert "hashed_password" not in me  # password never leaves the server


def test_update_own_profile(client: TestClient):
    headers = register(client, "joe@test.com")
    resp = client.patch(
        "/auth/me",
        json={"full_name": "Joe Fresh", "phone": " 912345678 "},
        headers=headers,
    )
    assert resp.status_code == 200
    me = resp.json()
    assert me["full_name"] == "Joe Fresh"
    assert me["phone"] == "912345678"  # trimmed


def test_profile_blank_name_is_rejected(client: TestClient):
    headers = register(client, "joe@test.com")
    resp = client.patch("/auth/me", json={"full_name": "   "}, headers=headers)
    assert resp.status_code == 422


def test_profile_blank_phone_becomes_null(client: TestClient):
    headers = register(client, "joe@test.com")
    resp = client.patch(
        "/auth/me", json={"full_name": "Joe", "phone": "  "}, headers=headers
    )
    assert resp.status_code == 200
    assert resp.json()["phone"] is None


def test_profile_update_needs_auth(client: TestClient):
    assert client.patch("/auth/me", json={"full_name": "X"}).status_code == 401


def test_seed_keeps_the_owners_edited_name(client: TestClient, owner_headers: dict):
    """Editing your own name must survive a restart (re-seed), like the password."""
    from app.seed import seed_owner

    client.patch(
        "/auth/me",
        json={"full_name": "Paquito Ribeiro", "phone": "912345678"},
        headers=owner_headers,
    )
    seed_owner()  # what runs on every startup
    me = client.get("/auth/me", headers=owner_headers).json()
    assert me["full_name"] == "Paquito Ribeiro"  # not reset to config
    assert me["phone"] == "912345678"
    assert me["is_admin"] is True  # role is still guaranteed


def test_duplicate_email_is_rejected(client: TestClient):
    register(client, "joe@test.com")
    dup = client.post(
        "/auth/register",
        json={"email": "joe@test.com", "full_name": "X", "password": "secret123"},
    )
    assert dup.status_code == 409


def test_protected_endpoint_needs_a_token(client: TestClient):
    assert client.get("/auth/me").status_code == 401
    assert (
        client.get("/auth/me", headers={"Authorization": "Bearer junk"}).status_code
        == 401
    )


# --- barbers ------------------------------------------------------------


def test_only_admin_can_create_a_barber(client: TestClient):
    headers = register(client, "joe@test.com")
    resp = client.post("/barbers", json={"user_id": 1}, headers=headers)
    assert resp.status_code == 403


def test_listing_shows_only_active_barbers(client: TestClient, barber: dict):
    assert len(client.get("/barbers").json()) == 1


# --- working hours ------------------------------------------------------


def test_working_hours_validation(
    client: TestClient, owner_headers: dict, barber: dict
):
    def put(day: dict):
        return client.put("/barbers/1/working-hours", json=[day], headers=owner_headers)

    base = {"start_time": "09:00", "end_time": "17:00"}
    assert put({"weekday": "Funday", **base}).status_code == 422
    assert (
        put(
            {"weekday": "Monday", "start_time": "17:00", "end_time": "09:00"}
        ).status_code
        == 422
    )
    assert (
        put(
            {"weekday": "Monday", **base, "break_start": "08:00", "break_end": "08:30"}
        ).status_code
        == 422
    )


def test_only_owner_or_admin_edits_schedule(client: TestClient, barber: dict):
    headers = register(client, "joe@test.com")
    resp = client.put(
        "/barbers/1/working-hours",
        json=[{"weekday": "Monday", "start_time": "09:00", "end_time": "17:00"}],
        headers=headers,
    )
    assert resp.status_code == 403


# --- availability -------------------------------------------------------


def test_services_share_one_fixed_grid(client: TestClient, barber: dict):
    """Every service starts on the same grid (the GCD of service lengths = 15)."""
    day = barber["open_day"]
    haircut = avail(client, 1, day, HAIRCUT).json()  # 30-minute service
    beard = avail(client, 1, day, BEARD).json()  # 15-minute service
    assert haircut[:3] == [
        slot(day, "T09:00:00"),
        slot(day, "T09:15:00"),
        slot(day, "T09:30:00"),
    ]
    assert beard[:3] == [
        slot(day, "T09:00:00"),
        slot(day, "T09:15:00"),
        slot(day, "T09:30:00"),
    ]
    # 09-17 minus a one-hour lunch on a 15-min grid: 28 beard starts, and 26
    # haircut starts (the extra 30-min tail can't finish before the break/close).
    assert len(beard) == 28
    assert len(haircut) == 26


def test_slots_pack_against_an_earlier_booking(
    client: TestClient, owner_headers: dict, barber: dict
):
    """A 15-min booking frees an odd edge; a 30-min service starts right there."""
    day = barber["open_day"]
    book_manual(client, owner_headers, slot(day), service_id=BEARD, customer_name="Zé")
    haircut = avail(client, 1, day, HAIRCUT).json()
    assert slot(day, "T09:00:00") not in haircut  # taken by the beard (09:00-09:15)
    assert slot(day, "T09:15:00") in haircut  # 30-min cut packs right after it
    assert slot(day, "T09:30:00") in haircut  # and the grid still offers 09:30


def test_owner_updates_recurrence_policy(
    client: TestClient, owner_headers: dict, barber: dict
):
    resp = client.patch(
        "/barbers/1",
        json={"allow_recurring": True, "max_recurring_weeks": 6},
        headers=owner_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["allow_recurring"] is True
    assert resp.json()["max_recurring_weeks"] == 6


def test_recurrence_cap_out_of_range_rejected(
    client: TestClient, owner_headers: dict, barber: dict
):
    assert (
        client.patch(
            "/barbers/1", json={"max_recurring_weeks": 100}, headers=owner_headers
        ).status_code
        == 422
    )


def test_only_owner_or_self_updates_barber(client: TestClient, barber: dict):
    headers = register(client, "joe@test.com")
    resp = client.patch("/barbers/1", json={"allow_recurring": True}, headers=headers)
    assert resp.status_code == 403


def test_availability_open_day_excludes_lunch(client: TestClient, barber: dict):
    slots = avail(
        client, 1, barber["open_day"]
    ).json()  # 30-min haircut on a 15-min grid
    assert (
        len(slots) == 26
    )  # 09-17 minus a one-hour lunch, minus the pre-lunch/close tails


def test_availability_closed_day_is_empty(client: TestClient, barber: dict):
    slots = avail(client, 1, barber["closed_day"]).json()
    assert slots == []


def test_availability_unknown_barber_404(client: TestClient):
    assert avail(client, 99, "2030-01-07").status_code == 404


# --- booking rules ------------------------------------------------------


def test_book_a_free_slot(client: TestClient, barber: dict):
    headers = register(client, "joe@test.com")
    resp = book(client, headers, 1, slot(barber["open_day"]))
    assert resp.status_code == 201
    assert first(resp)["start_at"].startswith(str(barber["open_day"]))
    assert first(resp)["duration_minutes"] == 30


def test_cannot_book_when_shop_is_closed(client: TestClient, barber: dict):
    headers = register(client, "joe@test.com")
    assert book(client, headers, 1, slot(barber["closed_day"])).status_code == 409


def test_cannot_book_outside_working_hours(client: TestClient, barber: dict):
    headers = register(client, "joe@test.com")
    assert (
        book(client, headers, 1, slot(barber["open_day"], "T18:00:00")).status_code
        == 409
    )


def test_cannot_book_off_the_grid(client: TestClient, barber: dict):
    headers = register(client, "joe@test.com")
    # 09:07 falls between the 15-minute grid points, so it's never on offer.
    assert (
        book(client, headers, 1, slot(barber["open_day"], "T09:07:00")).status_code
        == 409
    )


def test_cannot_book_during_lunch(client: TestClient, barber: dict):
    headers = register(client, "joe@test.com")
    assert (
        book(client, headers, 1, slot(barber["open_day"], "T12:00:00")).status_code
        == 409
    )


def test_cannot_book_in_the_past(client: TestClient, barber: dict):
    headers = register(client, "joe@test.com")
    assert book(client, headers, 1, slot(barber["past_day"])).status_code == 409


def test_a_slot_cannot_be_double_booked(client: TestClient, barber: dict):
    joe = register(client, "joe@test.com")
    eve = register(client, "eve@test.com")
    assert book(client, joe, 1, slot(barber["open_day"])).status_code == 201
    assert book(client, eve, 1, slot(barber["open_day"])).status_code == 409


def test_a_barber_cannot_book_themselves(
    client: TestClient, owner_headers: dict, barber: dict
):
    assert book(client, owner_headers, 1, slot(barber["open_day"])).status_code == 403


def test_cannot_book_an_inactive_barber(
    client: TestClient, owner_headers: dict, barber: dict
):
    with Session(engine) as session:
        b = session.get(Barber, 1)
        assert b is not None
        b.is_active = False
        session.add(b)
        session.commit()

    headers = register(client, "joe@test.com")
    assert book(client, headers, 1, slot(barber["open_day"])).status_code == 404


def test_booking_requires_authentication(client: TestClient, barber: dict):
    resp = client.post(
        "/appointments",
        json={"barber_id": 1, "start_at": slot(barber["open_day"])},
    )
    assert resp.status_code == 401


# --- listing & cancelling ----------------------------------------------


def test_my_appointments_lists_own_bookings(client: TestClient, barber: dict):
    headers = register(client, "joe@test.com")
    book(client, headers, 1, slot(barber["open_day"]))
    mine = client.get("/appointments", headers=headers).json()
    assert len(mine) == 1
    assert mine[0]["barber_id"] == 1


def test_cancel_frees_the_slot(client: TestClient, barber: dict):
    headers = register(client, "joe@test.com")
    appt = first(book(client, headers, 1, slot(barber["open_day"])))
    assert (
        client.delete(f"/appointments/{appt['id']}", headers=headers).status_code == 204
    )
    freed = avail(client, 1, barber["open_day"]).json()
    assert slot(barber["open_day"]) in freed


def test_cannot_cancel_someone_elses_appointment(client: TestClient, barber: dict):
    joe = register(client, "joe@test.com")
    eve = register(client, "eve@test.com")
    appt = first(book(client, joe, 1, slot(barber["open_day"])))
    assert client.delete(f"/appointments/{appt['id']}", headers=eve).status_code == 403


def test_admin_can_cancel_any_appointment(
    client: TestClient, owner_headers: dict, barber: dict
):
    joe = register(client, "joe@test.com")
    appt = first(book(client, joe, 1, slot(barber["open_day"])))
    assert (
        client.delete(f"/appointments/{appt['id']}", headers=owner_headers).status_code
        == 204
    )


def test_cancel_missing_appointment_404(client: TestClient):
    headers = register(client, "joe@test.com")
    assert client.delete("/appointments/999", headers=headers).status_code == 404


def _make_barber(client: TestClient, owner_headers: dict, email: str, open_day) -> dict:
    """Register a plain user, make them a barber, and open the given weekday."""
    from app.models import Weekday

    headers = register(client, email)
    user_id = client.get("/auth/me", headers=headers).json()["id"]
    made = client.post(
        "/barbers", json={"user_id": user_id}, headers=owner_headers
    ).json()
    client.put(
        f"/barbers/{made['id']}/working-hours",
        json=[
            {
                "weekday": Weekday.of(open_day).value,
                "start_time": "09:00",
                "end_time": "17:00",
            }
        ],
        headers=owner_headers,
    )
    services = client.get(f"/barbers/{made['id']}/services").json()
    return {"id": made["id"], "headers": headers, "service_id": services[0]["id"]}


def test_barber_can_cancel_a_booking_on_their_chair(
    client: TestClient, owner_headers: dict, barber: dict
):
    bob = _make_barber(client, owner_headers, "bob@test.com", barber["open_day"])
    joe = register(client, "joe@test.com")
    appt = first(
        book(
            client,
            joe,
            bob["id"],
            slot(barber["open_day"]),
            service_id=bob["service_id"],
        )
    )
    # Bob owns the chair but is not an admin, yet he may cancel its bookings.
    assert (
        client.delete(f"/appointments/{appt['id']}", headers=bob["headers"]).status_code
        == 204
    )


def test_staff_cancel_emails_the_customer(
    client: TestClient, owner_headers: dict, barber: dict, monkeypatch
):
    sent: list[tuple] = []
    monkeypatch.setattr(
        "app.routers.appointments.send_email",
        lambda to, subject, body: sent.append((to, subject)),
    )
    joe = register(client, "joe@test.com")
    appt = first(book(client, joe, 1, slot(barber["open_day"])))
    client.delete(f"/appointments/{appt['id']}", headers=owner_headers)
    assert sent and sent[0][0] == "joe@test.com"


def test_customer_self_cancel_sends_no_email(
    client: TestClient, barber: dict, monkeypatch
):
    sent: list = []
    monkeypatch.setattr(
        "app.routers.appointments.send_email", lambda *a, **k: sent.append(a)
    )
    joe = register(client, "joe@test.com")
    appt = first(book(client, joe, 1, slot(barber["open_day"])))
    assert client.delete(f"/appointments/{appt['id']}", headers=joe).status_code == 204
    assert sent == []


def test_cancel_walk_in_sends_no_email(
    client: TestClient, owner_headers: dict, barber: dict, monkeypatch
):
    sent: list = []
    monkeypatch.setattr(
        "app.routers.appointments.send_email", lambda *a, **k: sent.append(a)
    )
    appt = first(
        book_manual(
            client, owner_headers, slot(barber["open_day"]), customer_name="Tom"
        )
    )
    assert (
        client.delete(f"/appointments/{appt['id']}", headers=owner_headers).status_code
        == 204
    )
    assert sent == []


# --- booking on someone's behalf ---------------------------------------


def test_barber_books_a_walk_in_by_name(
    client: TestClient, owner_headers: dict, barber: dict
):
    resp = book_manual(
        client, owner_headers, slot(barber["open_day"]), customer_name="Old Tom"
    )
    assert resp.status_code == 201
    assert first(resp)["guest_name"] == "Old Tom"
    assert first(resp)["customer_id"] is None

    booked = client.get("/barbers/1/appointments", headers=owner_headers).json()
    assert booked[0]["customer_name"] == "Old Tom"
    assert booked[0]["customer_email"] == ""
    assert booked[0]["customer_phone"] == ""


def test_barber_books_an_existing_account_by_email(
    client: TestClient, owner_headers: dict, barber: dict
):
    eve_headers = register(client, "eve@test.com")
    client.patch(
        "/auth/me",
        json={"full_name": "Eve", "phone": "913000000"},
        headers=eve_headers,
    )
    resp = book_manual(
        client, owner_headers, slot(barber["open_day"]), customer_email="eve@test.com"
    )
    assert resp.status_code == 201
    assert first(resp)["customer_id"] is not None
    assert first(resp)["guest_name"] is None

    booked = client.get("/barbers/1/appointments", headers=owner_headers).json()
    assert booked[0]["customer_email"] == "eve@test.com"
    assert booked[0]["customer_phone"] == "913000000"

    eve = register(client, "eve@test.com")  # same account; log back in
    assert len(client.get("/appointments", headers=eve).json()) == 1


def test_manual_booking_with_unknown_email_404(
    client: TestClient, owner_headers: dict, barber: dict
):
    resp = book_manual(
        client, owner_headers, slot(barber["open_day"]), customer_email="ghost@x.com"
    )
    assert resp.status_code == 404


def test_manual_booking_needs_a_name_or_email(
    client: TestClient, owner_headers: dict, barber: dict
):
    assert (
        book_manual(client, owner_headers, slot(barber["open_day"])).status_code == 422
    )


def test_manual_booking_respects_taken_slots(
    client: TestClient, owner_headers: dict, barber: dict
):
    book_manual(client, owner_headers, slot(barber["open_day"]), customer_name="Tom")
    twice = book_manual(
        client, owner_headers, slot(barber["open_day"]), customer_name="Jerry"
    )
    assert twice.status_code == 409


def test_a_customer_cannot_book_for_someone_elses_chair(
    client: TestClient, barber: dict
):
    joe = register(client, "joe@test.com")  # a plain customer, not a barber
    resp = book_manual(client, joe, slot(barber["open_day"]), customer_name="Tom")
    assert resp.status_code == 403


# --- theme settings -----------------------------------------------------


def test_theme_defaults_to_the_configured_colours(client: TestClient):
    body = client.get("/settings/theme").json()
    assert body["brand"] == "#9e7b53"
    assert body["background"] == "#f6f1e9"
    assert body["headline"] == "A sua cadeira está à espera"


def test_admin_can_change_the_theme(client: TestClient, owner_headers: dict):
    payload = {"brand": "#2563eb", "background": "#0f172a", "headline": "Bem-vindo"}
    resp = client.put("/settings/theme", json=payload, headers=owner_headers)
    assert resp.status_code == 200
    assert resp.json()["brand"] == "#2563eb"
    assert resp.json()["background"] == "#0f172a"
    assert resp.json()["headline"] == "Bem-vindo"
    saved = client.get("/settings/theme").json()
    assert saved["brand"] == "#2563eb"
    assert saved["background"] == "#0f172a"
    assert saved["headline"] == "Bem-vindo"


def test_customers_cannot_change_the_theme(client: TestClient):
    joe = register(client, "joe@test.com")
    payload = {"brand": "#2563eb", "background": "#0f172a", "headline": "Olá"}
    resp = client.put("/settings/theme", json=payload, headers=joe)
    assert resp.status_code == 403


def test_invalid_colours_are_rejected(client: TestClient, owner_headers: dict):
    resp = client.put(
        "/settings/theme",
        json={"brand": "blue", "background": "#f6f1e9", "headline": "Olá"},
        headers=owner_headers,
    )
    assert resp.status_code == 422


def test_empty_headline_is_allowed(client: TestClient, owner_headers: dict):
    resp = client.put(
        "/settings/theme",
        json={"brand": "#2563eb", "background": "#0f172a", "headline": ""},
        headers=owner_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["headline"] == ""


# --- logo ---------------------------------------------------------------

# A minimal valid 1x1 PNG.
_PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
    "0000000a49444154789c6360000002000154a24f5f0000000049454e44ae426082"
)


def test_logo_is_served(client: TestClient):
    resp = client.get("/settings/logo")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("image/")
    assert resp.content  # bytes present (the seeded default)


def test_admin_can_replace_the_logo(client: TestClient, owner_headers: dict):
    before = client.get("/settings/theme").json()["logo_version"]
    resp = client.put(
        "/settings/logo",
        files={"file": ("logo.png", _PNG, "image/png")},
        headers=owner_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["logo_version"] != before  # cache-buster advanced
    served = client.get("/settings/logo")
    assert served.content == _PNG
    assert served.headers["content-type"] == "image/png"


def test_customers_cannot_replace_the_logo(client: TestClient):
    joe = register(client, "joe@test.com")
    resp = client.put(
        "/settings/logo",
        files={"file": ("logo.png", _PNG, "image/png")},
        headers=joe,
    )
    assert resp.status_code == 403


def test_non_image_logo_is_rejected(client: TestClient, owner_headers: dict):
    resp = client.put(
        "/settings/logo",
        files={"file": ("evil.txt", b"not an image", "text/plain")},
        headers=owner_headers,
    )
    assert resp.status_code == 415


# --- services -----------------------------------------------------------


def test_services_are_seeded_and_listed(client: TestClient, barber: dict):
    services = client.get("/barbers/1/services").json()
    names = {s["name"]: s["duration_minutes"] for s in services}
    assert names == {"Corte": 30, "Barba": 15}


def test_owner_can_add_a_service(client: TestClient, owner_headers: dict, barber: dict):
    resp = client.post(
        "/barbers/1/services",
        json={"name": "Corte + Barba", "duration_minutes": 45},
        headers=owner_headers,
    )
    assert resp.status_code == 201
    assert resp.json()["duration_minutes"] == 45
    assert len(client.get("/barbers/1/services").json()) == 3


def test_customer_cannot_add_a_service(client: TestClient, barber: dict):
    joe = register(client, "joe@test.com")
    resp = client.post(
        "/barbers/1/services", json={"name": "X", "duration_minutes": 30}, headers=joe
    )
    assert resp.status_code == 403


def test_deactivating_a_service_hides_it_from_customers(
    client: TestClient, owner_headers: dict, barber: dict
):
    client.patch(f"/services/{BEARD}", json={"is_active": False}, headers=owner_headers)
    active = [s["id"] for s in client.get("/barbers/1/services").json()]
    assert BEARD not in active and HAIRCUT in active


def test_cannot_delete_a_service_in_use(
    client: TestClient, owner_headers: dict, barber: dict
):
    headers = register(client, "joe@test.com")
    book(client, headers, 1, slot(barber["open_day"]), service_id=HAIRCUT)
    resp = client.delete(f"/services/{HAIRCUT}", headers=owner_headers)
    assert resp.status_code == 409


def test_can_delete_an_unused_service(
    client: TestClient, owner_headers: dict, barber: dict
):
    assert client.delete(f"/services/{BEARD}", headers=owner_headers).status_code == 204


def test_bulk_replace_services(client: TestClient, owner_headers: dict, barber: dict):
    """PUT replaces the full menu: updates existing, creates new, removes absent."""
    resp = client.put(
        "/barbers/1/services",
        json=[
            {
                "id": HAIRCUT,
                "name": "Corte rápido",
                "duration_minutes": 20,
                "is_active": True,
            },
            {"name": "Coloração", "duration_minutes": 60, "is_active": True},
        ],
        headers=owner_headers,
    )
    assert resp.status_code == 200
    services = resp.json()
    names = {s["name"]: s["duration_minutes"] for s in services if s["is_active"]}
    assert "Corte rápido" in names and names["Corte rápido"] == 20
    assert "Coloração" in names
    # Beard was removed from the list — should be deleted (unused) or deactivated.
    active_ids = {s["id"] for s in services if s["is_active"]}
    assert BEARD not in active_ids


def test_cannot_book_another_barbers_service(
    client: TestClient, owner_headers: dict, barber: dict
):
    bob = _make_barber(client, owner_headers, "bob@test.com", barber["open_day"])
    joe = register(client, "joe@test.com")
    # HAIRCUT (id 1) belongs to barber 1, not to bob's chair.
    resp = book(client, joe, bob["id"], slot(barber["open_day"]), service_id=HAIRCUT)
    assert resp.status_code == 400


# --- switching an appointment's service --------------------------------


def test_staff_can_switch_service_to_a_shorter_one(
    client: TestClient, owner_headers: dict, barber: dict
):
    headers = register(client, "joe@test.com")
    appt = first(book(client, headers, 1, slot(barber["open_day"]), service_id=HAIRCUT))
    resp = client.patch(
        f"/appointments/{appt['id']}", json={"service_id": BEARD}, headers=owner_headers
    )
    assert resp.status_code == 200
    assert resp.json()["duration_minutes"] == 15


def test_switch_that_would_overlap_is_refused(
    client: TestClient, owner_headers: dict, barber: dict
):
    long_service = client.post(
        "/barbers/1/services",
        json={"name": "Longo", "duration_minutes": 60},
        headers=owner_headers,
    ).json()["id"]
    joe = register(client, "joe@test.com")
    first_appt = first(
        book(client, joe, 1, slot(barber["open_day"], "T09:00:00"), service_id=BEARD)
    )
    book(client, joe, 1, slot(barber["open_day"], "T09:15:00"), service_id=HAIRCUT)
    # Growing 09:00 to 60 minutes would run into the 09:15 booking.
    resp = client.patch(
        f"/appointments/{first_appt['id']}",
        json={"service_id": long_service},
        headers=owner_headers,
    )
    assert resp.status_code == 409


def test_customer_cannot_switch_service(client: TestClient, barber: dict):
    joe = register(client, "joe@test.com")
    appt = first(book(client, joe, 1, slot(barber["open_day"]), service_id=HAIRCUT))
    resp = client.patch(
        f"/appointments/{appt['id']}", json={"service_id": BEARD}, headers=joe
    )
    assert resp.status_code == 403


# --- weekly recurrence --------------------------------------------------


def _allow_recurring(client: TestClient, owner_headers: dict) -> None:
    client.patch("/barbers/1", json={"allow_recurring": True}, headers=owner_headers)


def test_recurring_books_several_weeks(
    client: TestClient, owner_headers: dict, barber: dict
):
    _allow_recurring(client, owner_headers)
    headers = register(client, "joe@test.com")
    resp = book(client, headers, 1, slot(barber["open_day"]), repeat_weeks=3)
    assert resp.status_code == 201
    booked = resp.json()["booked"]
    assert len(booked) == 3
    assert resp.json()["skipped"] == []
    groups = {b["recurrence_group_id"] for b in booked}
    assert len(groups) == 1 and None not in groups


def test_recurring_is_refused_when_not_allowed(client: TestClient, barber: dict):
    headers = register(client, "joe@test.com")
    resp = book(client, headers, 1, slot(barber["open_day"]), repeat_weeks=2)
    assert resp.status_code == 403


def test_recurring_skips_busy_weeks(
    client: TestClient, owner_headers: dict, barber: dict
):
    _allow_recurring(client, owner_headers)
    # Fill the second week's slot with a walk-in first.
    week2 = barber["open_day"] + timedelta(weeks=1)
    book_manual(client, owner_headers, slot(week2), customer_name="Tom")

    headers = register(client, "joe@test.com")
    resp = book(client, headers, 1, slot(barber["open_day"]), repeat_weeks=2)
    assert resp.status_code == 201
    assert len(resp.json()["booked"]) == 1
    assert len(resp.json()["skipped"]) == 1


def test_recurring_over_the_cap_is_rejected(
    client: TestClient, owner_headers: dict, barber: dict
):
    client.patch(
        "/barbers/1",
        json={"allow_recurring": True, "max_recurring_weeks": 4},
        headers=owner_headers,
    )
    headers = register(client, "joe@test.com")
    resp = book(client, headers, 1, slot(barber["open_day"]), repeat_weeks=6)
    assert resp.status_code == 422


def test_cancel_series_removes_all(
    client: TestClient, owner_headers: dict, barber: dict
):
    _allow_recurring(client, owner_headers)
    headers = register(client, "joe@test.com")
    booked = book(client, headers, 1, slot(barber["open_day"]), repeat_weeks=3).json()[
        "booked"
    ]
    group = booked[0]["recurrence_group_id"]
    assert (
        client.delete(f"/appointments/series/{group}", headers=headers).status_code
        == 204
    )
    assert client.get("/appointments", headers=headers).json() == []


# --- perpetual recurrence -------------------------------------------------


def test_perpetual_booking_creates_a_series_and_materialises_the_anchor(
    client: TestClient, owner_headers: dict, barber: dict
):
    _allow_recurring(client, owner_headers)
    headers = register(client, "joe@test.com")
    resp = book(client, headers, 1, slot(barber["open_day"]), perpetual=True)
    assert resp.status_code == 201
    booked = resp.json()["booked"]
    assert len(booked) >= 1
    group = booked[0]["recurrence_group_id"]
    assert group is not None
    assert all(b["recurrence_group_id"] == group for b in booked)


def test_perpetual_booking_is_refused_when_not_allowed(
    client: TestClient, barber: dict
):
    headers = register(client, "joe@test.com")
    resp = book(client, headers, 1, slot(barber["open_day"]), perpetual=True)
    assert resp.status_code == 403


def test_perpetual_booking_refuses_a_taken_slot(
    client: TestClient, owner_headers: dict, barber: dict
):
    _allow_recurring(client, owner_headers)
    book_manual(client, owner_headers, slot(barber["open_day"]), customer_name="Tom")

    headers = register(client, "joe@test.com")
    resp = book(client, headers, 1, slot(barber["open_day"]), perpetual=True)
    assert resp.status_code == 409


def test_perpetual_series_appears_in_recurring_series_list(
    client: TestClient, owner_headers: dict, barber: dict
):
    _allow_recurring(client, owner_headers)
    headers = register(client, "joe@test.com")
    book(client, headers, 1, slot(barber["open_day"]), perpetual=True)

    mine = client.get("/appointments/recurring-series", headers=headers).json()
    assert len(mine) == 1
    assert mine[0]["barber_name"]
    assert mine[0]["service_name"] == "Corte"

    # The barber/owner sees it too, since it's their chair.
    theirs = client.get("/appointments/recurring-series", headers=owner_headers).json()
    assert len(theirs) == 1
    assert theirs[0]["id"] == mine[0]["id"]


def test_a_customer_only_sees_their_own_recurring_series(
    client: TestClient, owner_headers: dict, barber: dict
):
    _allow_recurring(client, owner_headers)
    joe = register(client, "joe@test.com")
    book(client, joe, 1, slot(barber["open_day"]), perpetual=True)

    ana = register(client, "ana@test.com")
    assert client.get("/appointments/recurring-series", headers=ana).json() == []


def test_cancelling_a_perpetual_series_removes_the_pattern_and_bookings(
    client: TestClient, owner_headers: dict, barber: dict
):
    _allow_recurring(client, owner_headers)
    headers = register(client, "joe@test.com")
    booked = book(client, headers, 1, slot(barber["open_day"]), perpetual=True).json()[
        "booked"
    ]
    group = booked[0]["recurrence_group_id"]

    assert (
        client.delete(f"/appointments/series/{group}", headers=headers).status_code
        == 204
    )
    assert client.get("/appointments", headers=headers).json() == []
    assert client.get("/appointments/recurring-series", headers=headers).json() == []

    # Reading the schedule again must not resurrect the cancelled series.
    client.get("/barbers/1/appointments", headers=owner_headers)
    assert client.get("/appointments", headers=headers).json() == []


def test_bounded_series_appears_in_recurring_series_list(
    client: TestClient, owner_headers: dict, barber: dict
):
    _allow_recurring(client, owner_headers)
    headers = register(client, "joe@test.com")
    book(client, headers, 1, slot(barber["open_day"]), repeat_weeks=3)

    mine = client.get("/appointments/recurring-series", headers=headers).json()
    assert len(mine) == 1
    entry = mine[0]
    assert entry["kind"] == "bounded"
    assert entry["ends_at"] == str(barber["open_day"] + timedelta(weeks=2))


def test_recurring_series_exposes_customer_contact_details_for_staff(
    client: TestClient, owner_headers: dict, barber: dict
):
    """The barber/admin's "Horários Fixos" needs a way to reach the customer;
    the customer's own copy of the same list doesn't need to show it back to
    them, but the API always includes it — the frontend decides what to
    render per role, since a customer only ever sees their own series here
    anyway (nothing about another customer ever leaks through this list)."""
    _allow_recurring(client, owner_headers)
    headers = register(client, "joe@test.com")
    book(client, headers, 1, slot(barber["open_day"]), perpetual=True)

    staff_view = client.get(
        "/appointments/recurring-series", headers=owner_headers
    ).json()
    assert len(staff_view) == 1
    assert staff_view[0]["customer_email"] == "joe@test.com"

    # A walk-in with no account has neither — same as elsewhere in the app.
    book_manual(
        client, owner_headers, slot(barber["closed_day"]), customer_name="Tom"
    )
    resp = book_manual(
        client,
        owner_headers,
        slot(barber["open_day"] + timedelta(weeks=6)),
        service_id=BEARD,
        customer_name="Walk-in Tom",
        perpetual=True,
    )
    assert resp.status_code == 201
    staff_view = client.get(
        "/appointments/recurring-series", headers=owner_headers
    ).json()
    walk_in_entry = next(e for e in staff_view if e["customer_name"] == "Walk-in Tom")
    assert walk_in_entry["customer_email"] == ""
    assert walk_in_entry["customer_phone"] == ""


def test_a_single_booking_is_not_a_recurring_series(
    client: TestClient, owner_headers: dict, barber: dict
):
    headers = register(client, "joe@test.com")
    book(client, headers, 1, slot(barber["open_day"]))
    assert client.get("/appointments/recurring-series", headers=headers).json() == []


def test_recurring_series_list_mixes_bounded_and_perpetual(
    client: TestClient, owner_headers: dict, barber: dict
):
    _allow_recurring(client, owner_headers)
    headers = register(client, "joe@test.com")
    book(client, headers, 1, slot(barber["open_day"], "T09:00:00"), repeat_weeks=3)
    book(
        client,
        headers,
        1,
        slot(barber["open_day"], "T10:00:00"),
        service_id=BEARD,
        perpetual=True,
    )

    mine = client.get("/appointments/recurring-series", headers=headers).json()
    assert len(mine) == 2
    kinds = {entry["kind"] for entry in mine}
    assert kinds == {"bounded", "perpetual"}
    perpetual_entry = next(e for e in mine if e["kind"] == "perpetual")
    assert perpetual_entry["ends_at"] is None
    bounded_entry = next(e for e in mine if e["kind"] == "bounded")
    assert bounded_entry["ends_at"] is not None


def test_cannot_book_a_second_bounded_series_at_the_same_weekday_and_time(
    client: TestClient, owner_headers: dict, barber: dict
):
    _allow_recurring(client, owner_headers)
    headers = register(client, "joe@test.com")
    book(client, headers, 1, slot(barber["open_day"], "T09:00:00"), repeat_weeks=2)

    # Same weekday+hour every week, just a different (later) starting date
    # and a different service — still landing on the same standing slot.
    resp = book(
        client,
        headers,
        1,
        slot(barber["open_day"] + timedelta(weeks=4), "T09:00:00"),
        service_id=BEARD,
        repeat_weeks=2,
    )
    assert resp.status_code == 409
    # The frontend distinguishes this from a plain slot clash by this code,
    # not by matching on the human-readable message text.
    assert resp.json()["detail"]["code"] == "standing_slot_conflict"


def test_cannot_book_perpetual_over_an_existing_bounded_series(
    client: TestClient, owner_headers: dict, barber: dict
):
    _allow_recurring(client, owner_headers)
    headers = register(client, "joe@test.com")
    book(client, headers, 1, slot(barber["open_day"], "T09:00:00"), repeat_weeks=3)

    resp = book(
        client,
        headers,
        1,
        slot(barber["open_day"] + timedelta(weeks=6), "T09:00:00"),
        perpetual=True,
    )
    assert resp.status_code == 409


def test_cannot_book_bounded_over_an_existing_perpetual_series(
    client: TestClient, owner_headers: dict, barber: dict
):
    _allow_recurring(client, owner_headers)
    headers = register(client, "joe@test.com")
    book(client, headers, 1, slot(barber["open_day"], "T09:00:00"), perpetual=True)

    resp = book(
        client,
        headers,
        1,
        slot(barber["open_day"] + timedelta(weeks=6), "T09:00:00"),
        repeat_weeks=2,
    )
    assert resp.status_code == 409


def test_different_time_recurring_series_is_still_allowed(
    client: TestClient, owner_headers: dict, barber: dict
):
    _allow_recurring(client, owner_headers)
    headers = register(client, "joe@test.com")
    book(client, headers, 1, slot(barber["open_day"], "T09:00:00"), repeat_weeks=2)

    resp = book(
        client,
        headers,
        1,
        slot(barber["open_day"], "T10:00:00"),
        service_id=BEARD,
        repeat_weeks=2,
    )
    assert resp.status_code == 201


def test_a_single_booking_never_triggers_the_standing_slot_check(
    client: TestClient, owner_headers: dict, barber: dict
):
    _allow_recurring(client, owner_headers)
    headers = register(client, "joe@test.com")
    book(client, headers, 1, slot(barber["open_day"], "T09:00:00"), repeat_weeks=3)

    # A plain, one-off booking at the same weekday+time isn't a new standing
    # slot (repeat_weeks defaults to 1), so it isn't blocked by this guard —
    # it's still refused normally, though, since that exact slot is taken.
    resp = book(
        client,
        headers,
        1,
        slot(barber["open_day"] + timedelta(weeks=1), "T09:00:00"),
    )
    assert resp.status_code == 409  # taken by the series itself, not the guard


def test_walk_ins_are_exempt_from_the_standing_slot_check(
    client: TestClient, owner_headers: dict, barber: dict
):
    """Guests aren't tracked well enough for the guard to apply reliably."""
    book_manual(
        client,
        owner_headers,
        slot(barber["open_day"], "T09:00:00"),
        customer_name="Tom",
        repeat_weeks=2,
    )
    resp = book_manual(
        client,
        owner_headers,
        slot(barber["open_day"] + timedelta(weeks=4), "T09:00:00"),
        service_id=BEARD,
        customer_name="Tom",
        repeat_weeks=2,
    )
    assert resp.status_code == 201


def _freeze_shop_now(monkeypatch, when):
    """Pin "now" everywhere the app reads it.

    Every module that needs the current time does ``from app.availability
    import shop_now``, which copies the function *reference* at import time —
    patching ``app.availability.shop_now`` alone would not affect those
    already-bound copies. So each module that materialises or filters
    appointments by date is patched individually here.
    """
    import app.availability as availability
    import app.recurrence as recurrence
    import app.routers.appointments as appointments
    import app.routers.barbers as barbers

    for module in (availability, recurrence, appointments, barbers):
        monkeypatch.setattr(module, "shop_now", lambda when=when: when)


def test_perpetual_series_rolling_window_slides_forward_week_by_week(
    client: TestClient, owner_headers: dict, barber: dict, monkeypatch
):
    """The mechanism behind "Horários Fixos": a perpetual series only ever
    materialises real Appointment rows a rolling window ahead, refreshed
    lazily on every read — there is no background job.

    This walks through exactly the scenario a barber/customer experiences:
    book a perpetual Monday slot, see the next few Mondays appear, then let
    the anchor Monday come and go and confirm that, the very next time
    anyone reads the schedule (the following day — no need to wait for the
    week to turn over), the one that's now in the past drops off the
    "upcoming" list while enough new far-future Mondays have already been
    materialised to keep 4 full weeks of standing appointments visible.
    """
    _allow_recurring(client, owner_headers)
    headers = register(client, "joe@test.com")
    anchor = barber["open_day"]  # the only weekday this barber works

    resp = book(client, headers, 1, slot(anchor), perpetual=True)
    assert resp.status_code == 201

    # Right after booking, "now" is today, so the window (today + 4 weeks)
    # only reaches 2 weeks past the anchor (itself already 2 weeks out) —
    # 3 Mondays visible: the anchor, +1wk and +2wk.
    upcoming = client.get("/appointments", headers=headers).json()
    dates = {a["start_at"] for a in upcoming}
    assert dates == {
        slot(anchor),
        slot(anchor + timedelta(weeks=1)),
        slot(anchor + timedelta(weeks=2)),
    }

    # The anchor Monday happens; the very next day (Tuesday) someone opens
    # the schedule again — no week needs to "turn over" for this to kick in.
    the_next_day = datetime.combine(anchor + timedelta(days=1), datetime.min.time())
    _freeze_shop_now(monkeypatch, the_next_day)

    upcoming = client.get("/appointments", headers=headers).json()
    dates = {a["start_at"] for a in upcoming}

    # The anchor Monday is in the past now — filtered out of "upcoming",
    # even though its Appointment row still exists (kept for history, see
    # below). The window immediately tops back up to a full 4 Mondays —
    # not just the next one, but as many as it takes to reach the 4-week
    # mark from "now" — all on this single lazy read, nothing scheduled.
    assert dates == {
        slot(anchor + timedelta(weeks=1)),
        slot(anchor + timedelta(weeks=2)),
        slot(anchor + timedelta(weeks=3)),
        slot(anchor + timedelta(weeks=4)),
    }

    with Session(engine) as session:
        past_appt = session.exec(
            select(Appointment).where(
                Appointment.start_at == datetime.fromisoformat(slot(anchor))
            )
        ).first()
        assert past_appt is not None  # never deleted — just no longer "upcoming"
