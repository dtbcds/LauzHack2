"""The shared Queries panel for inspecting an organisation's task dependencies."""

from collections.abc import Callable
from dataclasses import dataclass
from functools import partial

import flet as ft

import palette as p
from component import Task
from queries import TaskQueries
from query_answers import build_answer

QUESTIONS = {
    "plan": ("Plan my work", "Find the order that keeps your teammates moving."),
    "slip": ("Check a delay", "See what work is at risk if a task slips."),
    "blocked": (
        "Trace blockers",
        "See what’s holding up a task and who to follow up with.",
    ),
    "teammate": (
        "Unblock a teammate",
        "Find the task that would free up the most work for them.",
    ),
}


@dataclass(frozen=True)
class QueryField:
    label: str
    control: ft.Control
    read: Callable[[], str | None]


def ask_panel(
    tasks: tuple[Task, ...],
    close: Callable[[], None],
    highlight: Callable[[set[str] | None], None],
    open_task: Callable[[Task], None],
) -> ft.Column:
    owners = {
        name: name for name in sorted({task.owner for task in tasks if task.owner})
    }
    queries = TaskQueries(tasks)

    question: str | None = None

    content = ft.ListView(expand=True, spacing=p.MEDIUM, padding=p.LARGE)
    result = ft.Column(spacing=p.MEDIUM)
    message = ft.Text(size=p.NOTE_TEXT, color=p.AMBER, visible=False)

    def heading(label: str) -> ft.Text:
        return ft.Text(
            label, size=p.SECTION_TITLE, color=p.TEXT, weight=ft.FontWeight.W_600
        )

    def option_row(
        title: str,
        on_click: Callable[[], None],
        *,
        detail: str,
        icon: ft.IconData | None = None
    ) -> ft.TextButton:
        label = ft.Text(
            title, size=p.BODY_TEXT, color=p.TEXT, weight=ft.FontWeight.W_600
        )
        text_controls: list[ft.Control] = [
            label,
            ft.Text(
                detail, size=p.NOTE_TEXT, color=p.MUTED, weight=ft.FontWeight.W_400
            ),
        ]

        row_controls: list[ft.Control] = []

        if icon is not None:
            row_controls.append(ft.Icon(icon, size=16, color=p.MUTED))

        row_controls.append(ft.Column(text_controls, spacing=4, expand=True))
        row_controls.append(ft.Icon(ft.Icons.CHEVRON_RIGHT, size=16, color=p.MUTED))

        return ft.TextButton(
            content=ft.Row(row_controls, spacing=p.SMALL),
            style=ft.ButtonStyle(
                padding=ft.Padding.symmetric(horizontal=p.SMALL, vertical=p.SMALL),
                shape=ft.RoundedRectangleBorder(radius=5),
            ),
            on_click=on_click,
        )

    def clear_answer() -> None:
        result.controls = []
        message.visible = False
        highlight(None)

    def inputs_changed() -> None:
        if question is None:
            return

        clear_answer()
        run_button.disabled = not all(field.read() for field in fields[question])

    def owner_changed() -> None:
        owner_name = (owner.data or "").strip().casefold()
        choices = {
            name: label
            for name, label in owners.items()
            if name.strip().casefold() != owner_name
        }

        replace_teammates(choices)
        teammate.disabled = not choices
        if not choices:
            teammate.tooltip = "No other task owners in this organisation"

        inputs_changed()

    owner, _ = p.select_menu("Choose owner", owners, owner_changed, expand=True)
    teammate, replace_teammates = p.select_menu(
        "Choose teammate", owners, inputs_changed, expand=True
    )
    task_choice, _ = p.select_menu(
        "Choose task",
        {task.id: task.title for task in tasks},
        inputs_changed,
        expand=True,
    )

    deadline = ft.TextField(
        hint_text="YYYY-MM-DD",
        tooltip="Deadline",
        text_size=p.CONTROL_TEXT,
        collapsed=True,
        border=ft.NoInputBorder(),
        content_padding=0,
        on_change=inputs_changed,
    )

    deadline_box = ft.Container(
        deadline,
        expand=True,
        height=p.CONTROL_HEIGHT,
        alignment=ft.Alignment.CENTER_LEFT,
        padding=ft.Padding.symmetric(horizontal=12),
        bgcolor=p.CONTROL,
        border=ft.Border.all(1, p.DIVIDER),
        border_radius=5,
    )

    def set_deadline_focus(focused: bool) -> None:
        deadline_box.border = (
            ft.Border.all(2, p.ACCENT) if focused else ft.Border.all(1, p.DIVIDER)
        )

    deadline.on_focus = lambda: set_deadline_focus(True)
    deadline.on_blur = lambda: set_deadline_focus(False)

    owner_field = QueryField("Your name", owner, lambda: owner.data)
    task_field = QueryField("Task", task_choice, lambda: task_choice.data)
    deadline_field = QueryField(
        "Deadline", deadline_box, lambda: (deadline.value or "").strip()
    )
    teammate_field = QueryField("Teammate", teammate, lambda: teammate.data)

    fields = {
        "plan": (owner_field, deadline_field),
        "slip": (task_field,),
        "blocked": (task_field,),
        "teammate": (owner_field, teammate_field),
    }

    def show_questions() -> None:
        nonlocal question

        question = None
        clear_answer()

        content.controls = [
            ft.Text(
                "Queries", size=p.PANE_TITLE, weight=ft.FontWeight.W_700, color=p.TEXT
            ),
            ft.Column(
                [
                    option_row(
                        QUESTIONS[key][0],
                        partial(show_question, key),
                        detail=QUESTIONS[key][1],
                        icon=icon,
                    )
                    for key, icon in (
                        ("plan", ft.Icons.LIST_ALT_OUTLINED),
                        ("slip", ft.Icons.SCHEDULE_OUTLINED),
                        ("blocked", ft.Icons.ACCOUNT_TREE_OUTLINED),
                        ("teammate", ft.Icons.PEOPLE_OUTLINE),
                    )
                ],
                spacing=p.SMALL,
                horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
            ),
        ]

    def show_question(key: str) -> None:
        nonlocal question

        question = key
        inputs_changed()

        query_fields = fields[key]
        input_rows = []

        for index, field in enumerate(query_fields):
            row_controls = [
                ft.Text(
                    field.label,
                    width=68 if len(query_fields) > 1 else None,
                    size=p.CONTROL_TEXT,
                    color=p.MUTED,
                ),
                field.control,
            ]
            if index == len(query_fields) - 1:
                row_controls.append(run_button)

            input_rows.append(
                ft.Row(
                    row_controls,
                    spacing=p.SMALL,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                )
            )

        content.controls = [
            ft.Row(
                [
                    ft.TextButton(
                        "All queries",
                        icon=ft.Icons.ARROW_BACK,
                        height=p.CONTROL_HEIGHT,
                        style=ft.ButtonStyle(
                            color=p.MUTED, padding=ft.Padding.only(right=p.SMALL)
                        ),
                        on_click=show_questions,
                    )
                ]
            ),
            heading(QUESTIONS[key][0]),
            ft.Text(QUESTIONS[key][1], size=p.CONTROL_TEXT, color=p.MUTED),
            ft.Column(input_rows, spacing=p.SMALL),
            message,
            result,
        ]

    def run_query() -> None:
        if question is None:
            return

        try:
            answer = build_answer(
                queries,
                question,
                owner=owner.data,
                deadline=(deadline.value or "").strip(),
                task=task_choice.data,
                teammate=teammate.data,
            )
        except ValueError as error:
            message.value = (
                "Enter a valid deadline in YYYY-MM-DD format."
                if question == "plan"
                else str(error)
            )
            message.visible = True

            return

        result.controls = [
            ft.Divider(height=p.SMALL, color=p.DIVIDER),
            heading("Answer"),
            ft.Text(answer.text, size=p.BODY_TEXT, color=p.TEXT, selectable=True),
        ]
        if answer.rows:
            related_tasks: list[ft.Control] = [
                ft.Text(
                    "Related tasks",
                    size=p.CONTROL_TEXT,
                    color=p.MUTED,
                    weight=ft.FontWeight.W_600,
                ),
            ]

            for item, detail in answer.rows:
                related_tasks.append(
                    option_row(item.title, partial(open_task, item), detail=detail)
                )

            result.controls.extend(
                [
                    ft.Divider(height=1, color=p.DIVIDER),
                    ft.Column(
                        related_tasks,
                        spacing=p.SMALL,
                        horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
                    ),
                ]
            )

        task_ids = {item.id for item, _detail in answer.rows}
        task_ids.update(item.id for item in answer.related)
        highlight(task_ids)

    run_style = p.control_button_style()
    run_style.bgcolor = {
        ft.ControlState.DISABLED: p.CONTROL,
        ft.ControlState.DEFAULT: p.ACCENT,
    }
    run_style.color = {
        ft.ControlState.DISABLED: p.MUTED,
        ft.ControlState.DEFAULT: p.BACKGROUND,
    }

    run_button = ft.TextButton(
        "Run query", height=p.CONTROL_HEIGHT, style=run_style, on_click=run_query
    )
    show_questions()

    return ft.Column(
        [
            ft.Container(
                ft.Row(
                    [
                        ft.Icon(ft.Icons.QUERY_STATS, size=19, color=p.MUTED),
                        ft.Container(expand=True),
                        ft.IconButton(
                            ft.Icons.CLOSE,
                            tooltip="Close Queries",
                            icon_size=18,
                            icon_color=p.MUTED,
                            on_click=close,
                        ),
                    ]
                ),
                padding=ft.Padding.only(left=p.LARGE, right=p.MEDIUM, top=p.SMALL),
            ),
            content,
        ],
        spacing=0,
        expand=True,
    )
