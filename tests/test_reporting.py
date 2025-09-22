"""Regression tests for the reporting and pipeline helpers."""
from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pandas as pd
import pytest

from wallettaser.pipeline import DATA_ROOT_ENV, process_statement
from wallettaser.reporting import generate_report


def _create_sample_statement(path: Path) -> None:
    """Write a tiny Excel statement that stresses key classifications."""
    rows = [
        {"Datum": "01.01.2023", "Tip": "Uplata", "Opis": "Zarada plata", "Iznos": "50000"},
        {"Datum": "03.01.2023", "Tip": "Card", "Opis": "Lidl grocery", "Iznos": "-8000"},
        {"Datum": "05.01.2023", "Tip": "Card", "Opis": "Car Go ride", "Iznos": "-2000"},
        {"Datum": "09.01.2023", "Tip": "Kartica", "Opis": "Kupovina EUR stednja", "Iznos": "-10000"},
        {"Datum": "12.01.2023", "Tip": "Card", "Opis": "Binance top up", "Iznos": "-5000"},
        {"Datum": "20.01.2023", "Tip": "ATM", "Opis": "Bankomat downtown", "Iznos": "-3000"},
    ]
    frame = pd.DataFrame(rows)
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_excel(path, index=False)


def _mock_pdf_table() -> pd.DataFrame:
    rows = [
        ["Datum", "Tip", "Opis", "Iznos"],
        ["01.01.2023", "Uplata", "Zarada plata", "50000"],
        ["03.01.2023", "Card", "Lidl grocery", "-8000"],
        ["05.01.2023", "Card", "Car Go ride", "-2000"],
    ]
    return pd.DataFrame(rows)


@pytest.fixture(scope="module")
def sample_statement(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Return the path to a reusable sample statement."""
    path = tmp_path_factory.mktemp("data") / "statement.xlsx"
    _create_sample_statement(path)
    return path


@pytest.fixture(autouse=True)
def isolate_matplotlib_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Force matplotlib to use a writable cache directory during tests."""
    cache_dir = tmp_path / "mpl-cache"
    cache_dir.mkdir(exist_ok=True)
    monkeypatch.setenv("MPLCONFIGDIR", str(cache_dir))


def test_generate_report_summary(tmp_path: Path, sample_statement: Path) -> None:
    """`generate_report` should produce consistent summary metrics."""
    output_dir = tmp_path / "report"
    summary = generate_report(sample_statement, output_dir)

    assert summary.months_observed == 1
    assert summary.average_income == pytest.approx(50_000)
    assert summary.average_spend == pytest.approx(-13_000)
    assert summary.average_savings == pytest.approx(10_000)
    assert summary.average_stock_investment == pytest.approx(5_000)
    assert summary.monthly_savings == pytest.approx(summary.average_savings)
    assert summary.monthly_spend == pytest.approx(abs(summary.average_spend))

    expected_net_flow = (
        summary.average_income
        + summary.average_savings
        + summary.average_stock_investment
        - summary.monthly_spend
    )
    assert summary.net_flow == pytest.approx(expected_net_flow)

    assert summary.total_spend >= summary.monthly_spend
    if summary.monthly_spend > 0:
        assert summary.savings_rate == pytest.approx(
            summary.monthly_savings / summary.monthly_spend, rel=1e-3
        )
    assert summary.needs_spend + summary.wants_spend <= summary.total_spend + 1

    assert summary.projected_net[0] == 0
    assert summary.projected_net[-1] == pytest.approx(624_000)
    assert summary.projected_savings[-1] == pytest.approx(120_000)

    vampires = set(summary.vampires)
    assert {"LIDL", "CAR GO", "BANKOMAT"}.issubset(vampires)
    if summary.vampire_breakdown:
        breakdown_vendors = {entry["vendor"] for entry in summary.vampire_breakdown}
        assert {"LIDL", "CAR GO", "BANKOMAT"} & breakdown_vendors
    assert summary.untagged_vendors
    assert summary.fx_rate == pytest.approx(117.0)

    metadata_path = output_dir / "metadata.json"
    assert metadata_path.exists()
    with metadata_path.open(encoding="utf-8") as handle:
        payload = json.load(handle)
    assert payload["average_income"] == summary.average_income
    assert payload["projected_savings"][-1] == summary.projected_savings[-1]
    assert payload["net_flow"] == summary.net_flow
    assert payload["total_spend"] == summary.total_spend
    assert payload["untagged_vendors"] == summary.untagged_vendors


def test_load_clean_handles_pdf(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from finance import load_clean

    pdf_path = tmp_path / "statement.pdf"
    pdf_path.write_bytes(b"%PDF-test")

    monkeypatch.setattr("finance._read_pdf_statement", lambda path: _mock_pdf_table())

    df = load_clean(str(pdf_path))

    assert not df.empty
    assert set(df.columns) >= {"Datum", "Tip", "Opis", "Iznos"}
    assert len(df) == 3


def test_process_statement_creates_artifacts(
    tmp_path: Path,
    sample_statement: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`process_statement` should write reports + archives under the tenant root."""
    data_root = tmp_path / "tenant-data"
    monkeypatch.setenv(DATA_ROOT_ENV, str(data_root))

    result = process_statement(
        tenant_id="tenant-1",
        job_id="job-123",
        statement_path=sample_statement,
        fx_rate=110.5,
    )

    report_dir = Path(result["report_directory"])
    archive_path = Path(result["archive_path"])
    summary = result["summary"]

    assert report_dir.exists()
    assert (report_dir / "full_enriched_dataset.csv").exists()
    assert archive_path.exists()

    with zipfile.ZipFile(archive_path) as archive:
        names = set(archive.namelist())
    assert "full_enriched_dataset.csv" in names
    assert "metadata.json" in names

    assert summary.months_observed == 1
    assert summary.average_income == pytest.approx(50_000)
    assert summary.average_savings == pytest.approx(10_000)
    assert summary.fx_rate == pytest.approx(110.5)
    assert summary.total_spend > 0
    assert summary.vampire_breakdown
    assert isinstance(summary.untagged_vendors, list)

    # check tenant isolation paths
    assert data_root in report_dir.parents
    assert data_root in archive_path.parents
