"""Tests for report asset listing and retrieval endpoints."""
from __future__ import annotations

import json
import uuid
from dataclasses import asdict
from pathlib import Path

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from wallettaser.api import app
from wallettaser.database import SessionLocal
from wallettaser.models import Job, Tenant
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

    token_resp = client.post("/auth/token", json={"username": "demo", "password": "demo"})
    assert token_resp.status_code == 200
    token = token_resp.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    assets_resp = client.get(f"/statements/{job_id}/assets", headers=headers)
    assert assets_resp.status_code == 200
    assets = assets_resp.json()["assets"]
    assert assets
    assert any(asset["name"].endswith("totals.png") for asset in assets)

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

    after_delete = client.get(f"/statements/{job_id}", headers=headers)
    assert after_delete.status_code == 404

    assert report_dir_path and not report_dir_path.exists()
    assert archive_path and not archive_path.exists()
    assert uploads_dir and not uploads_dir.exists()
