"""Reusable reporting pipeline extracted from :mod:`finance`."""
from __future__ import annotations

import csv
import json
import logging
import sqlite3
from dataclasses import dataclass, field
from datetime import timedelta
from itertools import cycle
from pathlib import Path
from typing import Iterable

import matplotlib.pyplot as plt
import pandas as pd

from finance import DEF_FX, fmt, load_clean, summary


@dataclass
class ReportSummary:
    months_observed: int
    average_savings: float
    average_income: float
    average_spend: float
    average_stock_investment: float
    projected_net: list[float]
    projected_savings: list[float]
    last_week_spend: float
    previous_week_spend: float
    delta_week_spend: float
    vampires: list[str]
    fx_rate: float
    net_flow: float
    monthly_spend: float
    monthly_savings: float
    total_spend: float
    savings_rate: float
    needs_spend: float
    wants_spend: float
    vampire_breakdown: list[dict[str, float]] = field(default_factory=list)


def _load_tags(tag_file: Path) -> dict[str, str]:
    if not tag_file.exists():
        return {}
    with tag_file.open(newline="") as handle:
        return {row["VENDOR"]: row["CLASS"] for row in csv.DictReader(handle)}


def _needs_wants(row: pd.Series, tags: dict[str, str]) -> str:
    if row["CATEGORY"] in ("SAVINGS", "STOCKS/CRYPTO"):
        return "TRANSFER"
    vendor_tag = tags.get(row["VENDOR"])
    if vendor_tag:
        return vendor_tag
    # default to WANTS to avoid silently promoting unknown vendors
    return "WANTS"


def _plot_totals(folder: Path, months: int, income: float, spend: float, savings: float, stocks: float) -> None:
    labels = ["Spend", "Save", "Stocks", "Income"]
    values = [abs(spend) * months, savings * months, stocks * months, income * months]
    plt.figure(figsize=(8, 4))
    bars = plt.bar(labels, values, color=["#e74c3c", "#27ae60", "#8e44ad", "#3498db"])
    for bar, value in zip(bars, values):
        plt.text(bar.get_x() + bar.get_width() / 2, value, fmt(value),
                 ha="center", va="bottom", fontsize=9)
    plt.title("Totals by Category")
    plt.ylabel("RSD")
    plt.tight_layout()
    plt.savefig(folder / "totals.png")
    plt.close()


TOP_COLORS = cycle(["#e74c3c", "#f1c40f", "#27ae60"])


def _plot_vendors(folder: Path, df: pd.DataFrame) -> None:
    top = (
        df[df.Iznos < 0]
        .groupby("VENDOR")["Iznos"]
        .sum()
        .abs()
        .sort_values(ascending=False)
        .head(10)
    )
    colors = [next(TOP_COLORS) if i < 3 else "#2980b9" for i in range(len(top))]
    plt.figure(figsize=(10, 6))
    bars = plt.bar(top.index, top.values, color=colors)
    for bar, value in zip(bars, top.values):
        plt.text(bar.get_x() + bar.get_width() / 2, value, fmt(value),
                 ha="center", va="bottom", fontsize=9)
    plt.title("Top Vendor Spend")
    plt.ylabel("RSD")
    plt.xticks(rotation=45)
    plt.tight_layout()
    plt.savefig(folder / "vendors_top.png")
    plt.close()


def _plot_weekday(folder: Path, df: pd.DataFrame) -> None:
    wk = df[df.Iznos < 0].groupby("DAY")["Iznos"].sum()
    plt.figure(figsize=(8, 4))
    wk.plot(kind="bar", color="#c0392b")
    plt.title("Spending by Weekday")
    plt.ylabel("RSD")
    plt.xticks(range(7), ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"])
    plt.tight_layout()
    plt.savefig(folder / "weekday_spend.png")
    plt.close()


def _plot_hourly(folder: Path, df: pd.DataFrame) -> None:
    hr = df[df.Iznos < 0].groupby("HOUR")["Iznos"].sum()
    if hr.sum() == 0 or hr.nunique() <= 1:
        return
    hr = hr.reindex(range(24), fill_value=0)
    plt.figure(figsize=(14, 4))
    hr.plot(kind="bar", color="#9b59b6")
    plt.grid(axis="y", alpha=0.3)
    plt.title("Spending by Hour (0-23)")
    plt.xlabel("Hour")
    plt.ylabel("RSD")
    plt.tight_layout()
    plt.savefig(folder / "hourly_spend.png")
    plt.close()


def _plot_monthly_trends(folder: Path, df: pd.DataFrame) -> None:
    monthly = (
        df.groupby(["YEAR_MONTH", "ADV_CAT"])["Iznos"]
        .sum()
        .unstack()
        .fillna(0)
    )
    monthly.plot(kind="bar", stacked=True, figsize=(12, 6))
    plt.title("Monthly Cash-flow by Advanced Category")
    plt.ylabel("RSD")
    plt.xticks(rotation=45)
    plt.tight_layout()
    plt.savefig(folder / "monthly_trends.png")
    plt.close()


def _plot_rolling(folder: Path, df: pd.DataFrame) -> None:
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


def _plot_monthly_net(folder: Path, df: pd.DataFrame) -> None:
    net_monthly = df.groupby("YEAR_MONTH")["Iznos"].sum()
    net_monthly.plot(marker="o", figsize=(10, 4))
    plt.axhline(0, color="gray", ls="--")
    plt.title("Monthly Net Δ")
    plt.ylabel("RSD")
    plt.tight_layout()
    plt.savefig(folder / "monthly_net.png")
    plt.close()


def _plot_needs_wants(folder: Path, df: pd.DataFrame) -> None:
    summary_df = (
        df[(df.Iznos < 0) & (df.NEEDS_WANTS != "TRANSFER")]
        .groupby("NEEDS_WANTS")["Iznos"]
        .sum()
        .abs()
    )
    summary_df = summary_df.reindex(["NEEDS", "WANTS"]).fillna(0)
    plt.figure(figsize=(7, 5))
    bars = plt.bar(summary_df.index, summary_df.values, color=["#2ecc71", "#e67e22"])
    for bar, value in zip(bars, summary_df.values):
        plt.text(bar.get_x() + bar.get_width() / 2, value, fmt(value),
                 ha="center", va="bottom", fontsize=10)
    plt.title("NEEDS vs WANTS")
    plt.ylabel("RSD")
    plt.tight_layout()
    plt.savefig(folder / "needs_wants.png")
    plt.close()


def _plot_projected_net(folder: Path, net_projection: Iterable[float]) -> None:
    xs = list(range(len(net_projection)))
    ys = list(net_projection)
    plt.figure(figsize=(10, 5))
    plt.plot(xs, ys, marker="o", color="#1abc9c")
    plt.title("Projected Net Worth")
    plt.xlabel("Months")
    plt.ylabel("RSD")
    plt.grid(alpha=0.3)
    plt.tight_layout()
    plt.savefig(folder / "projected_net.png")
    plt.close()


def _plot_projected_savings(folder: Path, savings_projection: Iterable[float]) -> None:
    xs = list(range(1, len(savings_projection) + 1))
    plt.figure(figsize=(10, 5))
    plt.plot(xs, savings_projection, marker="o", color="#e67e22")
    plt.title("Projected Savings Only (12 mo)")
    plt.xlabel("Months")
    plt.ylabel("RSD")
    plt.grid(alpha=0.3)
    plt.tight_layout()
    plt.savefig(folder / "projected_savings.png")
    plt.close()


def generate_report(
    statement_path: Path,
    output_folder: Path,
    *,
    fx_rate: float | None = None,
    tag_file: Path | None = None,
    sqlite_path: Path | None = None,
    debug: bool = False,
) -> ReportSummary:
    """Run the finance pipeline and persist the generated artefacts."""
    output_folder.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.DEBUG if debug else logging.INFO,
        format="[%(levelname)s] %(message)s",
    )

    fx_rate = fx_rate or DEF_FX
    tag_file = tag_file or Path("vendor_tags.csv")

    tags = _load_tags(tag_file)

    df = load_clean(str(statement_path))
    df["NEEDS_WANTS"] = df.apply(lambda row: _needs_wants(row, tags), axis=1)

    months, net_projection, savings_projection, avg_savings, avg_income, avg_spend, avg_stocks = summary(df)

    # plotting
    _plot_totals(output_folder, months, avg_income, avg_spend, avg_savings, avg_stocks)
    _plot_vendors(output_folder, df)
    _plot_needs_wants(output_folder, df)
    _plot_weekday(output_folder, df)
    _plot_hourly(output_folder, df)
    _plot_monthly_trends(output_folder, df)
    _plot_rolling(output_folder, df)
    _plot_monthly_net(output_folder, df)
    _plot_projected_net(output_folder, net_projection)
    _plot_projected_savings(output_folder, savings_projection)

    enriched_path = output_folder / "full_enriched_dataset.csv"
    df.to_csv(enriched_path, index=False)

    if sqlite_path is not None:
        with sqlite3.connect(sqlite_path) as connection:
            df.to_sql("tx", connection, if_exists="append", index=False)

    today = pd.Timestamp.today().normalize()
    last_week = abs(df[(df.Datum >= today - timedelta(days=7)) & (df.Iznos < 0)]["Iznos"].sum())
    previous_week = abs(
        df[
            (df.Datum >= today - timedelta(days=14))
            & (df.Datum < today - timedelta(days=7))
            & (df.Iznos < 0)
        ]["Iznos"].sum()
    )
    delta_week = last_week - previous_week
    spend_by_vendor = (
        df[df.Iznos < 0]
        .groupby("VENDOR")["Iznos"]
        .sum()
        .abs()
        .sort_values(ascending=False)
    )
    total_spend = float(spend_by_vendor.sum())
    vampire_breakdown: list[dict[str, float]] = []
    if total_spend > 0:
        for vendor, amount in spend_by_vendor.items():
            share = amount / total_spend if total_spend else 0.0
            if share < 0.04 and len(vampire_breakdown) >= 5:
                break
            vampire_breakdown.append(
                {
                    "vendor": vendor,
                    "share": round(share, 4),
                    "amount": round(float(amount), 2),
                }
            )
            if len(vampire_breakdown) >= 6:
                break

    vampires = [entry["vendor"] for entry in vampire_breakdown] or spend_by_vendor.head(3).index.tolist()

    monthly_spend = abs(avg_spend)
    monthly_savings = avg_savings
    net_flow = avg_income + monthly_savings + avg_stocks - monthly_spend
    savings_rate = monthly_savings / monthly_spend if monthly_spend > 0 else 1.0

    needs_spend = abs(
        df[(df.Iznos < 0) & (df.NEEDS_WANTS == "NEEDS")]["Iznos"].sum()
    )
    wants_spend = abs(
        df[(df.Iznos < 0) & (df.NEEDS_WANTS == "WANTS")]["Iznos"].sum()
    )

    summary_payload = ReportSummary(
        months_observed=months,
        average_savings=monthly_savings,
        average_income=avg_income,
        average_spend=avg_spend,
        average_stock_investment=avg_stocks,
        projected_net=list(net_projection),
        projected_savings=list(savings_projection),
        last_week_spend=last_week,
        previous_week_spend=previous_week,
        delta_week_spend=delta_week,
        vampires=vampires,
        fx_rate=fx_rate,
        net_flow=round(net_flow, 2),
        monthly_spend=round(monthly_spend, 2),
        monthly_savings=round(monthly_savings, 2),
        total_spend=round(total_spend, 2),
        savings_rate=round(savings_rate, 4),
        needs_spend=round(needs_spend, 2),
        wants_spend=round(wants_spend, 2),
        vampire_breakdown=vampire_breakdown,
    )

    metadata_path = output_folder / "metadata.json"
    with metadata_path.open("w", encoding="utf-8") as handle:
        json.dump(summary_payload.__dict__, handle, indent=2)

    return summary_payload
