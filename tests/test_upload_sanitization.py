"""Tests around upload sanitisation helpers."""
from __future__ import annotations

import pytest
from fastapi import HTTPException

from wallettaser.api import _sanitize_upload_filename


def test_sanitize_accepts_supported_extensions() -> None:
    assert _sanitize_upload_filename("my-file.XLS") == "my-file.xls"
    assert _sanitize_upload_filename("../weird/path/report.xlsx") == "report.xlsx"


def test_sanitize_rejects_unsupported_extensions() -> None:
    with pytest.raises(HTTPException):
        _sanitize_upload_filename("evil.sh")


def test_sanitize_normalises_name() -> None:
    safe = _sanitize_upload_filename("🔥budget 2024!!.csv")
    assert safe.startswith("_budget_2024")
    assert safe.endswith(".csv")
