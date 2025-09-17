"""Categorisation helpers for Wallet Taser."""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, Iterable, Mapping

import pandas as pd


PATTERNS: Dict[str, Iterable[str]] = {
    "MAXI": ["maxi"],
    "TIDAL": ["tidal"],
    "CAR GO": ["car go", "cargo"],
    "APOTEKA": ["apoteka"],
    "LIDL": ["lidl"],
    "EBAY": ["ebay"],
    "ALIEXPRESS": ["aliexpress", "ali express", "ali"],
    "GO TECH": ["go technologies"],
    "PAYPAL": ["paypal"],
    "WOLT": ["wolt"],
    "DEXPRESS": ["dexpress"],
}

ADVANCED_PATTERNS: Dict[str, Iterable[str]] = {
    "FOOD": ["lidl", "maxi", "idea", "tempo", "shop&go"],
    "TRANSPORT": ["car go", "naxis", "busplus"],
    "EDUCATION": ["udemy", "tryhackme", "coursera", "book"],
    "MEDICAL": ["apoteka", "pharmacy", "dr"],
    "ENTERTAINMENT": ["netflix", "tidal", "youtube", "spotify"],
}


@dataclass(frozen=True)
class CategorisationConfig:
    """Configuration used when assigning high level categories."""

    advanced_patterns: Dict[str, Iterable[str]] | None = None


def vendor(description: str) -> str:
    """Infer the most likely vendor name from a transaction description."""
    lowered = description.lower()
    for name, keys in PATTERNS.items():
        if any(keyword in lowered for keyword in keys):
            return name
    match = re.search(r"[A-Za-z]{4,}", description)
    return match.group(0).upper() if match else "OTHER"


def _base_cat(row: pd.Series) -> str:
    """Assign the base category for a transaction."""
    opis = row["Opis"].lower()
    tip = row["Tip"].lower()
    amount = row["Iznos"]

    if "kupovina eur" in opis:
        return "SAVINGS"
    if any(word in opis for word in ("zarada", "prilivi")) or "uplata" in tip:
        return "INCOME"
    if any(word in opis for word in ("xtb", "binance", "bifinity", "bit")):
        return "STOCKS/CRYPTO"
    if any(word in opis for word in ("bankomat", "isplata gotovine")):
        return "ATM_CASHOUT"
    if amount > 0:
        return "INCOME"
    return "SPENDING"


def _adv_cat(row: pd.Series, config: CategorisationConfig | None = None) -> str:
    """Assign the advanced category for a transaction."""
    patterns = (config.advanced_patterns if config and config.advanced_patterns else ADVANCED_PATTERNS)
    lowered = row["Opis"].lower()
    for category, keys in patterns.items():
        if any(keyword in lowered for keyword in keys):
            return category
    return _base_cat(row)


def apply_categories(df: pd.DataFrame, config: CategorisationConfig | None = None) -> pd.DataFrame:
    """Return a dataframe with category columns populated."""
    df = df.copy()
    df["CATEGORY"] = df.apply(_base_cat, axis=1)
    df.loc[df["CATEGORY"] == "SAVINGS", "Iznos"] = df.loc[df["CATEGORY"] == "SAVINGS", "Iznos"].abs()
    df["VENDOR"] = df["Opis"].apply(vendor)
    df["ADV_CAT"] = df.apply(_adv_cat, axis=1, config=config)
    return df


def needs_wants(row: pd.Series, tags: Mapping[str, str] | None = None) -> str:
    """Classify a row into NEEDS/WANTS based on vendor tags."""

    if row["CATEGORY"] in ("SAVINGS", "STOCKS/CRYPTO"):
        return "TRANSFER"
    lookup = tags or {}
    return lookup.get(row["VENDOR"], "WANTS")


def apply_needs_wants(
    df: pd.DataFrame,
    tags: Mapping[str, str] | None = None,
    *,
    inplace: bool = False,
) -> pd.DataFrame:
    """Assign NEEDS/WANTS classes to transactions."""

    target = df if inplace else df.copy()
    lookup = dict(tags or {})
    target["NEEDS_WANTS"] = target.apply(needs_wants, axis=1, tags=lookup)
    return target
