import sys
from pathlib import Path
from unittest import mock

import pandas as pd

import finance
from wallettaser.analytics import Summary
from wallettaser.facade import ProcessedStatement


def test_cli_delegates_to_facade(monkeypatch, tmp_path):
    data = pd.DataFrame(
        {
            "Datum": pd.to_datetime(["2024-01-01"]),
            "Iznos": [-100.0],
            "Tip": ["Odliv"],
            "Opis": ["Store"],
            "CATEGORY": ["SPENDING"],
            "VENDOR": ["STORE"],
            "ADV_CAT": ["OTHER"],
            "MONTH": pd.PeriodIndex(["2024-01"], freq="M"),
            "YEAR_MONTH": pd.PeriodIndex(["2024-01"], freq="M"),
            "DAY": [0],
            "HOUR": [12],
            "NEEDS_WANTS": ["WANTS"],
        }
    )
    summary = Summary(
        months=1,
        projected_net=[0.0, 10.0],
        projected_savings=[10.0],
        avg_savings=10.0,
        avg_income=20.0,
        avg_spend=-30.0,
        avg_stocks=5.0,
    )
    processed = ProcessedStatement(dataframe=data.copy(), summary=summary, charts=[], fx_rate=100.0)

    mock_process = mock.Mock(return_value=processed)
    monkeypatch.setattr(finance, "process_statement", mock_process)
    monkeypatch.setattr(finance, "load_vendor_tags", lambda: {})
    monkeypatch.setattr(finance, "tag_new_vendors", lambda df, tags: False)

    created_folders = []

    def fake_render(result, folder):
        folder_path = Path(folder)
        folder_path.mkdir(parents=True, exist_ok=True)
        created_folders.append(folder_path)

    monkeypatch.setattr(finance, "render_reports", fake_render)

    dummy_file = tmp_path / "statement.xlsx"
    dummy_file.write_text("dummy")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", ["finance.py", "-f", str(dummy_file), "--fx", "100"])

    finance.main()

    assert mock_process.call_count == 1
    _, kwargs = mock_process.call_args
    assert kwargs["fx_rate"] == 100.0
    assert created_folders, "render_reports should be invoked"
    csv_files = list(created_folders[0].glob("full_enriched_dataset.csv"))
    assert csv_files and csv_files[0].is_file()
