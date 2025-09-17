from __future__ import annotations

import csv
import logging
import os
import queue
import sqlite3
import threading
from dataclasses import dataclass
from typing import Dict, Optional

DB_PATH = 'wallettaser.db'
TAG_CSV = 'vendor_tags.csv'


class VendorTagRepository:
    """Persistence helper for vendor tagging metadata."""

    def __init__(self, db_path: str = DB_PATH) -> None:
        self.db_path = db_path
        self._ensure_schema()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path)

    def _ensure_schema(self) -> None:
        with self._connect() as con:
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS vendor_tags (
                    user_id TEXT NOT NULL,
                    vendor TEXT NOT NULL,
                    class TEXT NOT NULL,
                    PRIMARY KEY (user_id, vendor)
                )
                """
            )

    def migrate_from_csv(self, csv_path: str = TAG_CSV, user_id: str = 'default') -> None:
        """Load legacy CSV tags into sqlite, keeping a backup of the file."""

        if not os.path.exists(csv_path):
            return

        with open(csv_path, newline='') as fh:
            reader = csv.DictReader(fh)
            rows = [
                (row.get('VENDOR', '').strip().upper(), row.get('CLASS', '').strip().upper())
                for row in reader
                if row.get('VENDOR')
            ]

        if not rows:
            return

        with self._connect() as con:
            con.executemany(
                "INSERT OR REPLACE INTO vendor_tags(user_id, vendor, class) VALUES (?, ?, ?)",
                [(user_id, vendor, cls) for vendor, cls in rows],
            )

        backup_path = f"{csv_path}.bak"
        try:
            os.replace(csv_path, backup_path)
            logging.info(
                "Migrated %s vendor tags from %s to sqlite (backup saved to %s)",
                len(rows),
                csv_path,
                backup_path,
            )
        except OSError:
            logging.warning("Migrated vendor tags but failed to archive %s", csv_path)

    def get_tags(self, user_id: str) -> Dict[str, str]:
        with self._connect() as con:
            cur = con.execute(
                "SELECT vendor, class FROM vendor_tags WHERE user_id=?",
                (user_id,),
            )
            return {vendor: cls for vendor, cls in cur.fetchall()}

    def get_tag(self, user_id: str, vendor: str) -> Optional[str]:
        with self._connect() as con:
            cur = con.execute(
                "SELECT class FROM vendor_tags WHERE user_id=? AND vendor=?",
                (user_id, vendor),
            )
            row = cur.fetchone()
            return row[0] if row else None

    def set_tag(self, user_id: str, vendor: str, cls: str) -> None:
        with self._connect() as con:
            con.execute(
                "INSERT OR REPLACE INTO vendor_tags(user_id, vendor, class) VALUES (?, ?, ?)",
                (user_id, vendor, cls),
            )

    def delete_tag(self, user_id: str, vendor: str) -> None:
        with self._connect() as con:
            con.execute(
                "DELETE FROM vendor_tags WHERE user_id=? AND vendor=?",
                (user_id, vendor),
            )

    def list_tags(self, user_id: str) -> list[dict[str, str]]:
        with self._connect() as con:
            cur = con.execute(
                "SELECT vendor, class FROM vendor_tags WHERE user_id=? ORDER BY vendor",
                (user_id,),
            )
            return [
                {"vendor": vendor, "class": cls}
                for vendor, cls in cur.fetchall()
            ]


def apply_tagging_decisions(
    df,
    repo: VendorTagRepository,
    user_id: str,
    decisions: Optional[Dict[str, str]] = None,
    default_class: str = 'WANTS',
    min_frequency: int = 3,
) -> Dict[str, str]:
    """Update vendor tags based on provided decisions.

    Vendors that appear more frequently than ``min_frequency`` without a stored tag
    receive ``default_class``. Decisions override stored values and are persisted.
    Returns the effective tag map for ``user_id``.
    """

    decisions = {
        (vendor or '').upper(): (cls or '').upper()
        for vendor, cls in (decisions or {}).items()
        if vendor
    }

    existing = repo.get_tags(user_id)

    vendor_counts = df['VENDOR'].value_counts()
    candidate_vendors = vendor_counts.loc[lambda s: s >= min_frequency].index.tolist()

    for vendor in candidate_vendors:
        if vendor in existing:
            continue
        choice = decisions.get(vendor, default_class)
        if choice not in ('NEEDS', 'WANTS'):
            choice = default_class
        repo.set_tag(user_id, vendor, choice)
        existing[vendor] = choice

    for vendor, choice in decisions.items():
        if choice not in ('NEEDS', 'WANTS'):
            continue
        if existing.get(vendor) == choice:
            continue
        repo.set_tag(user_id, vendor, choice)
        existing[vendor] = choice

    return existing


@dataclass
class ReprocessJob:
    user_id: str
    vendor: str


class TransactionReprocessor:
    """Background worker that updates stored transactions when tags change."""

    def __init__(self, repo: VendorTagRepository, db_path: str = DB_PATH) -> None:
        self.repo = repo
        self.db_path = db_path
        self._jobs: "queue.Queue[ReprocessJob]" = queue.Queue()
        self._thread = threading.Thread(target=self._worker, daemon=True)
        self._thread.start()

    def schedule(self, user_id: str, vendor: str) -> None:
        self._jobs.put(ReprocessJob(user_id=user_id, vendor=vendor))

    def _worker(self) -> None:
        while True:
            job = self._jobs.get()
            try:
                self._apply(job)
            except Exception as exc:  # pragma: no cover - defensive logging
                logging.exception("Failed to reprocess %s/%s: %s", job.user_id, job.vendor, exc)
            finally:
                self._jobs.task_done()

    def _apply(self, job: ReprocessJob) -> None:
        with sqlite3.connect(self.db_path) as con:
            cur = con.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
                ('transactions',),
            )
            if not cur.fetchone():
                return

            tag = self.repo.get_tag(job.user_id, job.vendor) or 'WANTS'
            con.execute(
                "UPDATE transactions SET NEEDS_WANTS=? WHERE USER_ID=? AND VENDOR=?",
                (tag, job.user_id, job.vendor),
            )
            con.commit()
