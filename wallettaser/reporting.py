"""Reporting helpers for Wallet Taser."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from itertools import cycle
from pathlib import Path
from typing import Callable, Iterable, List

import matplotlib.pyplot as plt
import pandas as pd

from .analytics import Summary


fmt = lambda value: f"{value:,.2f}"


@dataclass
class ChartSpec:
    """Representation of a report chart."""

    filename: str
    renderer: Callable[[Path, pd.DataFrame, Summary], None]

    def render(self, folder: Path, df: pd.DataFrame, summary: Summary) -> None:
        """Render the chart into ``folder`` using ``df`` and ``summary``."""
        folder = Path(folder)
        folder.mkdir(parents=True, exist_ok=True)
        self.renderer(folder, df, summary)


def safe(func: Callable[..., None]) -> Callable[..., None]:
    """Decorator that logs rendering failures without aborting the run."""

    def wrapper(folder: Path, df: pd.DataFrame, summary: Summary) -> None:
        try:
            func(folder, df, summary)
        except Exception as exc:  # pragma: no cover - defensive logging
            logging.warning("%s failed: %s", func.__name__, exc)

    return wrapper


@safe
def plot_totals(folder: Path, df: pd.DataFrame, summary: Summary) -> None:
    labels = ["Spend", "Save", "Stocks", "Income"]
    values = [abs(summary.avg_spend) * summary.months, summary.avg_savings * summary.months,
              summary.avg_stocks * summary.months, summary.avg_income * summary.months]
    plt.figure(figsize=(8, 4))
    bars = plt.bar(labels, values, color=["#e74c3c", "#27ae60", "#8e44ad", "#3498db"])
    for bar, value in zip(bars, values):
        plt.text(bar.get_x() + bar.get_width() / 2, value, fmt(value), ha="center", va="bottom", fontsize=9)
    plt.title("Totals by Category")
    plt.ylabel("RSD")
    plt.tight_layout()
    plt.savefig(folder / "totals.png")
    plt.close()


TOP_COLORS = cycle(["#e74c3c", "#f1c40f", "#27ae60"])


@safe
def plot_vendors(folder: Path, df: pd.DataFrame, summary: Summary) -> None:
    top = (
        df[df.Iznos < 0]
        .groupby("VENDOR")["Iznos"]
        .sum()
        .abs()
        .sort_values(ascending=False)
        .head(10)
    )
    colors = [next(TOP_COLORS) if idx < 3 else "#2980b9" for idx in range(len(top))]
    plt.figure(figsize=(10, 6))
    bars = plt.bar(top.index, top.values, color=colors)
    for bar, value in zip(bars, top.values):
        plt.text(bar.get_x() + bar.get_width() / 2, value, fmt(value), ha="center", va="bottom", fontsize=9)
    plt.title("Top Vendor Spend")
    plt.ylabel("RSD")
    plt.xticks(rotation=45)
    plt.tight_layout()
    plt.savefig(folder / "vendors_top.png")
    plt.close()


@safe
def plot_weekday(folder: Path, df: pd.DataFrame, summary: Summary) -> None:
    weekly = df[df.Iznos < 0].groupby("DAY")["Iznos"].sum()
    plt.figure(figsize=(8, 4))
    weekly.plot(kind="bar", color="#c0392b")
    plt.title("Spending by Weekday")
    plt.ylabel("RSD")
    plt.xticks(range(7), ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"])
    plt.tight_layout()
    plt.savefig(folder / "weekday_spend.png")
    plt.close()


@safe
def plot_hourly(folder: Path, df: pd.DataFrame, summary: Summary) -> None:
    hourly = df[df.Iznos < 0].groupby("HOUR")["Iznos"].sum()
    if hourly.sum() == 0 or hourly.nunique() <= 1:
        return
    hourly = hourly.reindex(range(24), fill_value=0)
    plt.figure(figsize=(14, 4))
    hourly.plot(kind="bar", color="#9b59b6")
    plt.grid(axis="y", alpha=0.3)
    plt.title("Spending by Hour (0-23)")
    plt.xlabel("Hour")
    plt.ylabel("RSD")
    plt.tight_layout()
    plt.savefig(folder / "hourly_spend.png")
    plt.close()


@safe
def plot_monthly_trends(folder: Path, df: pd.DataFrame, summary: Summary) -> None:
    monthly = df.groupby(["YEAR_MONTH", "ADV_CAT"])["Iznos"].sum().unstack().fillna(0)
    monthly.plot(kind="bar", stacked=True, figsize=(12, 6))
    plt.title("Monthly Cash-flow by Advanced Category")
    plt.ylabel("RSD")
    plt.xticks(rotation=45)
    plt.tight_layout()
    plt.savefig(folder / "monthly_trends.png")
    plt.close()


@safe
def plot_rolling(folder: Path, df: pd.DataFrame, summary: Summary) -> None:
    daily = (
        df[df.Iznos < 0]
        .set_index("Datum")
        .resample("D")["Iznos"]
        .sum()
        .abs()
    )
    window = 30 if len(daily) >= 30 else 7
    daily.rolling(window).sum().plot(figsize=(12, 5))
    plt.title(f"{window}-Day Rolling Spend")
    plt.ylabel("RSD")
    plt.tight_layout()
    plt.savefig(folder / f"rolling{window}_spend.png")
    plt.close()


@safe
def plot_monthly_net(folder: Path, df: pd.DataFrame, summary: Summary) -> None:
    net_monthly = df.groupby("YEAR_MONTH")["Iznos"].sum()
    net_monthly.plot(marker="o", figsize=(10, 4))
    plt.axhline(0, color="gray", ls="--")
    plt.title("Monthly Net Δ")
    plt.ylabel("RSD")
    plt.tight_layout()
    plt.savefig(folder / "monthly_net.png")
    plt.close()


@safe
def plot_needs_wants(folder: Path, df: pd.DataFrame, summary: Summary) -> None:
    selection = (
        df[(df.Iznos < 0) & (df.NEEDS_WANTS != "TRANSFER")]
        .groupby("NEEDS_WANTS")["Iznos"]
        .sum()
        .abs()
    )
    selection = selection.reindex(["NEEDS", "WANTS"]).fillna(0)
    plt.figure(figsize=(7, 5))
    bars = plt.bar(selection.index, selection.values, color=["#2ecc71", "#e67e22"])
    for bar, value in zip(bars, selection.values):
        plt.text(bar.get_x() + bar.get_width() / 2, value, fmt(value), ha="center", va="bottom", fontsize=10)
    plt.title("NEEDS vs WANTS")
    plt.ylabel("RSD")
    plt.tight_layout()
    plt.savefig(folder / "needs_wants.png")
    plt.close()


@safe
def plot_projected_net(folder: Path, df: pd.DataFrame, summary: Summary) -> None:
    xs = list(range(len(summary.projected_net)))
    plt.figure(figsize=(10, 5))
    plt.plot(xs, summary.projected_net, marker="o", color="#1abc9c")
    plt.title("Projected Net Worth")
    plt.xlabel("Months")
    plt.ylabel("RSD")
    plt.grid(alpha=0.3)
    plt.tight_layout()
    plt.savefig(folder / "projected_net.png")
    plt.close()


@safe
def plot_projected_savings(folder: Path, df: pd.DataFrame, summary: Summary) -> None:
    xs = list(range(1, len(summary.projected_savings) + 1))
    plt.figure(figsize=(10, 5))
    plt.plot(xs, summary.projected_savings, marker="o", color="#e67e22")
    plt.title("Projected Savings Only (12 mo)")
    plt.xlabel("Months")
    plt.ylabel("RSD")
    plt.grid(alpha=0.3)
    plt.tight_layout()
    plt.savefig(folder / "projected_savings.png")
    plt.close()


def build_chart_specs(df: pd.DataFrame, summary: Summary) -> List[ChartSpec]:
    """Return the list of chart specs for the given dataset."""
    renderers: Iterable[tuple[str, Callable[[Path, pd.DataFrame, Summary], None]]] = (
        ("totals.png", plot_totals),
        ("vendors_top.png", plot_vendors),
        ("weekday_spend.png", plot_weekday),
        ("hourly_spend.png", plot_hourly),
        ("monthly_trends.png", plot_monthly_trends),
        ("rolling_spend.png", plot_rolling),
        ("monthly_net.png", plot_monthly_net),
        ("needs_wants.png", plot_needs_wants),
        ("projected_net.png", plot_projected_net),
        ("projected_savings.png", plot_projected_savings),
    )
    return [ChartSpec(filename=name, renderer=renderer) for name, renderer in renderers]
