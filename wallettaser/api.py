"""FastAPI application exposing the WalletTaser pipeline."""
from __future__ import annotations

import json
import mimetypes
import re
import shutil
import uuid
from pathlib import Path
from typing import Any, Dict, List

from fastapi import Depends, FastAPI, File, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from .auth import auth_router, ensure_default_user, get_current_user
from .database import Base, engine, get_session
from .models import Job, User
from .pipeline import get_data_root
from .tasks import process_statement_task

app = FastAPI(title="WalletTaser API")
app.include_router(auth_router)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

ensure_default_user()


ALLOWED_EXTENSIONS = {".xls", ".xlsx", ".csv"}
ALLOWED_ASSET_EXTENSIONS = {".png", ".csv", ".json"}
_FILENAME_SANITIZER = re.compile(r"[^A-Za-z0-9._-]")


def _sanitize_upload_filename(filename: str) -> str:
    """Return a safe filename limited to allowed extensions."""
    if not filename:
        raise HTTPException(status_code=400, detail="filename required")
    name = Path(filename).name
    suffix = Path(name).suffix.lower()
    if suffix not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail="Unsupported file type")
    stem = Path(name).stem
    safe_stem = _FILENAME_SANITIZER.sub("_", stem)[:40] or "statement"
    return f"{safe_stem}{suffix}"


def _serialize_job(job: Job) -> Dict[str, Any]:
    """Convert a job ORM instance to a JSON-serialisable dict."""
    return {
        "job_id": job.id,
        "tenant_id": job.tenant_id,
        "filename": job.filename,
        "status": job.status,
        "fx_rate": job.fx_rate,
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "updated_at": job.updated_at.isoformat() if job.updated_at else None,
        "started_at": job.started_at.isoformat() if job.started_at else None,
        "completed_at": job.completed_at.isoformat() if job.completed_at else None,
        "result_path": job.result_path,
        "report_directory": job.report_directory,
        "error": job.error,
        "summary": json.loads(job.summary) if job.summary else None,
    }


def _get_owned_job(session: Session, job_id: str, tenant_id: int) -> Job:
    job = session.query(Job).filter(Job.id == job_id, Job.tenant_id == tenant_id).first()
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@app.on_event("startup")
def _create_schema() -> None:
    Base.metadata.create_all(bind=engine)


@app.post("/statements/upload")
def upload_statement(
    file: UploadFile = File(...),
    fx_rate: float | None = None,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    job_id = uuid.uuid4().hex
    tenant_id = user.tenant_id
    sanitized_name = _sanitize_upload_filename(file.filename)
    suffix = Path(sanitized_name).suffix
    job = Job(
        id=job_id,
        tenant_id=tenant_id,
        filename=sanitized_name,
        status="queued",
        fx_rate=fx_rate,
    )
    session.add(job)
    session.commit()

    tenant_root = get_data_root() / str(tenant_id) / "uploads" / job_id
    tenant_root.mkdir(parents=True, exist_ok=True)
    stored_filename = f"{job_id}{suffix}"
    saved_path = tenant_root / stored_filename
    with saved_path.open("wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
    file.file.close()

    process_statement_task.delay(job_id, tenant_id, str(saved_path), fx_rate)

    return {
        "job_id": job_id,
        "status": job.status,
        "detail_path": f"/statements/{job_id}",
    }


@app.get("/statements", response_model=List[Dict[str, Any]])
def list_jobs(
    limit: int = 25,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    jobs = (
        session.query(Job)
        .filter(Job.tenant_id == user.tenant_id)
        .order_by(Job.created_at.desc())
        .limit(limit)
        .all()
    )
    return [_serialize_job(job) for job in jobs]


@app.get("/statements/{job_id}")
def get_job_status(
    job_id: str,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    job = _get_owned_job(session, job_id, user.tenant_id)
    return _serialize_job(job)


@app.get("/statements/{job_id}/summary")
def get_job_summary(
    job_id: str,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    job = _get_owned_job(session, job_id, user.tenant_id)
    if not job.summary:
        raise HTTPException(status_code=404, detail="Summary not available")
    return {
        "job_id": job.id,
        "summary": json.loads(job.summary),
    }


@app.get("/statements/{job_id}/result")
def download_result(
    job_id: str,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    job = _get_owned_job(session, job_id, user.tenant_id)
    if job.status != "completed" or not job.result_path:
        raise HTTPException(status_code=400, detail="Job not completed")

    archive_path = Path(job.result_path)
    if not archive_path.exists():
        raise HTTPException(status_code=404, detail="Result missing")
    return FileResponse(archive_path, media_type="application/zip", filename=archive_path.name)


@app.get("/statements/{job_id}/assets")
def list_job_assets(
    job_id: str,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    job = _get_owned_job(session, job_id, user.tenant_id)
    if job.status != "completed" or not job.report_directory:
        raise HTTPException(status_code=400, detail="Job not completed")

    report_dir = Path(job.report_directory)
    if not report_dir.exists():
        raise HTTPException(status_code=404, detail="Report directory missing")

    assets: List[Dict[str, Any]] = []
    for path in report_dir.rglob("*"):
        if not path.is_file():
            continue
        suffix = path.suffix.lower()
        if suffix not in ALLOWED_ASSET_EXTENSIONS:
            continue
        relative_name = path.relative_to(report_dir).as_posix()
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        assets.append(
            {
                "name": relative_name,
                "size": path.stat().st_size,
                "content_type": content_type,
            }
        )
    assets.sort(key=lambda item: item["name"])
    return {"assets": assets}


@app.get("/statements/{job_id}/asset")
def get_job_asset(
    job_id: str,
    name: str = Query(..., min_length=1),
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    job = _get_owned_job(session, job_id, user.tenant_id)
    if job.status != "completed" or not job.report_directory:
        raise HTTPException(status_code=400, detail="Job not completed")

    report_dir = Path(job.report_directory)
    if not report_dir.exists():
        raise HTTPException(status_code=404, detail="Report directory missing")

    requested = Path(name)
    if requested.is_absolute() or any(part == ".." for part in requested.parts):
        raise HTTPException(status_code=400, detail="Invalid asset path")

    file_path = (report_dir / requested).resolve()
    try:
        report_root = report_dir.resolve()
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Report directory missing")

    if report_root not in file_path.parents:
        raise HTTPException(status_code=400, detail="Invalid asset path")

    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(status_code=404, detail="Asset not found")

    if file_path.suffix.lower() not in ALLOWED_ASSET_EXTENSIONS:
        raise HTTPException(status_code=400, detail="Unsupported asset type")

    media_type = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"
    return FileResponse(file_path, media_type=media_type, filename=file_path.name)
