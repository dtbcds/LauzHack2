import json
import sys
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import notifications


NOW = datetime(2026, 11, 21, 12, tzinfo=timezone.utc)


def bottleneck(**changes):
    task = {
        "task_id": "task-1",
        "title": "Approve budget",
        "owner": "Ari",
        "deadline": "2026-11-22",
        "status": "pending",
        "priority_score": 80,
        "downstream_count": 3,
        "affected_people": 1,
    }
    return {**task, **changes}


def test_qualifying_bottleneck_sends_and_persists(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(notifications, "send_notification", lambda task: calls.append(task) or True)
    path = tmp_path / "state.json"
    assert notifications.run_bottleneck_check([bottleneck()], state_path=path, now=NOW) == ["task-1"]
    assert calls == [bottleneck()]
    assert json.loads(path.read_text())["task-1"] == NOW.isoformat()


def test_priority_and_impact_thresholds(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(notifications, "send_notification", lambda task: calls.append(task) or True)
    tasks = [
        bottleneck(task_id="low", priority_score=74.99),
        bottleneck(task_id="small", downstream_count=2, affected_people=1),
        bottleneck(task_id="people", downstream_count=1, affected_people=2),
    ]
    assert notifications.run_bottleneck_check(tasks, state_path=tmp_path / "state.json", now=NOW) == ["people"]
    assert calls == [tasks[-1]]


def test_cooldown_survives_restart_and_expires_at_four_hours(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(notifications, "send_notification", lambda task: calls.append(task) or True)
    path = tmp_path / "state.json"
    assert notifications.run_bottleneck_check([bottleneck()], state_path=path, now=NOW) == ["task-1"]
    assert notifications.run_bottleneck_check(
        [bottleneck()], state_path=path, now=NOW + timedelta(hours=3, minutes=59)
    ) == []
    assert notifications.run_bottleneck_check(
        [bottleneck()], state_path=path, now=NOW + timedelta(hours=4)
    ) == ["task-1"]
    assert len(calls) == 2


def test_completed_task_never_sends(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(notifications, "send_notification", lambda task: calls.append(task) or True)
    assert notifications.run_bottleneck_check(
        [bottleneck(status="completed", priority_score=100)],
        state_path=tmp_path / "state.json", now=NOW,
    ) == []
    assert calls == []


def test_failure_does_not_start_cooldown(monkeypatch, tmp_path):
    monkeypatch.setattr(notifications, "send_notification", lambda task: False)
    path = tmp_path / "state.json"
    assert notifications.run_bottleneck_check([bottleneck()], state_path=path, now=NOW) == []
    assert not path.exists()


def test_windows_toast_content_and_unknown_owner(monkeypatch):
    shown = []

    class FakeNotification:
        def __init__(self, **kwargs):
            shown.append(kwargs)

        def show(self):
            pass

    monkeypatch.setattr(notifications.platform, "system", lambda: "Windows")
    monkeypatch.setitem(sys.modules, "winotify", SimpleNamespace(Notification=FakeNotification))
    assert notifications.send_notification(bottleneck(owner=None)) is True
    assert shown[0]["title"] == "High-impact task is blocking work"
    for line in ("Approve budget", "Owner: Unknown", "Deadline: 2026-11-22",
                 "Downstream tasks: 3", "Affected coworkers: 1"):
        assert line in shown[0]["msg"]


def test_toast_library_failure_is_handled(monkeypatch):
    class FailingNotification:
        def __init__(self, **kwargs):
            raise RuntimeError("toast unavailable")

    monkeypatch.setattr(notifications.platform, "system", lambda: "Windows")
    monkeypatch.setitem(sys.modules, "winotify", SimpleNamespace(Notification=FailingNotification))
    assert notifications.send_notification(bottleneck()) is False


def test_macos_notification_uses_native_command_safely(monkeypatch):
    calls = []
    monkeypatch.setattr(notifications.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(
        notifications.subprocess, "run",
        lambda args, **kwargs: calls.append((args, kwargs)),
    )
    task = bottleneck(title='Review "launch"; do not execute', owner=None)
    assert notifications.send_notification(task) is True
    args, options = calls[0]
    assert args[0] == "osascript"
    assert args[-2] == notifications.TITLE
    assert 'Review "launch"; do not execute' in args[-1]
    assert "Owner: Unknown" in args[-1]
    assert options["check"] is True
    assert options["timeout"] == 10


def test_macos_notification_failure_does_not_start_cooldown(monkeypatch, tmp_path):
    def fail(*args, **kwargs):
        raise notifications.subprocess.CalledProcessError(1, args[0])

    monkeypatch.setattr(notifications.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(notifications.subprocess, "run", fail)
    path = tmp_path / "state.json"
    assert notifications.run_bottleneck_check([bottleneck()], state_path=path, now=NOW) == []
    assert not path.exists()


def test_macos_state_path_uses_application_support(monkeypatch, tmp_path):
    monkeypatch.setattr(notifications.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(notifications.Path, "home", lambda: tmp_path)
    assert notifications._state_path() == (
        tmp_path / "Library" / "Application Support" / "DependencyIntelligence"
        / "notification_timestamps.json"
    )
