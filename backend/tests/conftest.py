"""Test fixtures: an isolated SQLite DB and a FastAPI test client."""

import os
import tempfile

# Configure the app for tests *before* importing it (settings read the env).
os.environ.update(
    {
        "SHOP_NAME": "Test Shop",
        "SHOP_TIMEZONE": "UTC",
        "DATABASE_URL": f"sqlite:///{tempfile.gettempdir()}/barber_test.db",
        "JWT_SECRET": "test-secret-key-that-is-long-enough-32b",
        "OWNER_EMAIL": "owner@test.com",
        "OWNER_NAME": "Owner",
        "OWNER_PASSWORD": "ownerpass",
        "CORS_ORIGINS": "*",
        "PUBLIC_BASE_URL": "http://test",
        "SMTP_HOST": "",
        "SMTP_PORT": "1025",
        "SMTP_FROM": "test@shop.local",
    }
)

from datetime import date, timedelta  # noqa: E402

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlmodel import SQLModel  # noqa: E402

from app.database import engine  # noqa: E402
from app.main import app  # noqa: E402
from app.limiter import limiter  # noqa: E402
from app.models import Weekday  # noqa: E402
from app.security import create_verification_token  # noqa: E402
from app.seed import seed_owner  # noqa: E402

# Disable rate limiting during tests so fixtures can call /auth/token freely.
limiter.enabled = False

OWNER = {"username": "owner@test.com", "password": "ownerpass"}


@pytest.fixture()
def client():
    """A test client backed by a fresh, seeded database."""
    SQLModel.metadata.drop_all(engine)
    SQLModel.metadata.create_all(engine)
    seed_owner()
    with TestClient(app) as c:
        yield c


def auth(client: TestClient, username: str, password: str) -> dict[str, str]:
    token = client.post(
        "/auth/token", data={"username": username, "password": password}
    )
    return {"Authorization": f"Bearer {token.json()['access_token']}"}


def register(
    client: TestClient, email: str, password: str = "secret123"
) -> dict[str, str]:
    """Register a customer and verify their email, returning auth headers."""
    client.post(
        "/auth/register",
        json={"email": email, "full_name": "Customer", "password": password},
    )
    headers = auth(client, email, password)
    user_id = client.get("/auth/me", headers=headers).json()["id"]
    client.get("/auth/verify", params={"token": create_verification_token(user_id)})
    return headers


@pytest.fixture()
def owner_headers(client: TestClient) -> dict[str, str]:
    return auth(client, OWNER["username"], OWNER["password"])


@pytest.fixture()
def barber(client: TestClient, owner_headers: dict[str, str]) -> dict[str, object]:
    """Make the owner a barber working 09:00-17:00 (lunch 12-13) on one weekday."""
    owner_id = client.get("/auth/me", headers=owner_headers).json()["id"]
    client.post("/barbers", json={"user_id": owner_id}, headers=owner_headers)

    open_day = date.today() + timedelta(days=14)  # future, same weekday as today
    client.put(
        "/barbers/1/working-hours",
        json=[
            {
                "weekday": Weekday.of(open_day).value,
                "start_time": "09:00",
                "end_time": "17:00",
                "break_start": "12:00",
                "break_end": "13:00",
            }
        ],
        headers=owner_headers,
    )
    return {
        "id": 1,
        "open_day": open_day,
        "closed_day": open_day + timedelta(days=1),  # a weekday with no hours
        "past_day": open_day - timedelta(days=21),  # same weekday, in the past
    }
