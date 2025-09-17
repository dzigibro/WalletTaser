#!/usr/bin/env python3
"""Wallet Taser CLI wrapper."""
from __future__ import annotations

import argparse
import csv
import glob
import logging
import os
import sqlite3
import textwrap
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict

import pandas as pd

from wallettaser import ProcessedStatement, process_statement
from wallettaser.categorization import apply_needs_wants

TAG_FILE = "vendor_tags.csv"
DEF_FX = 117.0

fmt = lambda value: f"{value:,.2f}"
latest_xls = lambda: sorted(glob.glob("*.xls*"), key=os.path.getmtime, reverse=True)[0]


# ─────────────────── logging ────────────────────
def setup_logging(debug: bool) -> None:
    logging.basicConfig(level=logging.DEBUG if debug else logging.INFO, format="[%(levelname)s] %(message)s")


# ─────────────────── tagging helpers ────────────────────
def load_vendor_tags(path: str = TAG_FILE) -> Dict[str, str]:
    try:
        with open(path, newline="") as handle:
            return {row["VENDOR"]: row["CLASS"] for row in csv.DictReader(handle)}
    except FileNotFoundError:
        return {}


def save_vendor_tags(tags: Dict[str, str], path: str = TAG_FILE) -> None:
    with open(path, "w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["VENDOR", "CLASS"])
        writer.writeheader()
        for vendor, klass in sorted(tags.items()):
            writer.writerow({"VENDOR": vendor, "CLASS": klass})


def tag_new_vendors(df: pd.DataFrame, tags: Dict[str, str]) -> bool:
    updated = False
    freq = df["VENDOR"].value_counts().loc[lambda series: series >= 3].index.difference(tags)
    if not freq.empty:
        print("\n► Tag vendors: NEEDS (n) / WANTS (w)")
    for vendor in freq:
        while True:
            answer = input(f"  {vendor}: n/w? ").strip().lower()
            if answer in ("n", "w"):
                tags[vendor] = "NEEDS" if answer == "n" else "WANTS"
                updated = True
                break
    return updated


# ─────────────────── CLI ────────────────────
PARSER = argparse.ArgumentParser(
    description="Balkan Schizo Finance – Wallet Taser",
    formatter_class=argparse.RawDescriptionHelpFormatter,
    epilog=textwrap.dedent(
        """
      Examples:
        python3 finance.py
        python3 finance.py -f bank.xlsx --fx 118 --sqlite --debug
        """
    ),
)
PARSER.add_argument("-f", "--file", help="bank statement (.xls/.xlsx)")
PARSER.add_argument("--fx", type=float, help=f"RSD→EUR (default {DEF_FX})")
PARSER.add_argument("--sqlite", action="store_true", help="append rows to transactions.db")
PARSER.add_argument("--debug", action="store_true", help="verbose logging")


# ─────────────────── orchestration ────────────────────
def ensure_needs_wants(result: ProcessedStatement, tags: Dict[str, str]) -> None:
    apply_needs_wants(result.dataframe, tags, inplace=True)


def render_reports(result: ProcessedStatement, folder: Path) -> None:
    for spec in result.charts:
        spec.render(folder, result.dataframe, result.summary)


def main() -> None:
    args = PARSER.parse_args()
    setup_logging(args.debug)

    if args.file:
        path = args.file
    else:
        latest = latest_xls()
        logging.info("Using statement %s", latest)
        path = latest

    fx = args.fx or float(input(f"RSD→EUR rate (Enter for {DEF_FX}): ") or DEF_FX)

    result = process_statement(path, fx_rate=fx)
    tags = load_vendor_tags()
    if tag_new_vendors(result.dataframe, tags):
        save_vendor_tags(tags)
    ensure_needs_wants(result, tags)

    folder = Path(f"finance_report_{datetime.now():%Y%m%d_%H%M%S}")
    render_reports(result, folder)

    csv_path = folder / "full_enriched_dataset.csv"
    result.dataframe.to_csv(csv_path, index=False)
    if args.sqlite:
        with sqlite3.connect("transactions.db") as connection:
            result.dataframe.to_sql("tx", connection, if_exists="append", index=False)

    today = pd.Timestamp.today().normalize()
    df = result.dataframe
    last7 = abs(df[(df.Datum >= today - timedelta(days=7)) & (df.Iznos < 0)]["Iznos"].sum())
    prev7 = abs(
        df[
            (df.Datum >= today - timedelta(days=14))
            & (df.Datum < today - timedelta(days=7))
            & (df.Iznos < 0)
        ]["Iznos"].sum()
    )
    delta = last7 - prev7
    total_spend = df[df.Iznos < 0]["Iznos"].abs().sum()
    vampires = (
        df[df.Iznos < 0]
        .groupby("VENDOR")["Iznos"]
        .sum()
        .abs()
        .div(total_spend)
        .loc[lambda series: series > 0.05]
        .index.tolist()
    )

    summary = result.summary
    net_12 = summary.projected_net[-1]
    print(
        f"\nMonths: {summary.months} | Avg save: {fmt(summary.avg_savings)} RSD"
        f" | Net 12 mo: {fmt(net_12)} RSD ({fmt(net_12 / result.fx_rate)} €)"
    )
    print(f"Last 7-day spend: {fmt(last7)} RSD (Δ {fmt(delta)} vs prev 7 d)")
    if vampires:
        print("Consider cutting:", ", ".join(vampires))
    print("Projected pure savings (12 mo):")
    for idx, value in enumerate(summary.projected_savings, 1):
        print(f"  +{idx:02d} mo → {fmt(value)} RSD ({fmt(value / result.fx_rate)} €)")
    print("Charts + CSV saved →", folder)


if __name__ == "__main__":
    main()
