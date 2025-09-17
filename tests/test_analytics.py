import pandas as pd

from wallettaser import analytics


def build_df():
    df = pd.DataFrame(
        {
            "Datum": pd.to_datetime(["2024-01-01", "2024-01-15", "2024-01-20", "2024-02-10"]),
            "Iznos": [1000.0, -200.0, 100.0, -50.0],
            "CATEGORY": ["INCOME", "SPENDING", "SAVINGS", "STOCKS/CRYPTO"],
        }
    )
    df["MONTH"] = df["Datum"].dt.to_period("M")
    return df


def test_project_savings():
    assert analytics.project_savings(100.0, months=3) == [100.0, 200.0, 300.0]


def test_summary_computes_averages():
    df = build_df()
    result = analytics.summary(df)
    assert result.months == 2
    assert result.avg_income == 500.0
    assert result.avg_savings == 50.0
    assert len(result.projected_net) == 13
    assert len(result.projected_savings) == 12
