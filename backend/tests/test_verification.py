"""Email verification, input validation and readiness checks."""

from fastapi.testclient import TestClient

from app.security import create_verification_token
from tests.conftest import auth
from tests.test_api import book, slot


def register_unverified(client: TestClient, email: str) -> dict[str, str]:
    """Register a customer but skip the email-verification step."""
    client.post(
        "/auth/register",
        json={"email": email, "full_name": "Joe", "password": "secret123"},
    )
    return auth(client, email, "secret123")


def test_new_users_start_unverified(client: TestClient):
    headers = register_unverified(client, "joe@test.com")
    assert client.get("/auth/me", headers=headers).json()["is_verified"] is False


def test_unverified_user_cannot_book(client: TestClient, barber: dict):
    headers = register_unverified(client, "joe@test.com")
    assert book(client, headers, 1, slot(barber["open_day"])).status_code == 403


def test_verifying_lets_the_user_book(client: TestClient, barber: dict):
    headers = register_unverified(client, "joe@test.com")
    user_id = client.get("/auth/me", headers=headers).json()["id"]
    token = create_verification_token(user_id)
    assert client.get("/auth/verify", params={"token": token}).status_code == 200
    assert book(client, headers, 1, slot(barber["open_day"])).status_code == 201


def test_verify_rejects_a_bad_token(client: TestClient):
    assert client.get("/auth/verify", params={"token": "garbage"}).status_code == 400


def test_resend_is_rejected_once_verified(client: TestClient):
    headers = register_unverified(client, "joe@test.com")
    user_id = client.get("/auth/me", headers=headers).json()["id"]
    client.get("/auth/verify", params={"token": create_verification_token(user_id)})
    assert client.post("/auth/resend-verification", headers=headers).status_code == 400


def test_owner_is_verified_on_seed(client: TestClient, owner_headers: dict):
    assert client.get("/auth/me", headers=owner_headers).json()["is_verified"] is True


def test_malformed_email_is_rejected(client: TestClient):
    resp = client.post(
        "/auth/register",
        json={"email": "not-an-email", "full_name": "Joe", "password": "secret123"},
    )
    assert resp.status_code == 422


def test_readiness_probe_reports_ready(client: TestClient):
    assert client.get("/health/ready").json()["status"] == "ready"
