"""SQLite storage for employee Calendar submissions on the coordinator."""

from __future__ import annotations

import json
import os
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

    def list_for_collection(self, project_id: str, collection_id: str) -> list[dict[str, Any]]:
        """Return the latest submission from each member in this collection."""
        with self._connect() as database:
            rows = database.execute("""
                SELECT payload_json FROM submissions
                WHERE project_id = ? AND collection_id = ?
                ORDER BY member_id
            """, (project_id, collection_id)).fetchall()
        return [json.loads(row[0]) for row in rows]
