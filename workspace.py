"""Durable reconciliation runs and reviewer decisions for a single workspace."""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path


class RunNotFound(Exception):
    pass


class ReviewConflict(Exception):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Workspace:
    def __init__(self, path: Path):
        self.path = path

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=15)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys = ON")
        try:
            with db:
                yield db
        finally:
            db.close()

    def initialize(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.execute("PRAGMA journal_mode = WAL")
            db.executescript("""
                CREATE TABLE IF NOT EXISTS runs (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    created_by TEXT NOT NULL,
                    fingerprint TEXT NOT NULL,
                    settings TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    result TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS runs_created_at ON runs (created_at DESC, id DESC);
                CREATE TABLE IF NOT EXISTS reviews (
                    run_id TEXT NOT NULL REFERENCES runs (id),
                    tx_id TEXT NOT NULL,
                    decision TEXT NOT NULL,
                    note TEXT NOT NULL,
                    actor TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    version INTEGER NOT NULL,
                    PRIMARY KEY (run_id, tx_id, version)
                );
            """)

    def list_runs(self, limit: int, offset: int) -> list[dict]:
        with self.connect() as db:
            rows = db.execute("""
                SELECT id, name, created_at, created_by, summary FROM runs
                ORDER BY created_at DESC, id DESC LIMIT ? OFFSET ?
            """, (limit, offset)).fetchall()
        return [{**dict(row), "summary": json.loads(row["summary"])} for row in rows]

    def _run(self, db, run_id: str) -> sqlite3.Row:
        row = db.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
        if row is None:
            raise RunNotFound(run_id)
        return row

    def _detail(self, db, row: sqlite3.Row) -> dict:
        reviews = db.execute("""
            SELECT tx_id, decision, note, actor, created_at, version FROM reviews
            WHERE run_id = ? ORDER BY rowid
        """, (row["id"],)).fetchall()
        history = [dict(review) for review in reviews]
        return {
            "id": row["id"],
            "name": row["name"],
            "created_at": row["created_at"],
            "created_by": row["created_by"],
            "settings": json.loads(row["settings"]),
            "result": json.loads(row["result"]),
            "reviews": {review["tx_id"]: review for review in history},
            "review_history": history,
        }

    def get_run(self, run_id: str) -> dict:
        with self.connect() as db:
            return self._detail(db, self._run(db, run_id))

    def find_submission(self, run_id: str, fingerprint: str) -> dict | None:
        with self.connect() as db:
            row = db.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
            if row is None:
                return None
            if row["fingerprint"] != fingerprint:
                raise ReviewConflict("This submission ID was already used for different inputs.")
            return self._detail(db, row)

    def save_run(self, run_id: str, name: str, actor: str, fingerprint: str, settings: dict, result: dict) -> dict:
        with self.connect() as db:
            db.execute("""
                INSERT INTO runs VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (id) DO NOTHING
            """, (run_id, name, _now(), actor, fingerprint, json.dumps(settings),
                  json.dumps(result["summary"]), json.dumps(result)))
            row = self._run(db, run_id)
            if row["fingerprint"] != fingerprint:
                raise ReviewConflict("This submission ID was already used for different inputs.")
            return self._detail(db, row)

    def review(self, run_id: str, tx_id: str, decision: str, note: str, version: int, actor: str) -> dict:
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = self._run(db, run_id)
            proposal = next((p for p in json.loads(row["result"])["proposals"] if p["tx_id"] == tx_id), None)
            if proposal is None:
                raise RunNotFound(tx_id)
            if decision == "approved" and proposal["status"] == "UNMATCHED_SUSPENSE":
                raise ReviewConflict("Unmatched transactions must be resolved in a new run before export.")
            if not note and (decision == "rejected" or proposal["status"] != "AUTO_RECONCILED"):
                raise ReviewConflict("Add a review note for this decision.")
            current = db.execute("""
                SELECT COALESCE(MAX(version), 0) FROM reviews WHERE run_id = ? AND tx_id = ?
            """, (run_id, tx_id)).fetchone()[0]
            if version != current:
                raise ReviewConflict("Another review was saved. Reload the run before changing the decision.")
            db.execute("INSERT INTO reviews VALUES (?, ?, ?, ?, ?, ?, ?)",
                       (run_id, tx_id, decision, note, actor, _now(), current + 1))
            return self._detail(db, row)
