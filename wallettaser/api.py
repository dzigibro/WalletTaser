"""FastAPI application exposing the WalletTaser pipeline."""
from __future__ import annotations

import shutil
import uuid
from pathlib import Path

from fastapi import Depends, FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from .auth import auth_router, ensure_default_user, get_current_user
from .database import Base, engine, get_session
from .models import Job, User
from .pipeline import get_data_root
from .tasks import process_statement_task

app = FastAPI(title="WalletTaser API")
app.include_router(auth_router)

ensure_default_user()


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
    if not file.filename:
        raise HTTPException(status_code=400, detail="filename required")

    job_id = uuid.uuid4().hex
    tenant_id = user.tenant_id
    job = Job(id=job_id, tenant_id=tenant_id, filename=file.filename, status="queued")
    session.add(job)
    session.commit()

    tenant_root = get_data_root() / str(tenant_id) / "uploads" / job_id
    tenant_root.mkdir(parents=True, exist_ok=True)
    saved_path = tenant_root / file.filename
    with saved_path.open("wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
    file.file.close()

    process_statement_task.delay(job_id, tenant_id, str(saved_path), fx_rate)

    return {"job_id": job_id, "status": job.status}


@app.get("/statements/{job_id}")
def get_job_status(
    job_id: str,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    job = session.query(Job).filter(Job.id == job_id, Job.tenant_id == user.tenant_id).first()
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return {
        "job_id": job.id,
        "status": job.status,
        "result_path": job.result_path,
        "error": job.error,
    }


@app.get("/statements/{job_id}/result")
def download_result(
    job_id: str,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    job = session.query(Job).filter(Job.id == job_id, Job.tenant_id == user.tenant_id).first()
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.status != "completed" or not job.result_path:
        raise HTTPException(status_code=400, detail="Job not completed")

    archive_path = Path(job.result_path)
    if not archive_path.exists():
        raise HTTPException(status_code=404, detail="Result missing")
    return FileResponse(archive_path, media_type="application/zip", filename=archive_path.name)
