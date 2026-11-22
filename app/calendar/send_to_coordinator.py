"""Fetch one member's Calendar events and upload them to the coordinator."""

from __future__ import annotations

import argparse
import getpass
import hashlib
import json
import random
import ssl
import sys
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from app.calendar.google_calendar import (
    connect_calendar,
    fetch_events,
    prepare_event,
    token_path_for_member,
)


def submission_endpoint(coordinator_url: str) -> str:
    """Accept an HTTPS coordinator, or HTTP on this computer for local tests."""
    parts = urlsplit(coordinator_url)
    if (not parts.hostname or parts.username or parts.password
            or parts.path not in ("", "/") or parts.query or parts.fragment):
        raise ValueError("coordinator URL must be only a server address, such as https://192.168.1.42:8000")
    if parts.scheme == "http" and parts.hostname not in ("127.0.0.1", "localhost"):
        raise ValueError("remote coordinator uploads require HTTPS")
    if parts.scheme not in ("http", "https"):
        raise ValueError("coordinator URL must start with https:// (or local http://)")
    return coordinator_url.rstrip("/") + "/submissions"


def post_submission(
    payload: dict[str, Any], *, coordinator_url: str, secret: str,
    ca_cert: str | Path | None = None,
) -> dict[str, Any]:
    """Send prepared event JSON, keeping Google OAuth tokens on this computer."""
    if not secret:
        raise ValueError("upload secret must not be empty")
    endpoint = submission_endpoint(coordinator_url)
    request = Request(
        endpoint,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {secret}",
        },
        method="POST",
    )
    if endpoint.startswith("https://"):
        context = ssl.create_default_context(cafile=str(ca_cert) if ca_cert else None)
        response = urlopen(request, context=context, timeout=20)
    else:
        response = urlopen(request, timeout=20)
    with response:
        receipt = json.load(response)
    if (not isinstance(receipt, dict) or receipt.get("received") is not True
            or receipt.get("project_id") != payload["project_id"]
            or receipt.get("collection_id") != payload["collection_id"]
            or receipt.get("member_id") != payload["member_id"]
            or receipt.get("event_count") != len(payload["events"])):
        raise ValueError("coordinator did not confirm the upload")
    return receipt


class CalendarSnapshotSync:
    """Reuse one Calendar login and send only snapshots that have changed."""

    def __init__(
        self, *, project_id: str, collection_id: str, member_id: str,
        coordinator_url: str, secret: str, credentials_path: str | Path = "credentials.json",
        calendar_id: str = "primary", days_ahead: int = 14,
        ca_cert: str | Path | None = None, service: Any | None = None,
    ):
        if not project_id.strip() or not collection_id.strip() or not member_id.strip():
            raise ValueError("project_id, collection_id, and member_id must be non-empty")
        if days_ahead < 1:
            raise ValueError("days_ahead must be positive")
        if not secret:
            raise ValueError("upload secret must not be empty")
        endpoint = submission_endpoint(coordinator_url)
        if endpoint.startswith("http://") and ca_cert is not None:
            raise ValueError("--ca-cert is only used with HTTPS")
        if endpoint.startswith("https://") and ca_cert is not None and not Path(ca_cert).is_file():
            raise FileNotFoundError(f"coordinator certificate missing: {ca_cert}")

        self.project_id = project_id
        self.collection_id = collection_id
        self.member_id = member_id
        self.coordinator_url = coordinator_url
        self.secret = secret
        self.calendar_id = calendar_id
        self.days_ahead = days_ahead
        self.ca_cert = ca_cert
        self.service = service if service is not None else connect_calendar(
            credentials_path, token_path_for_member(member_id)
        )
        self._last_uploaded_hash: bytes | None = None

    def sync_once(self) -> dict[str, Any] | None:
        """Upload on first check or after an add, edit, or deletion."""
        now = datetime.now(timezone.utc)
        events = fetch_events(
            self.service, calendar_id=self.calendar_id, time_min=now,
            time_max=now + timedelta(days=self.days_ahead),
        )
        prepared = [
            prepare_event(event, member_id=self.member_id, calendar_id=self.calendar_id)
            for event in events
        ]
        canonical = json.dumps(
            sorted(prepared, key=lambda event: event["id"]),
            ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        ).encode("utf-8")
        snapshot_hash = hashlib.sha256(canonical).digest()
        if snapshot_hash == self._last_uploaded_hash:
            return None

        payload = {
            "project_id": self.project_id,
            "collection_id": self.collection_id,
            "member_id": self.member_id,
            "events": prepared,
        }
        receipt = post_submission(
            payload, coordinator_url=self.coordinator_url,
            secret=self.secret, ca_cert=self.ca_cert,
        )
        self._last_uploaded_hash = snapshot_hash
        return receipt


def send_calendar_snapshot(
    *, project_id: str, collection_id: str, member_id: str,
    coordinator_url: str, secret: str, credentials_path: str | Path = "credentials.json",
    calendar_id: str = "primary", days_ahead: int = 14,
    ca_cert: str | Path | None = None,
) -> dict[str, Any]:
    """Collect and upload one full snapshot, preserving the existing CLI behavior."""
    sync = CalendarSnapshotSync(
        project_id=project_id, collection_id=collection_id, member_id=member_id,
        coordinator_url=coordinator_url, secret=secret, credentials_path=credentials_path,
        calendar_id=calendar_id, days_ahead=days_ahead, ca_cert=ca_cert,
    )
    receipt = sync.sync_once()
    if receipt is None:
        raise RuntimeError("Initial Calendar snapshot was not uploaded")
    return receipt


def watch_calendar(
    sync: CalendarSnapshotSync, *, interval_seconds: int = 60,
    stop_event: threading.Event | None = None,
) -> None:
    """Keep checking while the client is open; retry transient failures."""
    if interval_seconds < 30:
        raise ValueError("watch interval must be at least 30 seconds")
    stop_event = stop_event or threading.Event()
    failures = 0
    while not stop_event.is_set():
        try:
            receipt = sync.sync_once()
            if receipt is not None:
                print(f"Synced {receipt['event_count']} events for {receipt['member_id']}.", flush=True)
            failures = 0
        except HTTPError as exc:
            if exc.code == 401:
                raise RuntimeError("Coordinator rejected the member secret; stop and check it") from exc
            failures += 1
            print(f"Sync failed (HTTP {exc.code}); will retry.", file=sys.stderr, flush=True)
        except Exception as exc:
            failures += 1
            print(f"Sync failed: {exc}; will retry.", file=sys.stderr, flush=True)

        delay = min(interval_seconds * 2 ** min(failures, 4), 15 * 60)
        stop_event.wait(max(30, delay * random.uniform(0.75, 1.25)))


def main() -> None:
    parser = argparse.ArgumentParser(description="Send your Calendar events to the coordinator")
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--collection-id", required=True)
    parser.add_argument("--member-id", required=True)
    parser.add_argument("--coordinator-url", required=True, help="Base URL, such as https://192.168.1.42:8000")
    parser.add_argument("--ca-cert", type=Path, help="Coordinator certificate for HTTPS verification")
    parser.add_argument("--credentials", type=Path, default=Path("credentials.json"))
    parser.add_argument("--calendar-id", default="primary")
    parser.add_argument("--days-ahead", type=int, default=14)
    parser.add_argument("--watch", action="store_true", help="Keep syncing while this command runs")
    parser.add_argument("--interval-seconds", type=int, default=60, help="Watch interval (minimum 30 seconds)")
    args = parser.parse_args()
    if args.watch and args.interval_seconds < 30:
        parser.error("--interval-seconds must be at least 30 with --watch")

    try:
        secret = getpass.getpass("Your member upload secret: ")
        sync = CalendarSnapshotSync(
            project_id=args.project_id, collection_id=args.collection_id,
            member_id=args.member_id, coordinator_url=args.coordinator_url,
            secret=secret, credentials_path=args.credentials,
            calendar_id=args.calendar_id, days_ahead=args.days_ahead,
            ca_cert=args.ca_cert,
        )
        if args.watch:
            print("Watching Calendar for changes. Press Ctrl+C to stop.", flush=True)
            watch_calendar(sync, interval_seconds=args.interval_seconds)
            return
        receipt = sync.sync_once()
        if receipt is None:
            raise RuntimeError("Initial Calendar snapshot was not uploaded")
    except KeyboardInterrupt:
        print("\nStopped watching.")
        return
    except HTTPError as exc:
        parser.exit(1, f"Coordinator rejected the upload (HTTP {exc.code}). Check your member secret and project/member IDs.\n")
    except (URLError, OSError, ValueError, RuntimeError) as exc:
        parser.exit(1, f"Upload failed: {exc}\n")
    print(f"Coordinator received {receipt['event_count']} events for {receipt['member_id']}.")


if __name__ == "__main__":
    main()
