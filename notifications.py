"""Send high-impact bottleneck alerts on Windows and macOS."""

import json
import logging
import os
import platform
import subprocess
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path


TITLE = "High-impact task is blocking work"
COOLDOWN = timedelta(hours=4)
LOGGER = logging.getLogger(__name__)


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


def send_notification(task: dict) -> bool:
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
    try:
        if system == "Windows":
            from winotify import Notification

            Notification(app_id="Dependency Intelligence", title=TITLE, msg=message).show()
        else:
            subprocess.run(
                ["osascript", "-e", "on run argv", "-e",
                 "display notification (item 2 of argv) with title (item 1 of argv)",
                 "-e", "end run", TITLE, message],
                check=True, capture_output=True, text=True, timeout=10,
            )
        return True
    except Exception:
        LOGGER.exception("Could not send notification for task %r", task.get("task_id"))
        return False


def run_bottleneck_check(
    bottlenecks: list[dict], *, state_path: Path | None = None, now: datetime | None = None,
) -> list[str]:
    """Notify qualifying bottlenecks and persist each successful send time."""
    path = state_path or _state_path()
    current = now or datetime.now(timezone.utc)
    timestamps = _load_timestamps(path)
    sent = []

    for task in bottlenecks:
        task_id = task.get("task_id")
        if not isinstance(task_id, str) or not task_id:
            continue
        # detect_bottlenecks returns only pending tasks and omits the status field.
        if str(task.get("status", "pending")).strip().lower() != "pending":
            continue
        priority = task.get("priority_score")
        downstream = task.get("downstream_count")
        people = task.get("affected_people")
        if (
            not isinstance(priority, (int, float)) or priority < 75
            or not isinstance(downstream, int) or not isinstance(people, int)
            or (downstream < 3 and people < 2)
        ):
            continue
        last_sent = timestamps.get(task_id)
        if last_sent is not None and current - last_sent < COOLDOWN:
            continue
        if send_notification(task):
            timestamps[task_id] = current
            sent.append(task_id)
            try:
                _save_timestamps(path, timestamps)
            except OSError:
                LOGGER.exception("Could not persist notification time for task %r", task_id)

    return sent
