"""Analytical helpers for Wallet Taser."""
from __future__ import annotations

from dataclasses import dataclass
from typing import List

import pandas as pd


@dataclass(frozen=True)
class Summary:
    months: int
    projected_net: List[float]
    projected_savings: List[float]
    avg_savings: float
    avg_income: float
    avg_spend: float
    avg_stocks: float


def project_savings(avg_save: float, months: int = 12) -> List[float]:
    """Return the cumulative savings projection for the given monthly average."""
    return [round(avg_save * month, 2) for month in range(1, months + 1)]


def summary(df: pd.DataFrame) -> Summary:
    """Compute summary metrics for a categorised dataframe."""
    months = df["MONTH"].nunique() or 1
    selector = lambda category: df[df.CATEGORY == category]["Iznos"].sum()
    income = selector("INCOME")
    spend = selector("SPENDING")
    savings = selector("SAVINGS")
    stocks = abs(selector("STOCKS/CRYPTO"))

    avg_income = income / months
    avg_spend = spend / months
    avg_savings = savings / months
    avg_stocks = stocks / months

    projected_net = [0.0]
    for _ in range(12):
        projected_net.append(projected_net[-1] + avg_income - abs(avg_spend) + avg_savings + avg_stocks)

    projected_savings = project_savings(avg_savings, 12)
    return Summary(
        months=months,
        projected_net=projected_net,
        projected_savings=projected_savings,
        avg_savings=avg_savings,
        avg_income=avg_income,
        avg_spend=avg_spend,
        avg_stocks=avg_stocks,
    )
