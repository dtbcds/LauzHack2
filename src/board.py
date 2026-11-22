from collections.abc import Callable, Mapping
from typing import Any
from dataclasses import dataclass

import flet as ft

import palette as p
from component import Task, format_deadline
from filters import task_filters
from graph import TaskGraph
from native_motion import GraphGestureSurface, SettledSize


@dataclass
class TaskBoard:
    control: ft.LayoutControl
    view_switch: ft.Container
    select: Callable[[Task | None], None]
    dismiss_filters: Callable[[], bool]
    set_tasks: Callable[..., None]
    show_query_result: Callable[[set[str] | None], None]
    gesture_surface: Callable[..., GraphGestureSurface]


def task_board(
    tasks: tuple[Task, ...],
    on_select: Callable[[Task | None], None],
    ask_button: ft.Control | None = None,
    *, snapshot: Mapping[str, Any] | None = None,
    status_control: ft.Control | None = None,
) -> TaskBoard:
    selected: Task | None = None
    highlighted: set[str] = set()
    query_active = False

    compact = False
    board_width = 1200.0
    graph_view = TaskGraph(lambda task: select(task))
    graph_view.set_tasks(tasks, snapshot)
    gesture_surfaces: list[GraphGestureSurface] = []

    blocking_rows = ft.ListView(expand=True, spacing=0)
    non_blocking_rows = ft.ListView(expand=True, spacing=0)
    blocking_count = ft.Text(size=p.NOTE_TEXT, color=p.MUTED)
    non_blocking_count = ft.Text(size=p.NOTE_TEXT, color=p.MUTED)
    count = ft.Text(size=12, color=p.MUTED)
    query_scope = ft.Text(
        "Showing all organisation tasks for this query",
        size=p.NOTE_TEXT,
        color=p.MUTED,
        visible=False,
    )

    impact_title = ft.Text(size=13, color=p.TEXT, weight=ft.FontWeight.W_600)
    impact_detail = ft.Text(size=12, color=p.MUTED)
    impact_callout = ft.Container(
        ft.Row(
            [
                ft.Icon(ft.Icons.ACCOUNT_TREE_OUTLINED, size=17, color=p.BOTTLENECK),
                ft.Column(
                    [
                        ft.Text("Highest-impact bottleneck", size=12, color=p.BOTTLENECK),
                        impact_title,
                        impact_detail,
                    ],
                    spacing=2,
                    expand=True,
                ),
                ft.Icon(ft.Icons.CHEVRON_RIGHT, size=16, color=p.MUTED),
            ],
            spacing=p.SMALL,
        ),
        padding=ft.Padding.symmetric(vertical=p.SMALL, horizontal=12),
        bgcolor=p.SURFACE,
        border=ft.Border.all(1, p.DIVIDER),
        border_radius=6,
        visible=False,
        ink=True,
        tooltip="Open bottleneck details",
    )

    filters = task_filters(tasks, lambda: render())

    def table_row(cells: list[ft.Control]) -> ft.Row:
        task, owner_cell, deadline, priority_cell, downstream_cell = cells
        columns = [task]
        if not compact:
            columns.extend([owner_cell, deadline])

        columns.extend([priority_cell, downstream_cell])

        return ft.Row(
            columns, spacing=p.SMALL, vertical_alignment=ft.CrossAxisAlignment.CENTER
        )

    def bordered_row(
        content: ft.Control,
        *,
        height: int,
        bgcolor: str | None = None,
        on_click: Callable[..., None] | None = None,
    ) -> ft.Container:
        return ft.Container(
            content,
            height=height,
            bgcolor=bgcolor,
            on_click=on_click,
            ink=on_click is not None,
            padding=ft.Padding.symmetric(horizontal=p.SMALL),
            border=ft.Border(bottom=ft.BorderSide(1, p.DIVIDER)),
        )

    def task_row(task: Task, *, highest_impact: bool) -> ft.Container:
        active = selected is not None and selected.id == task.id
        is_highlighted = task.id in highlighted

        name_controls: list[ft.Control] = [
            ft.Text(
                task.title,
                size=p.CONTROL_TEXT,
                color=p.ACCENT if is_highlighted else p.TEXT,
                max_lines=1,
                overflow=ft.TextOverflow.ELLIPSIS,
            ),
        ]

        name = ft.Column(name_controls, spacing=4, tight=True)
        if compact:
            name.controls.append(
                ft.Text(
                    f"{task.owner or 'Unknown'} · {format_deadline(task.deadline)}",
                    size=p.NOTE_TEXT, color=p.MUTED,
                    max_lines=1, overflow=ft.TextOverflow.ELLIPSIS,
                ),
            )

        row_color = None
        if active:
            row_color = p.SELECTED
        elif is_highlighted:
            row_color = p.CONTROL

        return bordered_row(
            table_row(
                [
                    ft.TextButton(
                        content=name,
                        expand=True,
                        tooltip=f"{task.title}\n{task.owner or 'Unknown'} · {format_deadline(task.deadline)}",
                        style=ft.ButtonStyle(
                            padding=0, alignment=ft.Alignment.CENTER_LEFT
                        ),
                        on_click=lambda: select(task),
                    ),
                    ft.Text(task.owner or "Unknown", width=62, size=13, color=p.MUTED),
                    ft.Text(
                        format_deadline(task.deadline),
                        width=122,
                        size=12,
                        color=p.MUTED,
                    ),
                    ft.Text(
                        str(task.score),
                        width=50,
                        size=13,
                        color=p.TEXT,
                        tooltip="Weighted priority out of 100. Open the task for the breakdown.",
                    ),
                    ft.Text(
                        str(task.downstream_count),
                        width=76,
                        size=13,
                        color=p.BOTTLENECK if highest_impact else p.MUTED,
                        weight=ft.FontWeight.W_600 if highest_impact else None,
                        tooltip=(
                            "Most downstream tasks among visible bottlenecks"
                            if highest_impact
                            else None
                        ),
                    ),
                ]
            ),
            height=62 if compact else 42,
            bgcolor=row_color,
            on_click=lambda: select(task),
        )

    def render(*, keep_selection: bool = False) -> None:
        nonlocal selected

        if graph_view.control.visible:
            graph_view.render(selected, highlighted)

            return

        shown = filters.matching_tasks(tasks)
        update_list_layout(shown)
        empty_message.value = (
            "No tasks in this organisation yet."
            if not tasks else "No tasks match these filters."
        )

        if not keep_selection and selected is not None and selected not in shown:
            selected = None
            on_select(None)

        lead = max(
            (task for task in shown if task.bottleneck and task.downstream_count),
            key=lambda task: (task.downstream_count, task.score),
            default=None,
        )
        impact_callout.visible = lead is not None
        if lead is not None:
            impact_title.value = lead.title
            impact_detail.value = f"{lead.downstream_count} downstream tasks · {lead.affected_people} people affected"
            impact_callout.on_click = lambda: select(lead)

        for is_blocking, rows, group_count in (
            (True, blocking_rows, blocking_count),
            (False, non_blocking_rows, non_blocking_count),
        ):
            group = [task for task in shown if task.bottleneck == is_blocking]
            rows.controls = [task_row(task, highest_impact=task is lead) for task in group]
            group_count.value = str(len(group))

        count.value = f"{len(shown)} {'task' if len(shown) == 1 else 'tasks'}"

    def select(task: Task | None) -> None:
        nonlocal selected

        selected = task
        on_select(task)
        render(keep_selection=True)

    def show_query_result(task_ids: set[str] | None) -> None:
        nonlocal highlighted, query_active

        highlighted = set(task_ids or ())
        query_active = task_ids is not None
        query_scope.visible = query_active and not graph_view.control.visible
        filters.set_query_override(query_active)
        render(keep_selection=True)

    def set_tasks(records: tuple[Task, ...], snapshot: Mapping[str, Any] | None = None) -> None:
        nonlocal tasks, selected, query_active

        tasks = records
        graph_view.set_tasks(records, snapshot)
        selected = None
        highlighted.clear()
        query_active = False
        query_scope.visible = False
        filters.set_query_override(False)
        filters.dismiss()
        filters.set_owners(records)
        on_select(None)
        render()

    def make_headers() -> list[ft.Control]:
        return [
            ft.Text(label, size=12, color=p.MUTED, width=width, expand=width is None)
            for label, width in (
                ("Task", None), ("Owner", 62), ("Deadline", 122),
                ("Priority", 50), ("Downstream", 76),
            )
        ]

    blocking_headers = make_headers()
    non_blocking_headers = make_headers()
    blocking_header = bordered_row(table_row(blocking_headers), height=34)
    non_blocking_header = bordered_row(table_row(non_blocking_headers), height=34)

    def task_column(title: str, group_count: ft.Text, header: ft.Container, rows: ft.ListView) -> ft.Column:
        return ft.Column(
            [
                ft.Row([
                    ft.Text(title, size=p.SECTION_TITLE, color=p.TEXT, weight=ft.FontWeight.W_600),
                    group_count,
                ], spacing=p.SMALL),
                ft.Column([header, rows], spacing=0, expand=True),
            ],
            spacing=p.SMALL,
            expand=True,
        )

    blocking_column = task_column("Blocking", blocking_count, blocking_header, blocking_rows)
    non_blocking_column = task_column("Non-blocking", non_blocking_count, non_blocking_header, non_blocking_rows)
    tables = ft.Container(expand=True)
    empty_message = ft.Text(size=p.CONTROL_TEXT, color=p.MUTED)
    empty_state = ft.Container(empty_message, padding=p.MEDIUM, expand=True)

    def update_list_layout(shown: list[Task]) -> None:
        nonlocal compact

        blocking_column.visible = any(task.bottleneck for task in shown)
        non_blocking_column.visible = any(not task.bottleneck for task in shown)
        two_columns = blocking_column.visible and non_blocking_column.visible
        tables.visible = bool(shown)
        empty_state.visible = not shown

        gutter = p.MEDIUM if board_width < 610 else p.GUTTER
        available = max(0, board_width - 2 * gutter)
        stacked = two_columns and available < 700
        column_width = (available - p.LARGE) / 2 if two_columns and not stacked else available
        compact = column_width < 610

        blocking_header.content = table_row(blocking_headers)
        non_blocking_header.content = table_row(non_blocking_headers)

        columns: list[ft.Control] = [blocking_column, non_blocking_column]
        if stacked and not isinstance(tables.content, ft.Column):
            tables.content = ft.Column(columns, spacing=p.LARGE)
        elif not stacked and not isinstance(tables.content, ft.Row):
            tables.content = ft.Row(
                columns, spacing=p.LARGE,
                vertical_alignment=ft.CrossAxisAlignment.STRETCH,
            )

    def resize(event: ft.LayoutSizeChangeEvent) -> None:
        nonlocal board_width

        board_width = event.width
        gutter = p.MEDIUM if board_width < 610 else p.GUTTER
        available = max(0, event.width - 2 * gutter - p.CONTROL_HEIGHT - p.SMALL)
        filters.resize_search(available)
        control.padding = ft.Padding.symmetric(vertical=p.LARGE, horizontal=gutter)

        render(keep_selection=True)

    def resize_list_area(event: ft.LayoutSizeChangeEvent) -> None:
        filters.resize_popover(event.height)

    list_content = ft.Column([impact_callout, empty_state, tables, count], spacing=p.MEDIUM)
    list_area = ft.Stack(
        [list_content],
        expand=True,
        fit=ft.StackFit.EXPAND,
    )

    def show_view(use_graph: bool) -> None:
        filters.dismiss()
        list_area.visible = not use_graph
        graph_view.control.visible = use_graph
        filters.toolbar.visible = not use_graph
        query_scope.visible = query_active and not use_graph
        list_style.bgcolor = ft.Colors.TRANSPARENT if use_graph else p.SURFACE
        graph_style.bgcolor = p.SURFACE if use_graph else ft.Colors.TRANSPARENT
        list_style.color = p.MUTED if use_graph else p.TEXT
        graph_style.color = p.TEXT if use_graph else p.MUTED

        for surface in gesture_surfaces:
            surface.active = use_graph

        render(keep_selection=use_graph)

    def gesture_surface(content: ft.Control, **layout) -> GraphGestureSurface:
        surface = graph_view.gesture_surface(content, **layout)
        surface.active = bool(graph_view.control.visible)
        gesture_surfaces.append(surface)

        return surface

    list_style = ft.ButtonStyle(
        bgcolor=p.SURFACE, color=p.TEXT,
        shape=ft.RoundedRectangleBorder(radius=24),
        padding=ft.Padding.symmetric(horizontal=p.MEDIUM),
    )
    graph_style = ft.ButtonStyle(
        bgcolor=ft.Colors.TRANSPARENT, color=p.MUTED,
        shape=ft.RoundedRectangleBorder(radius=24),
        padding=ft.Padding.symmetric(horizontal=p.MEDIUM),
    )

    list_tab = ft.TextButton(
        "List View", width=136, height=p.CONTROL_HEIGHT,
        style=list_style,
        on_click=lambda: show_view(False),
    )
    graph_tab = ft.TextButton(
        "Graph View", width=136, height=p.CONTROL_HEIGHT,
        style=graph_style,
        on_click=lambda: show_view(True),
    )
    view_switch = ft.Container(
        ft.Row([list_tab, graph_tab], spacing=0, tight=True),
        width=278,
        height=p.CONTROL_HEIGHT + 6,
        bgcolor=p.CONTROL, padding=2, border_radius=24,
        border=ft.Border.all(1, p.DIVIDER),
    )
    title_controls: list[ft.Control] = [
        ft.Text("Tasks", size=36, weight=ft.FontWeight.W_700, color=p.TEXT),
        ft.Container(expand=True),
    ]
    if ask_button is not None:
        title_controls.append(ask_button)

    content_area = ft.Stack(
        [list_area, graph_view.control, filters.dismiss_area, filters.popover],
        expand=True,
        fit=ft.StackFit.EXPAND,
    )

    control = ft.Container(
        ft.Column(
            [
                ft.Row(title_controls, spacing=p.SMALL),
                *([status_control] if status_control is not None else []),
                filters.toolbar,
                query_scope,
                SettledSize(content_area, expand=True, on_settled=resize_list_area),
            ],
            spacing=p.MEDIUM,
        ),
        padding=ft.Padding.symmetric(vertical=p.LARGE, horizontal=p.GUTTER),
        expand=True,
    )
    render()

    return TaskBoard(
        SettledSize(control, expand=True, on_settled=resize),
        view_switch, select, filters.dismiss, set_tasks, show_query_result,
        gesture_surface,
    )
