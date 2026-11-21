from dataclasses import dataclass
from datetime import datetime

import flet as ft
import palette


PRIORITY_FACTORS = (
    ("Downstream impact", 40, "How much work depends on this task."),
    ("Deadline urgency", 25, "How soon this task is due."),
    ("People affected", 20, "How many coworkers depend on the downstream work."),
    ("Critical path", 15, "Whether delays could push back the project deadline."),
)


@dataclass(frozen=True)
class Task:
    id: str
    title: str
    description: str
    owner: str
    deadline: str | None
    score: int
    status: str = "pending"
    bottleneck: bool = False
    downstream_count: int = 0
    affected_people: int = 0
    prerequisites: tuple[str, ...] = ()
    dependents: tuple[str, ...] = ()
    evidence: str | None = None
    confidence: float | None = None
    score_breakdown: tuple[int, int, int, int] = (0, 0, 0, 0)


def format_deadline(value: str | None) -> str:
    if value is None:
        return "Unknown deadline"
    return datetime.fromisoformat(value).strftime("%a, %d %b · %H:%M")


def task_detail(task: Task, close) -> ft.Column:
    def property_row(name, value, icon):
        return ft.Row(
            [
                ft.Icon(icon, size=15, color=palette.MUTED),
                ft.Text(name, width=117, size=13, color=palette.MUTED),
                ft.Text(value, size=13, color=palette.TEXT, expand=True),
            ],
            spacing=palette.SMALL,
            vertical_alignment=ft.CrossAxisAlignment.START,
        )

    def section(title, *controls):
        return ft.Column(
            [ft.Text(title, size=palette.SECTION_TITLE, color=palette.TEXT, weight=ft.FontWeight.W_600), *controls],
            spacing=palette.SMALL,
        )

    def body(value, *, italic=False):
        return ft.Text(value, size=palette.BODY_TEXT, color=palette.TEXT, italic=italic)

    def note(value):
        return ft.Text(value, size=palette.NOTE_TEXT, color=palette.MUTED)

    def dependency_group(label, titles):
        return ft.Column([note(label), body("\n".join(titles) or "None")], spacing=4)

    properties = [
        property_row("Owner", task.owner or "Unknown owner", ft.Icons.PERSON_OUTLINE),
        property_row("Deadline", format_deadline(task.deadline), ft.Icons.EVENT_OUTLINED),
    ]
    score_lines = [
        ft.Row(
            [
                ft.Text(name, size=13, color=palette.MUTED, expand=True, tooltip=description),
                ft.Text(f"{points} / {maximum}", size=13, width=48,
                        text_align=ft.TextAlign.RIGHT, tooltip=description),
            ],
            spacing=palette.SMALL,
        )
        for (name, maximum, description), points in zip(PRIORITY_FACTORS, task.score_breakdown)
    ]
    sections = [
        ft.Text(task.title, size=palette.PANE_TITLE, weight=ft.FontWeight.W_700, color=palette.TEXT),
        ft.Row(
            [
                palette.tag(task.status.title()),
                *([palette.tag("Bottleneck", highlighted=True)] if task.bottleneck else []),
            ],
            spacing=palette.SMALL,
        ),
        ft.Column(properties, spacing=10),
        section(
            "Dependency impact",
            body(
                f"{len(task.dependents)} direct · {task.downstream_count} total downstream"
                f" · {task.affected_people} people affected",
            ),
            note("Total downstream includes tasks waiting indirectly."),
        ),
        section(
            f"Priority · {task.score} / 100",
            note("The four weighted scores add up to the task’s priority. "
                 "Higher scores rank first in priority order."),
            *score_lines,
        ),
        ft.Divider(height=1, color=palette.DIVIDER),
        section("Description", body(task.description or "No description")),
        section(
            "Dependencies",
            dependency_group("Prerequisites", task.prerequisites),
            dependency_group("Direct dependents", task.dependents),
        ),
    ]
    if task.evidence:
        confidence = f"{task.confidence:.0%} confidence" if task.confidence is not None else "Confidence unavailable"
        sections.append(
            section(
                "Dependency evidence",
                body(task.evidence, italic=True),
                note(confidence),
            )
        )

    return ft.Column(
        [
            ft.Container(
                ft.Row(
                    [
                        ft.Container(expand=True),
                        ft.IconButton(
                            ft.Icons.CLOSE,
                            tooltip="Close task",
                            icon_size=18,
                            icon_color=palette.MUTED,
                            on_click=lambda _: close(None),
                        ),
                    ],
                ),
                padding=ft.Padding.only(left=palette.LARGE, right=palette.MEDIUM, top=palette.SMALL),
            ),
            ft.ListView(
                controls=sections,
                expand=True,
                spacing=palette.MEDIUM,
                padding=ft.Padding.only(left=palette.LARGE, right=palette.LARGE, bottom=palette.LARGE),
            ),
        ],
        spacing=0,
        expand=True,
    )
