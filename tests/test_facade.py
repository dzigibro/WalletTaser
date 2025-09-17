import pandas as pd

from wallettaser import facade


def test_process_statement_with_dataframe():
    df = pd.DataFrame(
        {
            "Datum": pd.to_datetime(["2024-01-01", "2024-01-02"]),
            "Tip": ["Priliv", "Odliv"],
            "Opis": ["Salary", "Maxi purchase"],
            "Iznos": [1000.0, -200.0],
        }
    )

    result = facade.process_statement(df, fx_rate=120.0)
    expected_columns = {"CATEGORY", "VENDOR", "ADV_CAT", "MONTH", "YEAR_MONTH", "DAY", "HOUR", "NEEDS_WANTS"}
    assert expected_columns.issubset(result.dataframe.columns)
    assert len(result.charts) == 10
    assert result.summary.months == 1
    assert result.fx_rate == 120.0
