"""Tests for authentication and registration flows."""
from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from wallettaser.api import app
from wallettaser.database import SessionLocal
from wallettaser.models import Tenant, User


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app)


def test_register_requires_verification(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WALLETTASER_DEV_VERIFICATION_HINT", "1")
    email = f"user_{uuid.uuid4().hex[:6]}@example.com"

    response = client.post(
        "/auth/register",
        json={"email": email, "password": "Sup3rStrong!"},
    )
    assert response.status_code == 201
    payload = response.json()
    assert payload["status"] == "pending_verification"
    code = payload.get("verification_hint")
    assert code

    # login should be blocked until verification succeeds
    login_resp = client.post(
        "/auth/token",
        json={"email": email, "password": "Sup3rStrong!"},
    )
    assert login_resp.status_code == 403

    verify_resp = client.post(
        "/auth/verify",
        json={"email": email, "code": code},
    )
    assert verify_resp.status_code == 200
    token_payload = verify_resp.json()
    assert "access_token" in token_payload

    # login now works
    login_ok = client.post(
        "/auth/token",
        json={"email": email, "password": "Sup3rStrong!"},
    )
    assert login_ok.status_code == 200

    session = SessionLocal()
    try:
        db_user = session.query(User).filter(User.username == email).first()
        assert db_user is not None
        assert db_user.is_verified
        db_tenant = session.query(Tenant).filter(Tenant.id == db_user.tenant_id).first()
        assert db_tenant is not None
    finally:
        session.close()


def test_register_rejects_duplicate_email(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WALLETTASER_DEV_VERIFICATION_HINT", "1")
    email = f"dup_{uuid.uuid4().hex[:6]}@example.com"

    first = client.post(
        "/auth/register",
        json={"email": email, "password": "Password!1"},
    )
    assert first.status_code == 201

    duplicate = client.post(
        "/auth/register",
        json={"email": email, "password": "Different1!"},
    )
    assert duplicate.status_code == 409
