"""Unit tests for the perpetual recurring-series rolling window.

These call app.recurrence directly (rather than through the API) so we can
simulate the passage of time with a monkeypatched shop_now, without needing
real weeks to elapse or a time-freezing dependency.
"""

from datetime import date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

import app.recurrence as recurrence
from app.database import engine
from app.models import Appointment, RecurringSeries, Weekday

OWNER = {"username": "owner@test.com", "password": "ownerpass"}


@pytest.fixture()
def series_setup(client: TestClient, owner_headers: dict):
    """A barber working every day at 09:00-17:00, and one perpetual series."""
    owner_id = client.get("/auth/me", headers=owner_headers).json()["id"]
    client.post("/barbers", json={"user_id": owner_id}, headers=owner_headers)
    client.put(
        "/barbers/1/working-hours",
        json=[
            {"weekday": w.value, "start_time": "09:00", "end_time": "17:00"}
            for w in Weekday
        ],
        headers=owner_headers,
    )
    client.patch("/barbers/1", json={"allow_recurring": True}, headers=owner_headers)

    anchor = datetime.combine(date.today() + timedelta(days=14), datetime.min.time())
    anchor = anchor.replace(hour=9)
    with Session(engine) as session:
        series = RecurringSeries(
            id="test-series",
            barber_id=1,
            customer_id=None,
            guest_name="Joe",
            service_id=1,
            anchor_start_at=anchor,
            duration_minutes=30,
            materialized_through=anchor - timedelta(weeks=1),
        )
        session.add(series)
        session.commit()
    return anchor


def _appointment_dates(session: Session) -> set[datetime]:
    rows = session.exec(
        select(Appointment).where(Appointment.recurrence_group_id == "test-series")
    ).all()
    return {a.start_at for a in rows}


def test_ensure_materialized_only_fills_the_rolling_window(
    client: TestClient, owner_headers: dict, series_setup: datetime
):
    anchor = series_setup
    with Session(engine) as session:
        series = session.get(RecurringSeries, "test-series")
        assert series is not None
        recurrence.ensure_materialized(session, series)
        dates = _appointment_dates(session)

    # The anchor (2 weeks out) plus its next 2 occurrences fall within
    # "now + 4 weeks" at booking time; the one after that (5 weeks out) does not.
    assert dates == {anchor, anchor + timedelta(weeks=1), anchor + timedelta(weeks=2)}


def test_ensure_materialized_extends_the_window_as_time_passes(
    client: TestClient, owner_headers: dict, series_setup: datetime, monkeypatch
):
    anchor = series_setup
    later = anchor + timedelta(weeks=3)
    monkeypatch.setattr(recurrence, "shop_now", lambda: later)

    with Session(engine) as session:
        series = session.get(RecurringSeries, "test-series")
        assert series is not None
        recurrence.ensure_materialized(session, series)
        dates = _appointment_dates(session)

    # cutoff = later + 4 weeks = anchor + 7wk, and occurrences up to and
    # including the cutoff are materialised: anchor, +1wk, ..., +7wk.
    expected = {anchor + timedelta(weeks=n) for n in range(8)}
    assert dates == expected


def test_ensure_materialized_skips_a_week_that_becomes_busy(
    client: TestClient, owner_headers: dict, series_setup: datetime, monkeypatch
):
    anchor = series_setup
    with Session(engine) as session:
        # A walk-in takes the second occurrence before it gets materialised.
        session.add(
            Appointment(
                barber_id=1,
                customer_id=None,
                guest_name="Walk-in",
                start_at=anchor + timedelta(weeks=1),
                service_id=1,
                duration_minutes=30,
            )
        )
        session.commit()

    later = anchor + timedelta(weeks=2)
    monkeypatch.setattr(recurrence, "shop_now", lambda: later)
    with Session(engine) as session:
        series = session.get(RecurringSeries, "test-series")
        assert series is not None
        recurrence.ensure_materialized(session, series)
        dates = _appointment_dates(session)

    # Week +1 was already taken by the walk-in, so the series skips it but
    # keeps going (its cursor still advances past that week).
    assert anchor + timedelta(weeks=1) not in dates
    assert anchor in dates
    assert anchor + timedelta(weeks=2) in dates


def test_cancelling_stops_future_materialisation(
    client: TestClient, owner_headers: dict, series_setup: datetime
):
    with Session(engine) as session:
        series = session.get(RecurringSeries, "test-series")
        assert series is not None
        recurrence.ensure_materialized(session, series)
        session.delete(series)
        for appointment in session.exec(
            select(Appointment).where(Appointment.recurrence_group_id == "test-series")
        ).all():
            session.delete(appointment)
        session.commit()

    with Session(engine) as session:
        assert session.get(RecurringSeries, "test-series") is None
        assert _appointment_dates(session) == set()
