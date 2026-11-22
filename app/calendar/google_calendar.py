"""Read events from a Google Calendar with desktop OAuth."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import tempfile
from dataclasses import dataclass
from html import unescape
from urllib.parse import unquote
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

SCOPES = [
    "https://www.googleapis.com/auth/calendar.readonly",
    "https://www.googleapis.com/auth/tasks.readonly",
]


@dataclass
class CalendarServices:
    calendar: Any
    tasks: Any

    def events(self):
        return self.calendar.events()


def linked_task_id(description: str) -> str | None:
    match = re.search(r"https://tasks\.google\.com/task/([A-Za-z0-9_%=-]+)", unescape(description))
    return unquote(match.group(1)) if match else None


def fill_task_descriptions(events: list[dict[str, Any]], service: Any) -> list[dict[str, Any]]:
    """Resolve task links by exact web link/ID, never by a potentially duplicate title."""
    linked = {event["id"]: linked_task_id(event.get("description") or "") for event in events}
    if not any(linked.values()):
        return events
    tasks_by_link = {}
    page = None
    while True:
        lists = service.tasklists().list(maxResults=100, pageToken=page).execute()
        for tasklist in lists.get("items", []):
            task_page = None
            while True:
                result = service.tasks().list(
                    tasklist=tasklist["id"], maxResults=100, pageToken=task_page,
                    showCompleted=True, showHidden=True, showDeleted=False,
                ).execute()
                for task in result.get("items", []):
                    if task.get("deleted"):
                        continue
                    tasks_by_link[task["id"]] = task
                    web_id = linked_task_id(task.get("webViewLink") or "")
                    if web_id:
                        tasks_by_link[web_id] = task
                task_page = result.get("nextPageToken")
                if not task_page:
                    break
        page = lists.get("nextPageToken")
        if not page:
            break
    enriched = []
    for event in events:
        task_id = linked[event["id"]]
        if task_id:
            task = tasks_by_link.get(task_id)
            if task is None:
                raise RuntimeError(
                    f"Could not match Google Tasks link for {event.get('summary', event['id'])!r}. "
                    "Check that the authorized Google account owns the task."
                )
            event = {**event, "description": task.get("notes") or ""}
        enriched.append(event)
    return enriched


def token_path_for_member(member_id: str | None) -> Path:
    """Keep each member's Google authorization separate from other members'."""
    if member_id is None:
        return Path("token.json")
    if not member_id.strip():
        raise ValueError("member_id must not be empty")
    token_name = hashlib.sha256(member_id.encode("utf-8")).hexdigest() + ".json"
    return Path("tokens") / token_name


def _save_token(token_path: Path, token_json: str) -> None:
    """Atomically save an OAuth token with private local file permissions."""
    token_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if os.name == "posix" and token_path.parent == Path("tokens"):
        token_path.parent.chmod(0o700)

    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=token_path.parent,
            prefix=".token-", delete=False,
        ) as temporary_file:
            temporary_path = Path(temporary_file.name)
            temporary_file.write(token_json)
        os.replace(temporary_path, token_path)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def connect_calendar(
    credentials_path: str | Path = "credentials.json",
    token_path: str | Path = "token.json",
) -> Any:
    """Authorize once in a browser, then reuse or refresh the saved token."""
    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
        from googleapiclient.discovery import build
    except ImportError as exc:
        raise RuntimeError("Install Calendar dependencies: pip install -r requirements.txt") from exc

    credentials_path = Path(credentials_path)
    token_path = Path(token_path)
    if not credentials_path.is_file():
        raise FileNotFoundError(
            f"OAuth desktop credentials missing: {credentials_path}. "
            "Download them from Google Cloud and keep them out of Git."
        )

    credentials = None
    if token_path.is_file():
        if token_path.is_symlink():
            raise ValueError("OAuth token path must not be a symbolic link")
        if os.name == "posix":
            token_path.chmod(0o600)
        # Read the actual saved scopes, rather than labelling an old token with new ones.
        credentials = Credentials.from_authorized_user_file(str(token_path))
        if not credentials.has_scopes(SCOPES):
            credentials = None
    if not credentials or not credentials.valid:
        if credentials and credentials.expired and credentials.refresh_token:
            credentials.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(str(credentials_path), SCOPES)
            credentials = flow.run_local_server(port=0, prompt="consent")
        _save_token(token_path, credentials.to_json())

    return CalendarServices(
        build("calendar", "v3", credentials=credentials),
        build("tasks", "v1", credentials=credentials),
    )


def fetch_events(
    service: Any,
    *,
    calendar_id: str = "primary",
    time_min: datetime,
    time_max: datetime,
    page_size: int = 250,
) -> list[dict[str, Any]]:
    """Fetch all non-cancelled event pages, including descriptions and people."""
    if time_min.tzinfo is None or time_max.tzinfo is None:
        raise ValueError("time_min and time_max must include a timezone")
    if time_max <= time_min:
        raise ValueError("time_max must be after time_min")

    events: list[dict[str, Any]] = []
    page_token = None
    while True:
        result = service.events().list(
            calendarId=calendar_id,
            timeMin=time_min.isoformat(),
            timeMax=time_max.isoformat(),
            maxResults=page_size,
            singleEvents=True,
            orderBy="startTime",
            pageToken=page_token,
        ).execute()
        events.extend(event for event in result.get("items", []) if event.get("status") != "cancelled")
        page_token = result.get("nextPageToken")
        if not page_token:
            if isinstance(service, CalendarServices):
                return fill_task_descriptions(events, service.tasks)
            return events


def prepare_event(
    event: dict[str, Any], *, member_id: str | None = None, calendar_id: str = "primary"
) -> dict[str, Any]:
    """Keep the Calendar fields needed for downstream task extraction."""
    if not event.get("id"):
        raise ValueError("Calendar event is missing its ID")
    return {
        "id": event["id"],
        "member_id": member_id,
        "calendar_id": calendar_id,
        "summary": event.get("summary") or "",
        "description": event.get("description") or "",
        "start": event.get("start") or {},
        "end": event.get("end") or {},
        "organizer": event.get("organizer") or {},
        "attendees": event.get("attendees") or [],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch Calendar events as JSON")
    parser.add_argument("--credentials", default="credentials.json")
    parser.add_argument("--token", type=Path, help="Custom token path for single-user mode")
    parser.add_argument("--member-id", help="Stable group member ID; uses a separate OAuth token")
    parser.add_argument("--calendar-id", default="primary")
    parser.add_argument("--days-ahead", type=int, default=14)
    parser.add_argument("--output", type=Path, help="Write JSON to this file; default is stdout")
    args = parser.parse_args()
    if args.days_ahead < 1:
        parser.error("--days-ahead must be positive")
    if args.member_id is not None and args.token is not None:
        parser.error("Use --member-id or --token, not both")
    try:
        token_path = args.token or token_path_for_member(args.member_id)
    except ValueError as exc:
        parser.error(str(exc))

    now = datetime.now(timezone.utc)
    service = connect_calendar(args.credentials, token_path)
    events = fetch_events(
        service,
        calendar_id=args.calendar_id,
        time_min=now,
        time_max=now + timedelta(days=args.days_ahead),
    )
    output = json.dumps(
        {"events": [
            prepare_event(event, member_id=args.member_id, calendar_id=args.calendar_id)
            for event in events
        ]},
        ensure_ascii=False,
        indent=2,
    )
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(output + "\n", encoding="utf-8")
    else:
        print(output)


if __name__ == "__main__":
    main()
