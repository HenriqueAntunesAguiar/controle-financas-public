"""Adaptador SQLite para registro local e historico de versoes."""

from __future__ import annotations

import sqlite3
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from fastapi_app.application.ports import RepositoryConflict
from fastapi_app.domain import ConnectionStatus


SCHEMA = """
PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS invoices (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    filename TEXT NOT NULL,
    pdf_path TEXT NOT NULL,
    reference_date TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'received',
    current_version INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    error_code TEXT
);
CREATE TABLE IF NOT EXISTS invoice_versions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    invoice_id TEXT NOT NULL REFERENCES invoices(id) ON DELETE CASCADE,
    version_number INTEGER NOT NULL,
    json_path TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    transaction_count INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'ready',
    postgres_version_id INTEGER,
    created_at TEXT NOT NULL,
    imported_at TEXT,
    UNIQUE(invoice_id, version_number)
);
CREATE INDEX IF NOT EXISTS invoice_versions_invoice_idx
    ON invoice_versions(invoice_id, version_number DESC);
"""


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class SQLiteInvoiceRepository:
    component = "sqlite_registry"

    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.session() as connection:
            connection.executescript(SCHEMA)
            columns = {
                row["name"]
                for row in connection.execute("PRAGMA table_info(invoices)").fetchall()
            }
            if "name" not in columns:
                connection.execute("ALTER TABLE invoices ADD COLUMN name TEXT")
                connection.execute(
                    "UPDATE invoices SET name=filename WHERE name IS NULL OR name=''"
                )
            connection.execute(
                "UPDATE invoices SET status='error', error_code='interrupted' "
                "WHERE status='processing'"
            )

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=10000")
        return connection

    @contextmanager
    def session(self) -> Iterator[sqlite3.Connection]:
        connection = self.connect()
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def create(self, invoice_id: str, name: str, filename: str, pdf_path: str, reference_date: str) -> None:
        timestamp = now_iso()
        with self.session() as connection:
            connection.execute(
                """
                INSERT INTO invoices(
                    id, name, filename, pdf_path, reference_date, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    invoice_id,
                    name,
                    filename,
                    pdf_path,
                    reference_date,
                    timestamp,
                    timestamp,
                ),
            )

    def list_all(self) -> list[dict[str, Any]]:
        with self.session() as connection:
            invoices = [
                dict(row)
                for row in connection.execute(
                    """
                    SELECT i.*, COALESCE(v.transaction_count, 0) transaction_count,
                           v.status version_status
                    FROM invoices i
                    LEFT JOIN invoice_versions v
                      ON v.invoice_id=i.id AND v.version_number=i.current_version
                    ORDER BY i.created_at DESC
                    """
                ).fetchall()
            ]
            for invoice in invoices:
                invoice["versions"] = [
                    dict(row)
                    for row in connection.execute(
                        """
                        SELECT version_number, transaction_count, status,
                               postgres_version_id, created_at, imported_at
                        FROM invoice_versions WHERE invoice_id=?
                        ORDER BY version_number DESC
                        """,
                        (invoice["id"],),
                    ).fetchall()
                ]
            return invoices

    def stats(self) -> dict[str, int]:
        with self.session() as connection:
            row = connection.execute(
                """
                SELECT COUNT(*) total,
                  SUM(CASE WHEN status='received' THEN 1 ELSE 0 END) received,
                  SUM(CASE WHEN status='ready' THEN 1 ELSE 0 END) ready,
                  SUM(CASE WHEN status='needs_review' THEN 1 ELSE 0 END) needs_review,
                  SUM(CASE WHEN status='imported' THEN 1 ELSE 0 END) imported
                FROM invoices
                """
            ).fetchone()
            return {key: int(row[key] or 0) for key in row.keys()}

    def begin_processing(self, invoice_id: str) -> dict[str, Any]:
        connection = self.connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM invoices WHERE id=?", (invoice_id,)
            ).fetchone()
            if row is None:
                raise RepositoryConflict("invoice_not_found")
            if row["status"] == "processing":
                raise RepositoryConflict("invoice_busy")
            version_number = int(row["current_version"]) + 1
            connection.execute(
                "UPDATE invoices SET status='processing', error_code=NULL, "
                "updated_at=? WHERE id=?",
                (now_iso(), invoice_id),
            )
            connection.commit()
            return {**dict(row), "version_number": version_number}
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def finish_processing(self, invoice_id: str, version_number: int, json_path: str, content_hash: str, transaction_count: int, status: str) -> None:
        timestamp = now_iso()
        with self.session() as connection:
            connection.execute(
                """
                INSERT INTO invoice_versions(
                    invoice_id, version_number, json_path, content_hash,
                    transaction_count, status, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    invoice_id,
                    version_number,
                    json_path,
                    content_hash,
                    transaction_count,
                    status,
                    timestamp,
                ),
            )
            connection.execute(
                "UPDATE invoices SET status=?, current_version=?, "
                "updated_at=?, error_code=NULL WHERE id=?",
                (status, version_number, timestamp, invoice_id),
            )

    def fail_processing(self, invoice_id: str) -> None:
        with self.session() as connection:
            connection.execute(
                "UPDATE invoices SET status='error', error_code='parse_failed', "
                "updated_at=? WHERE id=?",
                (now_iso(), invoice_id),
            )

    def latest_version(self, invoice_id: str) -> dict[str, Any] | None:
        with self.session() as connection:
            row = connection.execute(
                "SELECT v.*, i.name invoice_name FROM invoice_versions v "
                "JOIN invoices i ON i.id=v.invoice_id WHERE v.invoice_id=? "
                "ORDER BY v.version_number DESC LIMIT 1",
                (invoice_id,),
            ).fetchone()
            return dict(row) if row else None

    def approve_latest(self, invoice_id: str) -> None:
        timestamp = now_iso()
        with self.session() as connection:
            row = connection.execute(
                "SELECT version_number, status FROM invoice_versions "
                "WHERE invoice_id=? ORDER BY version_number DESC LIMIT 1",
                (invoice_id,),
            ).fetchone()
            if row is None or row["status"] != "needs_review":
                raise RepositoryConflict("review_not_pending")
            connection.execute(
                "UPDATE invoice_versions SET status='ready' "
                "WHERE invoice_id=? AND version_number=?",
                (invoice_id, row["version_number"]),
            )
            connection.execute(
                "UPDATE invoices SET status='ready', updated_at=?, error_code=NULL "
                "WHERE id=?",
                (timestamp, invoice_id),
            )

    def mark_imported(self, invoice_id: str, version_number: int, postgres_version_id: int) -> None:
        timestamp = now_iso()
        with self.session() as connection:
            connection.execute(
                "UPDATE invoice_versions SET status='imported', "
                "postgres_version_id=?, imported_at=? "
                "WHERE invoice_id=? AND version_number=?",
                (postgres_version_id, timestamp, invoice_id, version_number),
            )
            connection.execute(
                "UPDATE invoices SET status='imported', updated_at=?, "
                "error_code=NULL WHERE id=?",
                (timestamp, invoice_id),
            )

    def mark_import_failed(self, invoice_id: str) -> None:
        with self.session() as connection:
            connection.execute(
                "UPDATE invoices SET error_code='postgres_unavailable', "
                "updated_at=? WHERE id=?",
                (now_iso(), invoice_id),
            )

    def probe(self) -> ConnectionStatus:
        started = time.perf_counter()
        try:
            with self.session() as connection:
                connection.execute("SELECT 1").fetchone()
            status, detail = "ok", "query_ok"
        except Exception:
            status, detail = "error", "query_failed"
        return ConnectionStatus(
            self.component, status, round((time.perf_counter() - started) * 1000, 2), detail
        )
