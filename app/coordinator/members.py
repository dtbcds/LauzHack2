"""Issue per-member secrets for uploading Calendar events to the coordinator."""

from __future__ import annotations

import argparse
from pathlib import Path

from app.coordinator.storage import SubmissionStore


def main() -> None:
    parser = argparse.ArgumentParser(description="Add or rotate a coordinator member")
    parser.add_argument("project_id")
    parser.add_argument("member_id")
    parser.add_argument("--database", type=Path, default=Path("data/coordinator.sqlite3"))
    args = parser.parse_args()
    secret = SubmissionStore(args.database).register_member(args.project_id, args.member_id)
    print(f"Member: {args.member_id} (project: {args.project_id})")
    print(f"Upload secret (shown once): {secret}")


if __name__ == "__main__":
    main()
