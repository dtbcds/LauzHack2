"""SQLite storage for employee Calendar submissions on the coordinator."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator


class SubmissionStore:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        if self.path.is_symlink():
            raise ValueError("SQLite database path must not be a symbolic link")
        flags = os.O_CREAT | os.O_RDWR
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        descriptor = os.open(self.path, flags, 0o600)
        os.close(descriptor)
        if os.name == "posix":
            self.path.chmod(0o600)
            if self.path.parent == Path("data"):
                self.path.parent.chmod(0o700)

        with self._connect() as database:
            database.execute("""
                CREATE TABLE IF NOT EXISTS submissions (
                    project_id TEXT NOT NULL,
                    collection_id TEXT NOT NULL,
                    member_id TEXT NOT NULL,
                    received_at TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    PRIMARY KEY (project_id, collection_id, member_id)
                )
            """)
            database.execute("""
                CREATE TABLE IF NOT EXISTS member_secrets (
                    project_id TEXT NOT NULL,
                    member_id TEXT NOT NULL,
                    secret_hash TEXT NOT NULL,
                    PRIMARY KEY (project_id, member_id)
                )
            """)
            database.execute("""
                CREATE TABLE IF NOT EXISTS analyses (
                    project_id TEXT NOT NULL,
                    collection_id TEXT NOT NULL,
                    revision INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    result_json TEXT,
                    error TEXT,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (project_id, collection_id)
                )
            """)
            database.execute("""
                INSERT OR IGNORE INTO analyses
                    (project_id, collection_id, revision, status, updated_at)
                SELECT project_id, collection_id, 1, 'pending', ?
                FROM submissions GROUP BY project_id, collection_id
            """, (datetime.now(timezone.utc).isoformat(),))

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        database = sqlite3.connect(self.path, timeout=5)
        try:
            yield database
            database.commit()
        except Exception:
            database.rollback()
            raise
        finally:
            database.close()

    def save(self, payload: dict[str, Any]) -> int:
        """Persist a member snapshot and mark its collection for full analysis."""
        received_at = datetime.now(timezone.utc).isoformat()
        with self._connect() as database:
            database.execute("""
                INSERT INTO submissions
                    (project_id, collection_id, member_id, received_at, payload_json)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(project_id, collection_id, member_id) DO UPDATE SET
                    received_at = excluded.received_at,
                    payload_json = excluded.payload_json
            """, (
                payload["project_id"], payload["collection_id"], payload["member_id"],
                received_at, json.dumps(payload, ensure_ascii=False),
            ))
            database.execute("""
                INSERT INTO analyses
                    (project_id, collection_id, revision, status, updated_at)
                VALUES (?, ?, 1, 'pending', ?)
                ON CONFLICT(project_id, collection_id) DO UPDATE SET
                    revision = revision + 1,
                    status = 'pending',
                    error = NULL,
                    updated_at = excluded.updated_at
            """, (payload["project_id"], payload["collection_id"], received_at))
            revision = database.execute("""
                SELECT revision FROM analyses WHERE project_id = ? AND collection_id = ?
            """, (payload["project_id"], payload["collection_id"])).fetchone()[0]
        return revision

    def pending_analyses(self) -> list[tuple[str, str, int]]:
        """Return unfinished jobs, including jobs interrupted by a restart."""
        with self._connect() as database:
            rows = database.execute("""
                SELECT project_id, collection_id, revision FROM analyses
                WHERE status IN ('pending', 'processing')
            """).fetchall()
        return [(project_id, collection_id, revision) for project_id, collection_id, revision in rows]

    def mark_analysis_processing(self, project_id: str, collection_id: str, revision: int) -> bool:
        with self._connect() as database:
            changed = database.execute("""
                UPDATE analyses SET status = 'processing', updated_at = ?
                WHERE project_id = ? AND collection_id = ? AND revision = ?
                  AND status IN ('pending', 'processing')
            """, (datetime.now(timezone.utc).isoformat(), project_id, collection_id, revision))
        return changed.rowcount == 1

    def finish_analysis(
        self, project_id: str, collection_id: str, revision: int,
        *, result: dict[str, Any] | None = None, error: str | None = None,
    ) -> bool:
        """Save a result only if no newer submission superseded this run."""
        if (result is None) == (error is None):
            raise ValueError("Provide exactly one of result or error")
        with self._connect() as database:
            changed = database.execute("""
                UPDATE analyses SET status = ?, result_json = COALESCE(?, result_json),
                    error = ?, updated_at = ?
                WHERE project_id = ? AND collection_id = ? AND revision = ?
            """, (
                "ready" if error is None else "failed",
                json.dumps(result, ensure_ascii=False) if result is not None else None,
                error, datetime.now(timezone.utc).isoformat(),
                project_id, collection_id, revision,
            ))
        return changed.rowcount == 1

    def get_analysis(self, project_id: str, collection_id: str) -> dict[str, Any] | None:
        with self._connect() as database:
            row = database.execute("""
                SELECT revision, status, result_json, error, updated_at FROM analyses
                WHERE project_id = ? AND collection_id = ?
            """, (project_id, collection_id)).fetchone()
        if row is None:
            return None
        revision, status, result_json, error, updated_at = row
        return {
            "project_id": project_id,
            "collection_id": collection_id,
            "revision": revision,
            "status": status,
            "result": json.loads(result_json) if result_json else None,
            "error": error,
            "updated_at": updated_at,
        }

    def register_member(self, project_id: str, member_id: str) -> str:
        """Create or rotate one member's upload secret; return it only once."""
        if not project_id.strip() or not member_id.strip():
            raise ValueError("project_id and member_id must be non-empty")
        secret = secrets.token_urlsafe(32)
        secret_hash = hashlib.sha256(secret.encode("ascii")).hexdigest()
        with self._connect() as database:
            database.execute("""
                INSERT INTO member_secrets (project_id, member_id, secret_hash)
                VALUES (?, ?, ?)
                ON CONFLICT(project_id, member_id) DO UPDATE SET
                    secret_hash = excluded.secret_hash
            """, (project_id, member_id, secret_hash))
        return secret

    def is_authorized(self, project_id: str, member_id: str, secret: str) -> bool:
        """Check a member's upload secret without storing the secret itself."""
        with self._connect() as database:
            row = database.execute("""
                SELECT secret_hash FROM member_secrets
                WHERE project_id = ? AND member_id = ?
            """, (project_id, member_id)).fetchone()
        provided_hash = hashlib.sha256(secret.encode("utf-8")).hexdigest()
        expected_hash = row[0] if row else "0" * 64
        return hmac.compare_digest(provided_hash, expected_hash) and row is not None

    def list_for_collection(self, project_id: str, collection_id: str) -> list[dict[str, Any]]:
        """Return the latest submission from each member in this collection."""
        with self._connect() as database:
            rows = database.execute("""
                SELECT payload_json FROM submissions
                WHERE project_id = ? AND collection_id = ?
                ORDER BY member_id
            """, (project_id, collection_id)).fetchall()
        return [json.loads(row[0]) for row in rows]
