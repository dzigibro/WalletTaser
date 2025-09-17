"""Tenant-aware wrappers around the reporting pipeline."""
from __future__ import annotations

import os
import zipfile
from pathlib import Path
from typing import TypedDict

from .reporting import ReportSummary, generate_report

DATA_ROOT_ENV = "WALLETTASER_DATA_ROOT"
DEFAULT_DATA_ROOT = Path("data")


class PipelineResult(TypedDict):
    report_directory: str
    archive_path: str
    summary: ReportSummary


def get_data_root() -> Path:
    """Return the base directory that stores tenant specific data."""
    root = Path(os.getenv(DATA_ROOT_ENV, DEFAULT_DATA_ROOT))
    if not root.is_absolute():
        root = Path.cwd() / root
    root.mkdir(parents=True, exist_ok=True)
    return root


def tenant_root(tenant_id: int | str) -> Path:
    base = get_data_root()
    path = base / str(tenant_id)
    path.mkdir(parents=True, exist_ok=True)
    return path


def process_statement(
    *,
    tenant_id: int | str,
    job_id: str,
    statement_path: Path,
    fx_rate: float | None = None,
) -> PipelineResult:
    """Run the reporting pipeline for ``statement_path`` and return artefacts."""
    tenant_dir = tenant_root(tenant_id)
    reports_dir = tenant_dir / "reports" / job_id
    uploads_dir = tenant_dir / "uploads"
    uploads_dir.mkdir(parents=True, exist_ok=True)

    tag_file = tenant_dir / "vendor_tags.csv"

    report_summary = generate_report(
        statement_path,
        reports_dir,
        fx_rate=fx_rate,
        tag_file=tag_file,
    )

    archive_dir = tenant_dir / "archives"
    archive_dir.mkdir(parents=True, exist_ok=True)
    archive_path = archive_dir / f"{job_id}.zip"

    with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in reports_dir.rglob("*"):
            if path.is_file():
                archive.write(path, path.relative_to(reports_dir))

    return PipelineResult(
        report_directory=str(reports_dir),
        archive_path=str(archive_path),
        summary=report_summary,
    )
