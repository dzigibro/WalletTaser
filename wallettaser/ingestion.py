"""Data ingestion helpers for Wallet Taser."""
from __future__ import annotations

from pathlib import Path
from typing import Union

import pandas as pd


StatementSource = Union[str, Path]


def load_clean(path: StatementSource) -> pd.DataFrame:
    """Load and standardise a bank statement spreadsheet.

    Parameters
    ----------
    path:
        Path to the spreadsheet containing a single statement. The header row
        can appear anywhere within the first 30 rows of the file.

    Returns
    -------
    pandas.DataFrame
        A dataframe with canonicalised column names (``Datum``, ``Tip``,
        ``Opis`` and ``Iznos``) and parsed date/amount values.
    """

    raw = pd.read_excel(path, header=None, dtype=str)
    header_row = next(
        idx
        for idx in range(min(len(raw), 30))
        if sum(
            any(keyword in str(col).lower() for keyword in ("datum", "tip", "opis", "iznos"))
            for col in raw.iloc[idx]
        )
        >= 3
    )

    df = pd.read_excel(path, header=header_row, dtype=str)
    renames: dict[str, str] = {}
    for column in df.columns:
        lowered = str(column).lower()
        if "datum" in lowered:
            renames[column] = "Datum"
        elif "tip" in lowered:
            renames[column] = "Tip"
        elif any(keyword in lowered for keyword in ("opis", "naziv", "det")):
            renames[column] = "Opis"
        elif any(keyword in lowered for keyword in ("iznos", "amount", "suma")):
            renames[column] = "Iznos"

    df = df.rename(columns=renames)[["Datum", "Tip", "Opis", "Iznos"]].dropna()
    df["Datum"] = pd.to_datetime(df["Datum"], dayfirst=True, errors="coerce")
    df = df[df["Datum"].notna()].copy()
    df["Iznos"] = (
        df["Iznos"].str.replace(r"[^0-9,.\\-]", "", regex=True)
        .str.replace(".", "", regex=False)
        .str.replace(",", ".", regex=False)
        .astype(float)
    )
    return df
