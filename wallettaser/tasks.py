"""Celery task definitions."""
from __future__ import annotations

import logging
from pathlib import Path

from sqlalchemy.orm import Session

from .celery_app import celery_app
from .database import SessionLocal
from .models import Job
from .pipeline import process_statement


@celery_app.task(bind=True)
def process_statement_task(self, job_id: str, tenant_id: int, statement_path: str, fx_rate: float | None = None) -> dict:
    logging.info("Starting processing for job %s", job_id)
    session: Session = SessionLocal()
    try:
        job = session.query(Job).filter(Job.id == job_id, Job.tenant_id == tenant_id).first()
        if job is None:
            logging.error("Job %s not found", job_id)
            return {"status": "missing"}
        job.status = "processing"
        session.commit()

        result = process_statement(
            tenant_id=tenant_id,
            job_id=job_id,
            statement_path=Path(statement_path),
            fx_rate=fx_rate,
        )

        job.status = "completed"
        job.result_path = result["archive_path"]
        job.report_directory = result["report_directory"]
        session.commit()
        logging.info("Job %s completed", job_id)
        return {
            "status": job.status,
            "archive_path": job.result_path,
            "report_directory": job.report_directory,
        }
    except Exception as exc:  # noqa: BLE001
        session.rollback()
        logging.exception("Job %s failed", job_id)
        job = session.query(Job).filter(Job.id == job_id).first()
        if job:
            job.status = "failed"
            job.error = str(exc)
            session.commit()
        raise
    finally:
        session.close()
