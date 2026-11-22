"""Coordinator-local entry point for the desktop Refresh button."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.coordinator.storage import SubmissionStore


def request_collection_refresh(
    project_id: str, collection_id: str, *, database: str | Path = "data/coordinator.sqlite3",
) -> dict:
    """Request fresh Calendar snapshots and return the new progress state."""
    store = SubmissionStore(database)
    store.request_refresh(project_id, collection_id)
    return store.get_refresh_status(project_id, collection_id)


def main() -> None:
    parser = argparse.ArgumentParser(description="Request a Calendar refresh from all project members")
    parser.add_argument("project_id")
    parser.add_argument("collection_id")
    parser.add_argument("--database", type=Path, default=Path("data/coordinator.sqlite3"))
    parser.add_argument("--status", action="store_true", help="Show progress without requesting a new refresh")
    args = parser.parse_args()
    if args.status:
        result = SubmissionStore(args.database).get_refresh_status(args.project_id, args.collection_id)
    else:
        result = request_collection_refresh(args.project_id, args.collection_id, database=args.database)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
