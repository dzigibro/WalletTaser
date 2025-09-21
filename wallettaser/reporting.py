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
from cycler import cycler

from finance import DEF_FX, fmt, load_clean, summary


plt.style.use("seaborn-v0_8-darkgrid")
plt.rcParams.update(
    {
        "figure.facecolor": "#0f172a",
        "axes.facecolor": "#091125",
        "axes.edgecolor": "#1e293b",
        "axes.grid": True,
        "axes.spines.top": False,
        "axes.spines.right": False,
        "grid.color": "#1e293b",
        "grid.alpha": 0.55,
        "text.color": "#e2e8f0",
        "axes.labelcolor": "#cbd5f5",
        "xtick.color": "#cbd5f5",
        "ytick.color": "#cbd5f5",
        "font.size": 11,
        "axes.prop_cycle": cycler(
            color=[
                "#38bdf8",
                "#a855f7",
                "#22c55e",
                "#f97316",
                "#facc15",
            ]
        ),
    }
)


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
    untagged_vendors: list[str] = field(default_factory=list)


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
    colors = ["#f97316", "#22d3ee", "#a855f7", "#38bdf8"]

    fig, ax = plt.subplots(figsize=(8, 4.5))
    bars = ax.bar(labels, values, color=colors, edgecolor="#0f172a", linewidth=1.2)

    for bar, value in zip(bars, values):
        ax.text(
            bar.get_x() + bar.get_width() / 2,
            value * 1.03,
            fmt(value),
            ha="center",
            va="bottom",
            fontsize=11,
            color="#f8fafc",
        )

    ax.set_title("Totals by category", fontsize=14, color="#f8fafc", pad=14)
    ax.set_ylabel("RSD")
    ax.set_axisbelow(True)
    ax.spines["bottom"].set_visible(False)
    ax.spines["left"].set_visible(False)
    fig.tight_layout()
    fig.savefig(folder / "totals.png", dpi=180)
    plt.close(fig)


TOP_COLORS = cycle(["#f97316", "#facc15", "#ef4444", "#a855f7", "#22d3ee"])


def _plot_vendors(folder: Path, df: pd.DataFrame) -> None:
    top = (
        df[df.Iznos < 0]
        .groupby("VENDOR")["Iznos"]
        .sum()
        .abs()
        .sort_values(ascending=False)
        .head(8)
    )
    if top.empty:
        return
    colors = [next(TOP_COLORS) for _ in range(len(top))]
    fig, ax = plt.subplots(figsize=(10, 5.5))
    bars = ax.bar(top.index, top.values, color=colors, linewidth=0)
    for bar, value in zip(bars, top.values):
        ax.text(
            bar.get_x() + bar.get_width() / 2,
            value * 1.02,
            fmt(value),
            ha="center",
            va="bottom",
            fontsize=10,
            color="#f8fafc",
        )
    ax.set_title("Where your cash actually went", fontsize=14, pad=16)
    ax.set_ylabel("RSD")
    ax.set_xticklabels(top.index, rotation=35, ha="right")
    ax.spines["bottom"].set_visible(False)
    ax.spines["left"].set_visible(False)
    fig.tight_layout()
    fig.savefig(folder / "vendors_top.png", dpi=180)
    plt.close(fig)


def _plot_weekday(folder: Path, df: pd.DataFrame) -> None:
    wk = df[df.Iznos < 0].groupby("DAY")["Iznos"].sum()
    if wk.empty:
        return
    fig, ax = plt.subplots(figsize=(8, 4.2))
    colors = ["#38bdf8" if day < 5 else "#f97316" for day in wk.index]
    ax.bar(["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"], wk.reindex(range(7), fill_value=0), color=colors)
    ax.set_title("Weekday damage", fontsize=13, pad=12)
    ax.set_ylabel("RSD")
    ax.spines["bottom"].set_visible(False)
    ax.spines["left"].set_visible(False)
    fig.tight_layout()
    fig.savefig(folder / "weekday_spend.png", dpi=160)
    plt.close(fig)


def _plot_hourly(folder: Path, df: pd.DataFrame) -> None:
    hr = df[df.Iznos < 0].groupby("HOUR")["Iznos"].sum()
    if hr.sum() == 0 or hr.nunique() <= 1:
        return
    hr = hr.reindex(range(24), fill_value=0)
    fig, ax = plt.subplots(figsize=(12, 4))
    ax.plot(hr.index, hr.values, color="#a855f7", linewidth=2.2, marker="o", markersize=4)
    ax.fill_between(hr.index, hr.values, color="#a855f7", alpha=0.18)
    ax.set_title("When the swipes happen", fontsize=13, pad=12)
    ax.set_xlabel("Hour of day")
    ax.set_ylabel("RSD")
    ax.set_xlim(0, 23)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    fig.tight_layout()
    fig.savefig(folder / "hourly_spend.png", dpi=160)
    plt.close(fig)


def _plot_monthly_trends(folder: Path, df: pd.DataFrame) -> None:
    monthly = (
        df.groupby(["YEAR_MONTH", "ADV_CAT"])["Iznos"]
        .sum()
        .unstack()
        .fillna(0)
    )
    if monthly.empty:
        return
    fig, ax = plt.subplots(figsize=(11.5, 5.5))
    monthly.plot(kind="bar", stacked=True, ax=ax, alpha=0.9)
    ax.set_title("Cashflow by category", fontsize=14, pad=14)
    ax.set_ylabel("RSD")
    ax.set_xlabel("")
    ax.legend(loc="upper left", bbox_to_anchor=(1.02, 1), frameon=False)
    ax.set_xticklabels([str(idx) for idx in monthly.index], rotation=35, ha="right")
    fig.tight_layout()
    fig.savefig(folder / "monthly_trends.png", dpi=170, bbox_inches="tight")
    plt.close(fig)


def _plot_rolling(folder: Path, df: pd.DataFrame) -> None:
    daily = (
        df[df.Iznos < 0]
        .set_index("Datum")
        .resample("D")["Iznos"]
        .sum()
        .abs()
    )
    window = 30 if len(daily) >= 30 else 7
    rolling = daily.rolling(window).sum()
    if rolling.empty:
        return
    fig, ax = plt.subplots(figsize=(11, 4.5))
    ax.plot(rolling.index, rolling.values, color="#38bdf8", linewidth=2.5)
    ax.fill_between(rolling.index, rolling.values, color="#38bdf8", alpha=0.18)
    ax.set_title(f"{window}-day burn rate", fontsize=13, pad=12)
    ax.set_ylabel("RSD")
    ax.set_xlabel("")
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    fig.autofmt_xdate()
    fig.tight_layout()
    fig.savefig(folder / f"rolling{window}_spend.png", dpi=170)
    plt.close(fig)


def _plot_monthly_net(folder: Path, df: pd.DataFrame) -> None:
    net_monthly = df.groupby("YEAR_MONTH")["Iznos"].sum()
    if net_monthly.empty:
        return
    fig, ax = plt.subplots(figsize=(10, 4.3))
    ax.plot(net_monthly.index, net_monthly.values, marker="o", color="#22d3ee", linewidth=2.4)
    ax.axhline(0, color="#64748b", linestyle="--", linewidth=1)
    ax.set_title("Monthly net change", fontsize=13, pad=12)
    ax.set_ylabel("RSD")
    ax.set_xlabel("")
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    fig.autofmt_xdate()
    fig.tight_layout()
    fig.savefig(folder / "monthly_net.png", dpi=170)
    plt.close(fig)


def _plot_needs_wants(folder: Path, df: pd.DataFrame) -> None:
    summary_df = (
        df[(df.Iznos < 0) & (df.NEEDS_WANTS != "TRANSFER")]
        .groupby("NEEDS_WANTS")["Iznos"]
        .sum()
        .abs()
    )
    summary_df = summary_df.reindex(["NEEDS", "WANTS"]).fillna(0)
    fig, ax = plt.subplots(figsize=(7.5, 4.5))
    bars = ax.bar(summary_df.index, summary_df.values, color=["#22c55e", "#f97316"], width=0.55)
    for bar, value in zip(bars, summary_df.values):
        ax.text(
            bar.get_x() + bar.get_width() / 2,
            value * 1.04,
            fmt(value),
            ha="center",
            va="bottom",
            fontsize=10,
            color="#f8fafc",
        )
    ax.set_title("Needs vs wants", fontsize=13, pad=12)
    ax.set_ylabel("RSD")
    ax.spines["bottom"].set_visible(False)
    ax.spines["left"].set_visible(False)
    fig.tight_layout()
    fig.savefig(folder / "needs_wants.png", dpi=170)
    plt.close(fig)


def _plot_projected_net(folder: Path, net_projection: Iterable[float]) -> None:
    xs = list(range(len(net_projection)))
    ys = list(net_projection)
    if not ys:
        return
    fig, ax = plt.subplots(figsize=(9.5, 4.5))
    ax.plot(xs, ys, color="#22d3ee", linewidth=2.5)
    ax.fill_between(xs, ys, color="#22d3ee", alpha=0.2)
    ax.set_title("Projected net worth", fontsize=13, pad=12)
    ax.set_xlabel("Months")
    ax.set_ylabel("RSD")
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    fig.tight_layout()
    fig.savefig(folder / "projected_net.png", dpi=170)
    plt.close(fig)


def _plot_projected_savings(folder: Path, savings_projection: Iterable[float]) -> None:
    xs = list(range(1, len(savings_projection) + 1))
    if not xs:
        return
    fig, ax = plt.subplots(figsize=(9.5, 4.5))
    ax.plot(xs, savings_projection, color="#facc15", linewidth=2.5)
    ax.fill_between(xs, savings_projection, color="#facc15", alpha=0.25)
    ax.set_title("Projected savings", fontsize=13, pad=12)
    ax.set_xlabel("Months")
    ax.set_ylabel("RSD")
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    fig.tight_layout()
    fig.savefig(folder / "projected_savings.png", dpi=170)
    plt.close(fig)


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
    untagged_vendors = [
        vendor
        for vendor in spend_by_vendor.index
        if vendor not in tags
    ][:8]
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
        untagged_vendors=untagged_vendors,
    )

    metadata_path = output_folder / "metadata.json"
    with metadata_path.open("w", encoding="utf-8") as handle:
        json.dump(summary_payload.__dict__, handle, indent=2)

    return summary_payload
