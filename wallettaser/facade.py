"""High level facade for Wallet Taser processing."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

import pandas as pd

from . import analytics, categorization, ingestion, reporting


@dataclass
class ProcessedStatement:
    """Container returned by :func:`process_statement`."""

    dataframe: pd.DataFrame
    summary: analytics.Summary
    charts: Sequence[reporting.ChartSpec]
    fx_rate: float


def _prepare_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    enriched = df.copy()
    enriched["MONTH"] = enriched["Datum"].dt.to_period("M")
    enriched["YEAR_MONTH"] = enriched["MONTH"]
    enriched["DAY"] = enriched["Datum"].dt.dayofweek
    enriched["HOUR"] = enriched["Datum"].dt.hour
    return enriched


def process_statement(path_or_df, *, fx_rate: float) -> ProcessedStatement:
    """Process a bank statement into analytics and chart specifications."""

    if isinstance(path_or_df, (str, Path)):
        df = ingestion.load_clean(path_or_df)
    elif isinstance(path_or_df, pd.DataFrame):
        df = path_or_df.copy()
    else:  # pragma: no cover - defensive branch
        raise TypeError("path_or_df must be a path or pandas DataFrame")

    df = categorization.apply_categories(df)
    df = _prepare_dataframe(df)
    categorization.apply_needs_wants(df, tags=None, inplace=True)

    summary = analytics.summary(df)
    charts = reporting.build_chart_specs(df, summary)
    return ProcessedStatement(dataframe=df, summary=summary, charts=charts, fx_rate=fx_rate)
