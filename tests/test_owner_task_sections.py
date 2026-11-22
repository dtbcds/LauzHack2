import sys
from dataclasses import replace
from pathlib import Path

import flet as ft

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from analysis_data import tasks_from_snapshot
from board import task_board
from component import Task
from filters import is_blocked


def walk(control):
    if not isinstance(control, ft.Control):
        return
    yield control
    for child in getattr(control, "controls", ()) or ():
        yield from walk(child)
    content = getattr(control, "content", None)
    if content is not None:
        yield from walk(content)


def section(board, title):
    return next(
        control for control in walk(board.control)
        if isinstance(control, ft.Column)
        and control.controls
        and isinstance(control.controls[0], ft.Row)
        and control.controls[0].controls
        and isinstance(control.controls[0].controls[0], ft.Text)
        and control.controls[0].controls[0].value == title
    )


def row_titles(column):
    rows = next(control for control in walk(column) if isinstance(control, ft.ListView))
    return [
        control.value for row in rows.controls for control in walk(row)
        if isinstance(control, ft.Text) and control.value in {"Ready", "Waiting", "Soft link"}
    ]


def test_owner_sections_show_startable_and_blocked_tasks():
    tasks = (
        Task("blocker", "Prerequisite", "", "Teammate", None, 50),
        Task("ready", "Ready", "", "Nil", None, 40),
        Task("waiting", "Waiting", "", "Nil", None, 30,
             prerequisites=("blocker",), blocking_prerequisites=("blocker",)),
        Task("soft", "Soft link", "", "Nil", None, 20,
             prerequisites=("blocker",), blocking_prerequisites=()),
        Task("done", "Finished", "", "Nil", None, 10, status="completed"),
    )
    board = task_board(tasks, lambda task: None)
    assert section(board, "Bottlenecks")
    assert section(board, "Other tasks")

    owner = next(control for control in walk(board.control)
                 if isinstance(control, ft.PopupMenuButton)
                 and str(control.tooltip).startswith("Owner"))
    next(item for item in owner.items if item.data == "Nil").on_click()

    assert set(row_titles(section(board, "Unblocked"))) == {"Ready", "Soft link"}
    assert row_titles(section(board, "Blocked")) == ["Waiting"]
    assert section(board, "Unblocked").controls[0].controls[1].value == "2"
    assert section(board, "Blocked").controls[0].controls[1].value == "1"

    board.set_tasks((replace(tasks[0], status="done"), *tasks[1:]))
    assert set(row_titles(section(board, "Unblocked"))) == {"Ready", "Waiting", "Soft link"}
    assert row_titles(section(board, "Blocked")) == []


def test_snapshot_keeps_soft_prerequisites_out_of_blocked_status():
    def node(key):
        return {
            "id": key, "title": key, "owner_display": "Nil", "status": "pending",
            "priority": {"priority_score": 10, "downstream_component": 0,
                         "urgency_component": 0, "people_component": 0,
                         "critical_path_component": 0},
            "impact": {"downstream_count": 0, "affected_people": 0},
            "is_bottleneck": False,
        }

    tasks = tasks_from_snapshot({
        "nodes": [node("a"), node("hard"), node("soft")],
        "edges": [
            {"source": "a", "target": "hard", "type": "hard"},
            {"source": "a", "target": "soft", "type": "soft"},
        ],
    })
    by_id = {task.id: task for task in tasks}
    assert by_id["soft"].prerequisites == ("a",)
    assert is_blocked(by_id["hard"], tasks)
    assert not is_blocked(by_id["soft"], tasks)
