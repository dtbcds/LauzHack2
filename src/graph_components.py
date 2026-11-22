"""Task cards and directed links used by the dependency graph."""

from collections.abc import Callable

import flet as ft
import flet.canvas as canvas

import palette as p
from component import Task, format_deadline

NODE_WIDTH = 208
NODE_HEIGHT = 120
HOTSPOT_SIZE = 30


def bottleneck_marker(
    task: Task,
    on_select: Callable[[], None],
    *,
    waiting_on: tuple[str, ...],
    blocks_you: bool,
    blocks_others: bool,
) -> ft.Container:
    label = "Blocks your work" if blocks_you else "Blocks other people’s work"
    if blocks_you and blocks_others:
        label = "Blocks your work and other people’s work"

    prerequisites = ", ".join(waiting_on)
    explanation = f"{task.title}\nWaiting on bottlenecks: {prerequisites}"
    color = p.ACCENT if blocks_you else p.BOTTLENECK
    outer_color = p.BOTTLENECK if blocks_others else color
    rings: list[ft.Control] = [
        ft.Container(
            width=HOTSPOT_SIZE, height=HOTSPOT_SIZE, border_radius=HOTSPOT_SIZE / 2,
            bgcolor=ft.Colors.with_opacity(0.12, outer_color),
            border=ft.Border.all(1, outer_color),
        ),
        ft.Container(
            width=20, height=20, border_radius=10,
            border=ft.Border.all(1, color),
        ),
        ft.Container(width=8, height=8, border_radius=4, bgcolor=color),
    ]

    return ft.Container(
        ft.Stack(rings, alignment=ft.Alignment.CENTER),
        width=HOTSPOT_SIZE,
        height=HOTSPOT_SIZE,
        border_radius=HOTSPOT_SIZE / 2,
        tooltip=f"{label}\n{explanation}",
        on_click=on_select,
        data=task.id,
    )


def task_node(
    task: Task,
    on_select: Callable[[], None],
    *,
    blocked_by: tuple[str, ...],
    selected: bool = False,
    highlighted: bool = False,
) -> ft.Container:
    completed = task.status.casefold() in {"done", "complete", "completed"}
    status = "Ready"
    if completed:
        status = "Completed"
    elif blocked_by:
        status = f"Waiting on {len(blocked_by)}"

    badges: list[ft.Control] = [p.tag(status)]
    if task.bottleneck and not completed:
        badges.append(p.tag("Bottleneck", highlighted=True))

    border_color = p.DIVIDER if completed else p.AMBER if blocked_by else p.MUTED
    border_width = 2

    if task.bottleneck and not completed:
        border_color = p.BOTTLENECK
        border_width = max(2, border_width)

    if selected or highlighted:
        border_color = p.ACCENT
        border_width = 3

    details = f"{task.owner or 'Unknown owner'} · Priority {task.score}"
    tooltip = task.title
    if blocked_by and not completed:
        tooltip += "\nWaiting on " + ", ".join(blocked_by)

    return ft.Container(
        ft.Column(
            [
                ft.Text(
                    task.title,
                    size=p.CONTROL_TEXT,
                    color=p.TEXT,
                    weight=ft.FontWeight.W_600,
                    max_lines=2,
                    overflow=ft.TextOverflow.ELLIPSIS,
                ),
                ft.Text(
                    details, size=p.NOTE_TEXT, color=p.MUTED,
                    max_lines=1, overflow=ft.TextOverflow.ELLIPSIS,
                ),
                ft.Text(
                    format_deadline(task.deadline), size=p.NOTE_TEXT, color=p.MUTED
                ),
                ft.Container(expand=True),
                ft.Row(badges, spacing=4),
            ],
            spacing=3,
        ),
        width=NODE_WIDTH,
        height=NODE_HEIGHT,
        padding=10,
        bgcolor=p.SURFACE,
        border=ft.Border.all(border_width, border_color),
        border_radius=6,
        tooltip=tooltip,
        ink=True,
        on_click=on_select,
    )


def dependency_link(
    source: tuple[float, float],
    target: tuple[float, float],
    *,
    highlighted: bool = False,
    blocking: bool = False,
    soft: bool = False,
    horizontal: bool = False,
) -> list[canvas.Shape]:
    """Join task edges with a curved link and an arrow into the receiving node."""
    start_x, start_y = source
    end_x, end_y = target
    color = p.ACCENT if highlighted else p.BOTTLENECK if blocking else p.MUTED
    stroke = ft.Paint(color=color, stroke_width=1.5, style=ft.PaintingStyle.STROKE)
    if soft:
        stroke.stroke_dash_pattern = [5, 4]

    elements: list[canvas.Path.PathElement] = [
        canvas.Path.MoveTo(start_x, start_y),
    ]
    if horizontal:
        bend = (start_x + end_x) / 2
        elements.append(canvas.Path.CubicTo(bend, start_y, bend, end_y, end_x, end_y))
        arrow_start = (end_x - 6, end_y - 4)
        arrow_end = (end_x - 6, end_y + 4)
    else:
        bend = (start_y + end_y) / 2
        elements.append(canvas.Path.CubicTo(start_x, bend, end_x, bend, end_x, end_y))
        arrow_start = (end_x - 4, end_y - 6)
        arrow_end = (end_x + 4, end_y - 6)

    path = canvas.Path(elements, paint=stroke)
    arrow = canvas.Path(
        [
            canvas.Path.MoveTo(*arrow_start),
            canvas.Path.LineTo(end_x, end_y),
            canvas.Path.LineTo(*arrow_end),
        ],
        paint=ft.Paint(color=color, stroke_width=1.5, style=ft.PaintingStyle.STROKE),
    )

    return [path, arrow]
