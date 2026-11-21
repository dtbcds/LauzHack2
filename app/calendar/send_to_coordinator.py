"""Fetch one member's Calendar events and upload them to the coordinator."""

from __future__ import annotations

import argparse
import getpass
import json
import ssl
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


def send_calendar_snapshot(
    *, project_id: str, collection_id: str, member_id: str,
    coordinator_url: str, secret: str, credentials_path: str | Path = "credentials.json",
    calendar_id: str = "primary", days_ahead: int = 14,
    ca_cert: str | Path | None = None,
) -> dict[str, Any]:
    """Collect this member's upcoming events and upload a complete snapshot."""
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

    now = datetime.now(timezone.utc)
    service = connect_calendar(credentials_path, token_path_for_member(member_id))
    events = fetch_events(
        service, calendar_id=calendar_id, time_min=now,
        time_max=now + timedelta(days=days_ahead),
    )
    payload = {
        "project_id": project_id,
        "collection_id": collection_id,
        "member_id": member_id,
        "events": [
            prepare_event(event, member_id=member_id, calendar_id=calendar_id)
            for event in events
        ],
    }
    return post_submission(payload, coordinator_url=coordinator_url, secret=secret, ca_cert=ca_cert)


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
    args = parser.parse_args()

    try:
        secret = getpass.getpass("Your member upload secret: ")
        receipt = send_calendar_snapshot(
            project_id=args.project_id, collection_id=args.collection_id,
            member_id=args.member_id, coordinator_url=args.coordinator_url,
            secret=secret, credentials_path=args.credentials,
            calendar_id=args.calendar_id, days_ahead=args.days_ahead,
            ca_cert=args.ca_cert,
        )
    except HTTPError as exc:
        parser.exit(1, f"Coordinator rejected the upload (HTTP {exc.code}). Check your member secret and project/member IDs.\n")
    except (URLError, OSError, ValueError, RuntimeError) as exc:
        parser.exit(1, f"Upload failed: {exc}\n")
    print(f"Coordinator received {receipt['event_count']} events for {receipt['member_id']}.")


if __name__ == "__main__":
    main()
