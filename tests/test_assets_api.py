"""Tests for report asset listing and retrieval endpoints."""
from __future__ import annotations

import json
import shutil
import uuid
from dataclasses import asdict
from pathlib import Path

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from wallettaser.api import app
from wallettaser.auth import issue_token
from wallettaser.database import SessionLocal
from wallettaser.models import Job, Tenant, User
from wallettaser.pipeline import DATA_ROOT_ENV, process_statement


def _make_statement(path: Path) -> None:
    data = [
        {"Datum": "02.02.2023", "Tip": "Uplata", "Opis": "Zarada", "Iznos": "75000"},
        {"Datum": "03.02.2023", "Tip": "Card", "Opis": "Lidl store", "Iznos": "-9000"},
        {"Datum": "05.02.2023", "Tip": "Card", "Opis": "Tidal renewal", "Iznos": "-1200"},
    ]
    frame = pd.DataFrame(data)
    frame.to_excel(path, index=False)


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app)


def test_assets_listing_and_fetch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, client: TestClient) -> None:
    data_root = tmp_path / "data"
    monkeypatch.setenv(DATA_ROOT_ENV, str(data_root))

    statement_path = tmp_path / "statement.xlsx"
    _make_statement(statement_path)

    report_dir_path: Path | None = None
    archive_path: Path | None = None
    uploads_dir: Path | None = None

    session = SessionLocal()
    try:
        tenant = session.query(Tenant).filter_by(name="default").first()
        assert tenant is not None

        job_id = uuid.uuid4().hex
        result = process_statement(
            tenant_id=tenant.id,
            job_id=job_id,
            statement_path=statement_path,
            fx_rate=118.0,
        )

        report_dir_path = Path(result["report_directory"])
        archive_path = Path(result["archive_path"])
        uploads_dir = data_root / str(tenant.id) / "uploads" / job_id

        job = Job(
            id=job_id,
            tenant_id=tenant.id,
            filename="statement.xlsx",
            status="completed",
            result_path=result["archive_path"],
            report_directory=result["report_directory"],
            fx_rate=118.0,
            summary=json.dumps(asdict(result["summary"])),
        )
        session.add(job)
        session.commit()
    finally:
        session.close()

    token_resp = client.post("/auth/token", json={"email": "demo@example.com", "password": "demo"})
    assert token_resp.status_code == 200
    token = token_resp.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    assets_resp = client.get(f"/statements/{job_id}/assets", headers=headers)
    assert assets_resp.status_code == 200
    assets = assets_resp.json()["assets"]
    assert assets
    assert any(asset["name"].endswith("totals.png") for asset in assets)

    tag_resp = client.post(
        "/vendors",
        json={"vendor": "LIDL", "classification": "NEEDS"},
        headers=headers,
    )
    assert tag_resp.status_code == 204

    vendor_list = client.get(f"/vendors?job_id={job_id}", headers=headers)
    assert vendor_list.status_code == 200
    vendor_payload = vendor_list.json()
    assert any(tag["vendor"] == "LIDL" for tag in vendor_payload["tags"])

    first_asset = assets[0]["name"]
    file_resp = client.get(f"/statements/{job_id}/asset", params={"name": first_asset}, headers=headers)
    assert file_resp.status_code == 200
    assert int(file_resp.headers.get("content-length", "0")) > 0

    bad_resp = client.get(
        f"/statements/{job_id}/asset",
        params={"name": "../secrets.txt"},
        headers=headers,
    )
    assert bad_resp.status_code == 400

    delete_resp = client.delete(f"/statements/{job_id}", headers=headers)
    assert delete_resp.status_code == 200

    clean_tag = client.delete("/vendors/LIDL", headers=headers)
    assert clean_tag.status_code == 200

    after_delete = client.get(f"/statements/{job_id}", headers=headers)
    assert after_delete.status_code == 404

    assert report_dir_path and not report_dir_path.exists()
    assert archive_path and not archive_path.exists()
    assert uploads_dir and not uploads_dir.exists()


def test_reanalyze_triggers_celery(
    tmp_path: Path,
    sample_statement: Path,
    monkeypatch: pytest.MonkeyPatch,
    client: TestClient,
) -> None:
    data_root = tmp_path / "data"
    monkeypatch.setenv(DATA_ROOT_ENV, str(data_root))

    session = SessionLocal()
    try:
        tenant = session.query(Tenant).filter_by(name="default").first()
        assert tenant is not None

        job_id = uuid.uuid4().hex
        result = process_statement(
            tenant_id=tenant.id,
            job_id=job_id,
            statement_path=sample_statement,
            fx_rate=118.0,
        )

        uploads_dir = data_root / str(tenant.id) / "uploads" / job_id
        uploads_dir.mkdir(parents=True, exist_ok=True)
        stored_path = uploads_dir / f"{job_id}{sample_statement.suffix}"
        shutil.copy2(sample_statement, stored_path)

        job = Job(
            id=job_id,
            tenant_id=tenant.id,
            filename="statement.xlsx",
            status="completed",
            result_path=result["archive_path"],
            report_directory=result["report_directory"],
            fx_rate=118.0,
            summary=json.dumps(asdict(result["summary"])),
        )
        session.add(job)
        session.commit()
    finally:
        session.close()

    token_resp = client.post("/auth/token", json={"email": "demo@example.com", "password": "demo"})
    assert token_resp.status_code == 200
    token = token_resp.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    captured: dict[str, tuple[str, int, str, float | None]] = {}

    def fake_delay(job_id_arg: str, tenant_arg: int, statement_arg: str, fx_arg: float | None) -> None:
        captured["call"] = (job_id_arg, tenant_arg, statement_arg, fx_arg)

    monkeypatch.setattr("wallettaser.api.process_statement_task.delay", fake_delay)

    reanalyze_resp = client.post(f"/statements/{job_id}/reanalyze", headers=headers)
    assert reanalyze_resp.status_code == 202
    payload = reanalyze_resp.json()
    assert payload["status"] == "queued"

    assert "call" in captured
    args = captured["call"]
    assert args[0] == job_id
    assert args[1] == tenant.id
    assert args[2] == str(stored_path)
    assert args[3] == pytest.approx(118.0)

    session = SessionLocal()
    try:
        refreshed = session.query(Job).filter_by(id=job_id).first()
        assert refreshed is not None
        assert refreshed.status == "queued"
        assert refreshed.error is None
    finally:
        session.close()

    assert not Path(result["report_directory"]).exists()
    assert not Path(result["archive_path"]).exists()
    assert stored_path.exists()


def test_summary_masked_for_unverified(
    tmp_path: Path,
    sample_statement: Path,
    monkeypatch: pytest.MonkeyPatch,
    client: TestClient,
) -> None:
    data_root = tmp_path / "data"
    monkeypatch.setenv(DATA_ROOT_ENV, str(data_root))

    email = f"masked_{uuid.uuid4().hex[:6]}@example.com"
    register_resp = client.post(
        "/auth/register",
        json={"email": email, "password": "MaskedPass1!"},
    )
    assert register_resp.status_code == 201

    session = SessionLocal()
    try:
        user = session.query(User).filter(User.username == email).first()
        assert user is not None
        token = issue_token(session, user)
        tenant_id = user.tenant_id
    finally:
        session.close()

    job_id = uuid.uuid4().hex
    result = process_statement(
        tenant_id=tenant_id,
        job_id=job_id,
        statement_path=sample_statement,
        fx_rate=119.0,
    )

    session = SessionLocal()
    try:
        job = session.query(Job).filter_by(id=job_id).first()
        assert job is not None
        job.status = "completed"
        job.result_path = result["archive_path"]
        job.report_directory = result["report_directory"]
        job.summary = json.dumps(asdict(result["summary"]))
        session.add(job)
        session.commit()
    finally:
        session.close()

    headers = {"Authorization": f"Bearer {token}"}
    summary_resp = client.get(f"/statements/{job_id}/summary", headers=headers)
    assert summary_resp.status_code == 200
    summary_payload = summary_resp.json()
    assert summary_payload["summary"]["masked"] is True

    assets_resp = client.get(f"/statements/{job_id}/assets", headers=headers)
    assert assets_resp.status_code == 200
    assets_payload = assets_resp.json()
    assert assets_payload.get("masked") is True
