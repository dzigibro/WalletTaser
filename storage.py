"""Storage backends for WalletTaser artifacts and metadata.

This module introduces a simple abstraction capable of writing artifacts to a
filesystem or an object store (such as S3) while persisting metadata in a
SQLite database.  Each run of ``finance.py`` is treated as a *result* that can
contain multiple artifacts (PNG charts, CSV exports, JSON chart specs, …).

Retention policies are applied per user to keep overall storage usage within
reasonable bounds.
"""

from __future__ import annotations

import json
import os
import sqlite3
import time
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Optional


ISO_FORMAT = "%Y-%m-%dT%H:%M:%S.%fZ"


def utcnow() -> datetime:
    return datetime.utcnow()


@dataclass
class RetentionPolicy:
    """Simple per-user retention policy."""

    max_results: Optional[int] = None
    max_age_days: Optional[int] = None
    max_storage_mb: Optional[int] = None

    @classmethod
    def from_env(cls) -> "RetentionPolicy":
        def _env_int(name: str) -> Optional[int]:
            value = os.getenv(name)
            return int(value) if value else None

        return cls(
            max_results=_env_int("WALLETTASER_MAX_RESULTS"),
            max_age_days=_env_int("WALLETTASER_MAX_AGE_DAYS"),
            max_storage_mb=_env_int("WALLETTASER_MAX_STORAGE_MB"),
        )


class StorageError(RuntimeError):
    pass


class Storage:
    """Abstract storage backend."""

    def start_result(self, user_id: str, metadata: Optional[Dict[str, Any]] = None) -> str:
        raise NotImplementedError

    def save_artifact(
        self,
        user_id: str,
        result_id: str,
        name: str,
        content: bytes,
        content_type: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        raise NotImplementedError

    def save_json(
        self,
        user_id: str,
        result_id: str,
        name: str,
        payload: Dict[str, Any],
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        return self.save_artifact(
            user_id,
            result_id,
            name,
            json.dumps(payload).encode("utf-8"),
            "application/json",
            metadata=metadata,
        )

    def finalize_result(self, result_id: str, summary: Optional[Dict[str, Any]] = None) -> None:
        raise NotImplementedError

    def enforce_retention(self, user_id: str) -> None:
        raise NotImplementedError


class LocalStorage(Storage):
    """Store artifacts on the local filesystem with SQLite metadata."""

    def __init__(
        self,
        base_path: str = "storage",
        metadata_path: Optional[str] = None,
        retention_policy: Optional[RetentionPolicy] = None,
    ) -> None:
        self.base_path = Path(base_path)
        self.base_path.mkdir(parents=True, exist_ok=True)
        self.db_path = Path(metadata_path) if metadata_path else self.base_path / "metadata.db"
        self.retention = retention_policy or RetentionPolicy.from_env()
        self._init_db()

    # ------------------------------------------------------------------
    # SQLite helpers
    def _init_db(self) -> None:
        with self._db() as con:
            con.execute("PRAGMA foreign_keys = ON")
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS results (
                    result_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    metadata TEXT,
                    summary TEXT
                )
                """
            )
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS artifacts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    result_id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    uri TEXT NOT NULL,
                    content_type TEXT NOT NULL,
                    size INTEGER NOT NULL,
                    metadata TEXT,
                    FOREIGN KEY(result_id) REFERENCES results(result_id) ON DELETE CASCADE
                )
                """
            )

    @contextmanager
    def _db(self):
        con = sqlite3.connect(self.db_path)
        try:
            yield con
            con.commit()
        finally:
            con.close()

    # ------------------------------------------------------------------
    def start_result(self, user_id: str, metadata: Optional[Dict[str, Any]] = None) -> str:
        result_id = f"{int(time.time() * 1000)}"
        with self._db() as con:
            con.execute(
                "INSERT INTO results (result_id, user_id, created_at, metadata) VALUES (?, ?, ?, ?)",
                (result_id, user_id, utcnow().strftime(ISO_FORMAT), json.dumps(metadata or {})),
            )
        result_dir = self._result_dir(user_id, result_id)
        result_dir.mkdir(parents=True, exist_ok=True)
        return result_id

    def _result_dir(self, user_id: str, result_id: str) -> Path:
        return self.base_path / user_id / result_id

    def save_artifact(
        self,
        user_id: str,
        result_id: str,
        name: str,
        content: bytes,
        content_type: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        result_dir = self._result_dir(user_id, result_id)
        result_dir.mkdir(parents=True, exist_ok=True)
        artifact_path = result_dir / name
        artifact_path.write_bytes(content)
        rel_uri = str(artifact_path.relative_to(self.base_path))

        with self._db() as con:
            con.execute(
                """
                INSERT INTO artifacts (result_id, name, uri, content_type, size, metadata)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    result_id,
                    name,
                    rel_uri,
                    content_type,
                    len(content),
                    json.dumps(metadata or {}),
                ),
            )
        return rel_uri

    def finalize_result(self, result_id: str, summary: Optional[Dict[str, Any]] = None) -> None:
        if summary is None:
            return
        with self._db() as con:
            con.execute(
                "UPDATE results SET summary = ? WHERE result_id = ?",
                (json.dumps(summary), result_id),
            )

    # ------------------------------------------------------------------
    def enforce_retention(self, user_id: str) -> None:
        policy = self.retention
        if not any((policy.max_age_days, policy.max_results, policy.max_storage_mb)):
            return

        with self._db() as con:
            con.row_factory = sqlite3.Row
            rows = con.execute(
                "SELECT result_id, created_at FROM results WHERE user_id = ? ORDER BY created_at ASC",
                (user_id,),
            ).fetchall()

        to_delete = set()
        # Age-based retention
        if policy.max_age_days is not None:
            cutoff = utcnow() - timedelta(days=policy.max_age_days)
            for row in rows:
                created_at = datetime.strptime(row["created_at"], ISO_FORMAT)
                if created_at < cutoff:
                    to_delete.add(row["result_id"])

        # Count-based retention
        if policy.max_results is not None and len(rows) > policy.max_results:
            overflow = len(rows) - policy.max_results
            for row in rows[:overflow]:
                to_delete.add(row["result_id"])

        # Size-based retention
        if policy.max_storage_mb is not None:
            current_size = self._user_storage_size(user_id)
            limit_bytes = policy.max_storage_mb * 1024 * 1024
            if current_size > limit_bytes:
                # Remove the oldest results until we are below the limit.
                for row in rows:
                    rid = row["result_id"]
                    if rid in to_delete:
                        continue
                    self._delete_result(user_id, rid)
                    current_size = self._user_storage_size(user_id)
                    if current_size <= limit_bytes:
                        break
                # size-based deletions already performed, so we can return early
                return

        for rid in to_delete:
            self._delete_result(user_id, rid)

    def _user_storage_size(self, user_id: str) -> int:
        with self._db() as con:
            total = con.execute(
                """
                SELECT COALESCE(SUM(a.size), 0) FROM artifacts a
                JOIN results r ON r.result_id = a.result_id
                WHERE r.user_id = ?
                """,
                (user_id,),
            ).fetchone()[0]
        return int(total)

    def _delete_result(self, user_id: str, result_id: str) -> None:
        # Remove metadata first (CASCADE ensures artifacts go away)
        with self._db() as con:
            con.execute("DELETE FROM results WHERE result_id = ?", (result_id,))

        # Remove filesystem artifacts
        result_dir = self._result_dir(user_id, result_id)
        if result_dir.exists():
            for path in sorted(result_dir.glob("**/*"), reverse=True):
                if path.is_file():
                    path.unlink(missing_ok=True)
            for path in sorted(result_dir.glob("**/*"), reverse=True):
                if path.is_dir():
                    path.rmdir()
            result_dir.rmdir()


class S3Storage(Storage):
    """S3-backed artifact storage with SQLite metadata."""

    def __init__(
        self,
        bucket: str,
        prefix: str = "",
        metadata_path: str = "s3_metadata.db",
        retention_policy: Optional[RetentionPolicy] = None,
    ) -> None:
        try:
            import boto3
        except ImportError as exc:  # pragma: no cover - optional dependency
            raise StorageError("boto3 is required for S3Storage") from exc

        self.bucket = bucket
        self.prefix = prefix.strip("/")
        self.retention = retention_policy or RetentionPolicy.from_env()
        self._s3 = boto3.client("s3")
        self.db_path = Path(metadata_path)
        self._init_db()

    # SQLite helpers mirror LocalStorage but reuse logic via composition would
    # complicate things; implementation kept straightforward for clarity.
    def _init_db(self) -> None:
        with sqlite3.connect(self.db_path) as con:
            con.execute("PRAGMA foreign_keys = ON")
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS results (
                    result_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    metadata TEXT,
                    summary TEXT
                )
                """
            )
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS artifacts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    result_id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    uri TEXT NOT NULL,
                    content_type TEXT NOT NULL,
                    size INTEGER NOT NULL,
                    metadata TEXT,
                    FOREIGN KEY(result_id) REFERENCES results(result_id) ON DELETE CASCADE
                )
                """
            )

    @contextmanager
    def _db(self):
        con = sqlite3.connect(self.db_path)
        try:
            yield con
            con.commit()
        finally:
            con.close()

    def start_result(self, user_id: str, metadata: Optional[Dict[str, Any]] = None) -> str:
        result_id = f"{int(time.time() * 1000)}"
        with self._db() as con:
            con.execute(
                "INSERT INTO results (result_id, user_id, created_at, metadata) VALUES (?, ?, ?, ?)",
                (result_id, user_id, utcnow().strftime(ISO_FORMAT), json.dumps(metadata or {})),
            )
        return result_id

    def _s3_key(self, user_id: str, result_id: str, name: str) -> str:
        parts = [p for p in (self.prefix, user_id, result_id, name) if p]
        return "/".join(parts)

    def save_artifact(
        self,
        user_id: str,
        result_id: str,
        name: str,
        content: bytes,
        content_type: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        key = self._s3_key(user_id, result_id, name)
        self._s3.put_object(Bucket=self.bucket, Key=key, Body=content, ContentType=content_type)
        uri = f"s3://{self.bucket}/{key}"
        with self._db() as con:
            con.execute(
                """
                INSERT INTO artifacts (result_id, name, uri, content_type, size, metadata)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    result_id,
                    name,
                    uri,
                    content_type,
                    len(content),
                    json.dumps(metadata or {}),
                ),
            )
        return uri

    def finalize_result(self, result_id: str, summary: Optional[Dict[str, Any]] = None) -> None:
        if summary is None:
            return
        with self._db() as con:
            con.execute(
                "UPDATE results SET summary = ? WHERE result_id = ?",
                (json.dumps(summary), result_id),
            )

    def enforce_retention(self, user_id: str) -> None:
        # Reuse LocalStorage logic by instantiating a temporary LocalStorage that
        # points at the same database but without filesystem deletions.
        # For S3 we simply delete metadata records and issue delete_object calls.
        policy = self.retention
        if not any((policy.max_age_days, policy.max_results, policy.max_storage_mb)):
            return

        with self._db() as con:
            con.row_factory = sqlite3.Row
            rows = con.execute(
                "SELECT result_id, created_at FROM results WHERE user_id = ? ORDER BY created_at ASC",
                (user_id,),
            ).fetchall()

        to_delete = set()
        if policy.max_age_days is not None:
            cutoff = utcnow() - timedelta(days=policy.max_age_days)
            for row in rows:
                created_at = datetime.strptime(row["created_at"], ISO_FORMAT)
                if created_at < cutoff:
                    to_delete.add(row["result_id"])

        if policy.max_results is not None and len(rows) > policy.max_results:
            overflow = len(rows) - policy.max_results
            for row in rows[:overflow]:
                to_delete.add(row["result_id"])

        if policy.max_storage_mb is not None:
            limit_bytes = policy.max_storage_mb * 1024 * 1024
            while self._user_storage_size(user_id) > limit_bytes and rows:
                rid = rows.pop(0)["result_id"]
                to_delete.add(rid)

        for rid in to_delete:
            self._delete_result(user_id, rid)

    def _user_storage_size(self, user_id: str) -> int:
        with self._db() as con:
            total = con.execute(
                """
                SELECT COALESCE(SUM(a.size), 0) FROM artifacts a
                JOIN results r ON r.result_id = a.result_id
                WHERE r.user_id = ?
                """,
                (user_id,),
            ).fetchone()[0]
        return int(total)

    def _delete_result(self, user_id: str, result_id: str) -> None:
        with self._db() as con:
            artifact_rows = con.execute(
                "SELECT uri FROM artifacts WHERE result_id = ?",
                (result_id,),
            ).fetchall()
            con.execute("DELETE FROM results WHERE result_id = ?", (result_id,))

        for (uri,) in artifact_rows:
            # uri looks like s3://bucket/key
            key = uri.split("/", 3)[-1]
            self._s3.delete_object(Bucket=self.bucket, Key=key)


def get_storage(backend: Optional[str] = None, **kwargs: Any) -> Storage:
    backend = (backend or os.getenv("WALLETTASER_STORAGE_BACKEND", "local")).lower()
    retention = kwargs.pop("retention_policy", RetentionPolicy.from_env())

    if backend == "local":
        base_path = kwargs.pop("base_path", os.getenv("WALLETTASER_STORAGE_PATH", "storage"))
        metadata_path = kwargs.pop("metadata_path", os.getenv("WALLETTASER_METADATA_PATH"))
        return LocalStorage(base_path=base_path, metadata_path=metadata_path, retention_policy=retention)
    if backend == "s3":
        bucket = kwargs.pop("bucket", os.getenv("WALLETTASER_S3_BUCKET"))
        if not bucket:
            raise StorageError("S3 backend requires WALLETTASER_S3_BUCKET")
        prefix = kwargs.pop("prefix", os.getenv("WALLETTASER_S3_PREFIX", ""))
        metadata_path = kwargs.pop("metadata_path", os.getenv("WALLETTASER_METADATA_PATH", "s3_metadata.db"))
        return S3Storage(bucket=bucket, prefix=prefix, metadata_path=metadata_path, retention_policy=retention)

    raise StorageError(f"Unsupported storage backend: {backend}")

