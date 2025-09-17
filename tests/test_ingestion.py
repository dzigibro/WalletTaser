import pandas as pd

from wallettaser import ingestion


def test_load_clean(monkeypatch):
    raw = pd.DataFrame(
        [
            ["noise", "noise", "noise", "noise"],
            ["Datum", "Tip", "Opis", "Iznos"],
            ["2024", "2024", "2024", "2024"],
        ]
    )
    cleaned = pd.DataFrame(
        {
            "Datum transakcije": ["01.01.2024", "02.01.2024"],
            "Tip": ["Priliv", "Odliv"],
            "Opis": ["Salary", "Maxi market"],
            "Iznos": ["1.000,00", "-200,50"],
        }
    )

    def fake_read_excel(path, header=None, dtype=None):
        return raw if header is None else cleaned

    monkeypatch.setattr(ingestion.pd, "read_excel", fake_read_excel)

    df = ingestion.load_clean("dummy.xlsx")
    assert list(df.columns) == ["Datum", "Tip", "Opis", "Iznos"]
    assert len(df) == 2
    assert df.loc[df["Opis"] == "Salary", "Iznos"].iloc[0] == 1000.0
    assert df.loc[df["Opis"] == "Maxi market", "Iznos"].iloc[0] == -200.50
    assert pd.api.types.is_datetime64_any_dtype(df["Datum"])  # dates parsed
