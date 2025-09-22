"""Tenant-aware wrappers around the reporting pipeline."""
from __future__ import annotations

import csv
import os
import zipfile
from pathlib import Path
from typing import Dict, Optional, TypedDict

from .reporting import ReportSummary, generate_report

DATA_ROOT_ENV = "WALLETTASER_DATA_ROOT"
DEFAULT_DATA_ROOT = Path("data")
STATEMENT_EXTENSIONS = {".xls", ".xlsx", ".csv"}


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


def vendor_tags_path(tenant_id: int | str) -> Path:
    return tenant_root(tenant_id) / "vendor_tags.csv"


def load_vendor_tags(path: Path) -> Dict[str, str]:
    if not path.exists():
        return {}
    with path.open(newline="") as handle:
        reader = csv.DictReader(handle)
        tags: Dict[str, str] = {}
        for row in reader:
            vendor = (row.get("VENDOR") or "").strip().upper()
            classification = (row.get("CLASS") or "").strip().upper()
            if not vendor or classification not in {"NEEDS", "WANTS"}:
                continue
            tags[vendor] = classification
        return tags


def write_vendor_tags(path: Path, tags: Dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["VENDOR", "CLASS"])
        writer.writeheader()
        for vendor, classification in sorted(tags.items()):
            writer.writerow(
                {
                    "VENDOR": (vendor or "").strip().upper(),
                    "CLASS": (classification or "").strip().upper(),
                }
            )


def locate_statement_source(tenant_id: int | str, job_id: str) -> Optional[Path]:
    """Return the uploaded statement path for ``job_id`` if it exists."""
    uploads_dir = tenant_root(tenant_id) / "uploads" / job_id
    if not uploads_dir.exists():
        return None
    for candidate in sorted(uploads_dir.iterdir()):
        if candidate.is_file() and candidate.suffix.lower() in STATEMENT_EXTENSIONS:
            return candidate
    return None


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

    tag_file = vendor_tags_path(tenant_id)

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
