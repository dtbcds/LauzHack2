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

    def save(self, payload: dict[str, Any]) -> None:
        """Persist one member's full snapshot; retrying replaces the old one."""
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
