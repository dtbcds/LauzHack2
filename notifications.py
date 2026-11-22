"""Send high-impact bottleneck alerts on Windows and macOS."""

import json
import logging
import os
import platform
import subprocess
import tempfile
import hashlib
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path


TITLE = "High-impact task is blocking work"
COOLDOWN = timedelta(hours=4)
LOGGER = logging.getLogger(__name__)
_STATE_LOCK = threading.Lock()


def _state_path() -> Path:
    if platform.system() == "Darwin":
        root = Path.home() / "Library" / "Application Support"
    else:
        root = Path(os.environ.get("LOCALAPPDATA") or Path.home())
    return root / "DependencyIntelligence" / "notification_timestamps.json"


def _load_timestamps(path: Path) -> dict[str, datetime]:
    try:
        saved = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(saved, dict):
            raise ValueError("Notification state must be an object")
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as exc:
        LOGGER.warning("Cannot read notification state: %s", exc)
        return {}

    timestamps = {}
    for task_id, value in saved.items():
        try:
            timestamp = datetime.fromisoformat(value)
            if timestamp.tzinfo is not None:
                timestamps[task_id] = timestamp.astimezone(timezone.utc)
        except (TypeError, ValueError):
            continue
    return timestamps


def _save_timestamps(path: Path, timestamps: dict[str, datetime]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent, prefix="notifications-",
            suffix=".tmp", delete=False,
        ) as file:
            temporary = Path(file.name)
            json.dump({key: value.isoformat() for key, value in timestamps.items()}, file)
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def send_notification(task: dict, *, notification_title: str | None = None) -> bool:
    """Submit one native desktop notification on Windows or macOS."""
    system = platform.system()
    if system not in ("Windows", "Darwin"):
        LOGGER.warning("Desktop notifications are unavailable on %s", system)
        return False

    owner = task.get("owner")
    if not isinstance(owner, str) or not owner.strip() or owner.strip().lower() == "unknown":
        owner = "Unknown"
    deadline = task.get("deadline") or "Unknown"
    message = "\n".join([
        str(task.get("title") or task.get("task_id") or "Untitled task"),
        f"Owner: {owner}",
        f"Deadline: {deadline}",
        f"Downstream tasks: {task.get('downstream_count', 0)}",
        f"Affected coworkers: {task.get('affected_people', 0)}",
    ])
    unknown = task.get("status") is None or str(task.get("status", "")).strip().lower() in ("", "unknown")
    title = notification_title or ("Potential bottleneck needs attention" if unknown else TITLE)
    if unknown:
        message += "\nCompletion status: unknown"
    try:
        if system == "Windows":
            from winotify import Notification

            Notification(app_id="Relay", title=title, msg=message).show()
        else:
            subprocess.run(
                ["osascript", "-e", "on run argv", "-e",
                 "display notification (item 2 of argv) with title (item 1 of argv)",
                 "-e", "end run", title, message],
                check=True, capture_output=True, text=True, timeout=10,
            )
        return True
    except Exception:
        LOGGER.exception("Could not send notification for task %r", task.get("task_id"))
        return False


def qualifying_bottlenecks(bottlenecks: list[dict]) -> list[dict]:
    """Apply the same alert thresholds to native notifications and the UI banner."""
    eligible = []
    for task in bottlenecks:
        status = task.get("status", "pending")
        status = status.strip().lower() if isinstance(status, str) else "unknown"
        if status not in {"pending", "unknown", "", "open", "needsaction", "in_progress"}:
            continue
        priority, downstream, people = (task.get("priority_score"), task.get("downstream_count"), task.get("affected_people"))
        if (not isinstance(task.get("task_id"), str) or not task["task_id"]
                or isinstance(priority, bool) or not isinstance(priority, (int, float)) or priority < 75
                or not isinstance(downstream, int) or not isinstance(people, int)
                or (downstream < 3 and people < 2)):
            continue
        eligible.append(task)
    return eligible


def snapshot_bottlenecks(snapshot: dict) -> list[dict]:
    """Adapt graph_to_ui_data nodes to notification records without model calls."""
    return [{
        "task_id": node["id"], "title": node["title"], "owner": node.get("owner_display") or node.get("owner"),
        "deadline": node.get("deadline"), "status": node.get("status"),
        "priority_score": node["priority"]["priority_score"],
        "downstream_count": node["impact"]["downstream_count"],
        "affected_people": node["impact"]["affected_people"],
    } for node in snapshot.get("nodes", []) if node.get("is_bottleneck")]


def run_snapshot_check(snapshot: dict, *, scope: str, state_path: Path | None = None,
                       now: datetime | None = None) -> list[str]:
    return run_bottleneck_check(snapshot_bottlenecks(snapshot), scope=scope, state_path=state_path, now=now)


def run_bottleneck_check(
    bottlenecks: list[dict], *, state_path: Path | None = None, now: datetime | None = None,
    scope: str = "",
) -> list[str]:
    with _STATE_LOCK:
        return _run_bottleneck_check(bottlenecks, state_path=state_path, now=now, scope=scope)


def _run_bottleneck_check(
    bottlenecks: list[dict], *, state_path: Path | None, now: datetime | None, scope: str,
) -> list[str]:
    """Notify qualifying bottlenecks and persist each successful send time."""
    path = state_path or _state_path()
    current = now or datetime.now(timezone.utc)
    timestamps = _load_timestamps(path)
    sent = []

    for task in qualifying_bottlenecks(bottlenecks):
        task_id = task["task_id"]
        state_key = hashlib.sha256(scope.encode()).hexdigest() + ":" + task_id if scope else task_id
        last_sent = timestamps.get(state_key)
        if last_sent is not None and current - last_sent < COOLDOWN:
            continue
        if send_notification(task):
            timestamps[state_key] = current
            sent.append(task_id)
            try:
                _save_timestamps(path, timestamps)
            except OSError:
                LOGGER.exception("Could not persist notification time for task %r", task_id)

    return sent


def main(argv=None) -> int:
    import argparse
    parser = argparse.ArgumentParser(description="Test Relay desktop notification delivery")
    parser.add_argument("--test", action="store_true", help="Submit one test notification without analysis or cooldown")
    args = parser.parse_args(argv)
    if not args.test:
        parser.error("Use --test to submit a test notification")
    submitted = send_notification({
        "task_id": "notification-test", "title": "Relay desktop notification test",
        "owner": "Test", "status": "pending", "downstream_count": 0, "affected_people": 0,
    }, notification_title="Relay notification test")
    print("Notification submitted. If no pop-up appears, check OS notification permissions and Focus/Do Not Disturb."
          if submitted else "Notification submission failed; see the error above.")
    return 0 if submitted else 1


if __name__ == "__main__":
    raise SystemExit(main())
