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


def test_register_creates_user_and_returns_token(client: TestClient) -> None:
    username = f"user_{uuid.uuid4().hex[:6]}"
    tenant = f"tenant_{uuid.uuid4().hex[:6]}"

    response = client.post(
        "/auth/register",
        json={"username": username, "password": "Sup3rStrong!", "tenant_name": tenant},
    )
    assert response.status_code == 201
    payload = response.json()
    assert "access_token" in payload

    # ensure the user exists and can sign in again
    login_resp = client.post(
        "/auth/token",
        json={"username": username, "password": "Sup3rStrong!"},
    )
    assert login_resp.status_code == 200

    session = SessionLocal()
    try:
        db_user = session.query(User).filter(User.username == username).first()
        assert db_user is not None
        db_tenant = session.query(Tenant).filter(Tenant.id == db_user.tenant_id).first()
        assert db_tenant is not None
    finally:
        session.close()


def test_register_rejects_duplicate_username(client: TestClient) -> None:
    username = f"dup_{uuid.uuid4().hex[:6]}"

    first = client.post(
        "/auth/register",
        json={"username": username, "password": "Password!1"},
    )
    assert first.status_code == 201

    duplicate = client.post(
        "/auth/register",
        json={"username": username, "password": "Different1!"},
    )
    assert duplicate.status_code == 409

