import pandas as pd

from wallettaser import categorization


def make_df():
    return pd.DataFrame(
        {
            "Datum": pd.to_datetime(["2024-01-01", "2024-01-02"]),
            "Tip": ["Priliv", "Odliv"],
            "Opis": ["Primanje", "Kupovina EUR"],
            "Iznos": [1000.0, -200.0],
        }
    )


def test_vendor_pattern_matching():
    assert categorization.vendor("Shopping at Maxi store") == "MAXI"
    assert categorization.vendor("Unknown 123") == "UNKNOWN"


def test_apply_categories_adjusts_columns():
    df = make_df()
    categorised = categorization.apply_categories(df)
    assert set(["CATEGORY", "VENDOR", "ADV_CAT"]).issubset(categorised.columns)
    assert categorised.loc[categorised["Opis"] == "Primanje", "CATEGORY"].iloc[0] == "INCOME"
    # Savings transactions must be positive
    assert categorised.loc[categorised["Opis"] == "Kupovina EUR", "Iznos"].iloc[0] == 200.0


def test_apply_needs_wants_uses_tags():
    df = make_df()
    categorised = categorization.apply_categories(df)
    updated = categorization.apply_needs_wants(categorised, tags={"PRIMANJE": "NEEDS"})
    assert set(updated["NEEDS_WANTS"]) == {"TRANSFER", "NEEDS"}
