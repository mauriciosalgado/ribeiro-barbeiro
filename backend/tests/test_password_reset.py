"""Password-reset flow tests."""

from fastapi.testclient import TestClient

from app.security import create_reset_token
from tests.conftest import auth, register


def test_forgot_password_always_returns_200(client: TestClient):
    """Never leak whether an email exists."""
    resp = client.post("/auth/forgot-password", json={"email": "nobody@test.com"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "sent"


def test_reset_password_with_valid_token(client: TestClient):
    """A valid reset token lets the user set a new password."""
    register(client, "joe@test.com", "oldpass123")
    headers = auth(client, "joe@test.com", "oldpass123")
    me = client.get("/auth/me", headers=headers).json()

    token = create_reset_token(me["id"])
    resp = client.post(
        "/auth/reset-password", json={"token": token, "new_password": "newpass123"}
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "password_updated"

    # Old password no longer works
    old_login = client.post(
        "/auth/token", data={"username": "joe@test.com", "password": "oldpass123"}
    )
    assert old_login.status_code == 401

    # New password works
    new_login = client.post(
        "/auth/token", data={"username": "joe@test.com", "password": "newpass123"}
    )
    assert new_login.status_code == 200
    assert "access_token" in new_login.json()


def test_reset_password_rejects_bad_token(client: TestClient):
    resp = client.post(
        "/auth/reset-password",
        json={"token": "garbage", "new_password": "longenough"},
    )
    assert resp.status_code == 400


def test_change_password(client: TestClient):
    """A logged-in user can change their own password."""
    register(client, "alice@test.com", "original123")
    headers = auth(client, "alice@test.com", "original123")

    resp = client.put(
        "/auth/me/password",
        json={"current_password": "original123", "new_password": "updated123"},
        headers=headers,
    )
    assert resp.status_code == 200

    # Old password rejected
    assert (
        client.post(
            "/auth/token",
            data={"username": "alice@test.com", "password": "original123"},
        ).status_code
        == 401
    )

    # New password works
    assert (
        client.post(
            "/auth/token", data={"username": "alice@test.com", "password": "updated123"}
        ).status_code
        == 200
    )


def test_change_password_wrong_current(client: TestClient):
    """Must provide the correct current password."""
    register(client, "bob@test.com", "bobpass123")
    headers = auth(client, "bob@test.com", "bobpass123")

    resp = client.put(
        "/auth/me/password",
        json={"current_password": "wrongpass", "new_password": "newone123"},
        headers=headers,
    )
    assert resp.status_code == 403
