from pathlib import Path

import pandas as pd

from wallettaser import analytics, reporting


def build_dataframe():
    dates = pd.date_range("2024-01-01", periods=48, freq="h")
    df = pd.DataFrame(
        {
            "Datum": dates,
            "Iznos": [-100.0 - idx for idx in range(len(dates))],
            "Tip": ["Odliv"] * len(dates),
            "Opis": ["Maxi"] * len(dates),
            "CATEGORY": ["SPENDING"] * len(dates),
            "VENDOR": ["MAXI"] * len(dates),
            "ADV_CAT": ["FOOD"] * len(dates),
            "MONTH": dates.to_period("M"),
            "YEAR_MONTH": dates.to_period("M"),
            "DAY": dates.dayofweek,
            "HOUR": dates.hour,
            "NEEDS_WANTS": ["WANTS"] * len(dates),
        }
    )
    income_row = {
        "Datum": pd.Timestamp("2024-01-05"),
        "Iznos": 1000.0,
        "Tip": "Priliv",
        "Opis": "Salary",
        "CATEGORY": "INCOME",
        "VENDOR": "COMPANY",
        "ADV_CAT": "INCOME",
        "MONTH": pd.Timestamp("2024-01-05").to_period("M"),
        "YEAR_MONTH": pd.Timestamp("2024-01-05").to_period("M"),
        "DAY": pd.Timestamp("2024-01-05").dayofweek,
        "HOUR": pd.Timestamp("2024-01-05").hour,
        "NEEDS_WANTS": "WANTS",
    }
    df = pd.concat([df, pd.DataFrame([income_row])], ignore_index=True)
    return df


def test_chart_specs_render_all(tmp_path):
    df = build_dataframe()
    summary = analytics.summary(df)
    specs = reporting.build_chart_specs(df, summary)
    assert len(specs) == 10

    output_dir = Path(tmp_path)
    for spec in specs:
        spec.render(output_dir, df, summary)

    files = {path.name for path in output_dir.iterdir() if path.is_file()}
    expected = {
        "totals.png",
        "vendors_top.png",
        "weekday_spend.png",
        "hourly_spend.png",
        "monthly_trends.png",
        "monthly_net.png",
        "needs_wants.png",
        "projected_net.png",
        "projected_savings.png",
    }
    assert expected.issubset(files)
    assert any(name.startswith("rolling") for name in files)
