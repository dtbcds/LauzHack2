from collections.abc import Callable
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
    set_tasks: Callable[[tuple[Task, ...]], None]
    show_query_result: Callable[[set[str] | None], None]
    gesture_surface: Callable[..., GraphGestureSurface]


def task_board(
    tasks: tuple[Task, ...],
    on_select: Callable[[Task | None], None],
    ask_button: ft.Control | None = None,
) -> TaskBoard:
    selected: Task | None = None
    highlighted: set[str] = set()

    compact = False
    narrow = False
    graph_view = TaskGraph(lambda task: select(task))
    graph_view.set_tasks(tasks)
    gesture_surfaces: list[GraphGestureSurface] = []

    rows = ft.ListView(expand=True, spacing=0)
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
        task, owner_cell, deadline, priority_cell, downstream_cell, flag_cell = cells
        columns = [task]
        if not compact:
            columns.append(owner_cell)

        if not narrow:
            columns.append(deadline)

        columns.extend([priority_cell, downstream_cell])
        if not compact:
            columns.append(flag_cell)

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
                expand=True,
                max_lines=1,
                overflow=ft.TextOverflow.ELLIPSIS,
            ),
        ]

        if compact and task.bottleneck:
            name_controls.append(
                ft.Icon(
                    ft.Icons.WARNING_AMBER_ROUNDED,
                    size=15,
                    color=p.BOTTLENECK,
                    tooltip="Bottleneck",
                )
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
                        content=ft.Row(name_controls, spacing=p.SMALL),
                        expand=True,
                        tooltip=task.title,
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
                    ft.Container(
                        (
                            p.tag("Bottleneck", highlighted=True)
                            if task.bottleneck
                            else None
                        ),
                        width=84,
                        alignment=ft.Alignment.CENTER_LEFT,
                    ),
                ]
            ),
            height=42,
            bgcolor=row_color,
            on_click=lambda: select(task),
        )

    def render(*, keep_selection: bool = False) -> None:
        nonlocal selected

        shown = filters.matching_tasks(tasks)

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

        rows.controls = [
            task_row(task, highest_impact=task is lead) for task in shown
        ] or [
            ft.Container(
                ft.Text("No tasks match these filters.", color=p.MUTED, size=13),
                padding=p.MEDIUM,
            )
        ]

        count.value = f"{len(shown)} {'task' if len(shown) == 1 else 'tasks'}"

        if graph_view.control.visible:
            graph_view.render(selected, highlighted, {task.id for task in shown})

    def select(task: Task | None) -> None:
        nonlocal selected

        selected = task
        on_select(task)
        render(keep_selection=True)

    def show_query_result(task_ids: set[str] | None) -> None:
        nonlocal highlighted

        highlighted = set(task_ids or ())
        query_scope.visible = task_ids is not None
        filters.set_query_override(query_scope.visible)
        render(keep_selection=True)

    def set_tasks(records: tuple[Task, ...]) -> None:
        nonlocal tasks, selected

        tasks = records
        graph_view.set_tasks(records)
        selected = None
        highlighted.clear()
        query_scope.visible = False
        filters.set_query_override(False)
        filters.dismiss()
        filters.set_owners(records)
        on_select(None)
        render()

    headers: list[ft.Control] = [
        ft.Text(label, size=12, color=p.MUTED, width=width, expand=width is None)
        for label, width in (
            ("Task", None),
            ("Owner", 62),
            ("Deadline", 122),
            ("Priority", 50),
            ("Downstream", 76),
            ("Flag", 84),
        )
    ]
    header_row = bordered_row(table_row(headers), height=34)

    def resize(event: ft.LayoutSizeChangeEvent) -> None:
        nonlocal compact, narrow

        new_compact = event.width < 610
        new_narrow = event.width < 470
        gutter = p.MEDIUM if new_compact else p.GUTTER
        available = max(0, event.width - 2 * gutter - p.CONTROL_HEIGHT - p.SMALL)
        filters.resize_search(available)
        control.padding = ft.Padding.symmetric(vertical=p.LARGE, horizontal=gutter)

        if (compact, narrow) != (new_compact, new_narrow):
            compact, narrow = new_compact, new_narrow
            header_row.content = table_row(headers)
            render(keep_selection=True)

    def resize_list_area(event: ft.LayoutSizeChangeEvent) -> None:
        filters.resize_popover(event.height)

    table = ft.Column([header_row, rows], spacing=0, expand=True)
    list_content = ft.Column([impact_callout, table, count], spacing=p.MEDIUM)
    list_area = ft.Stack(
        [list_content],
        expand=True,
        fit=ft.StackFit.EXPAND,
    )

    def show_view(use_graph: bool) -> None:
        filters.dismiss()
        list_area.visible = not use_graph
        graph_view.control.visible = use_graph
        list_style.bgcolor = ft.Colors.TRANSPARENT if use_graph else p.SURFACE
        graph_style.bgcolor = p.SURFACE if use_graph else ft.Colors.TRANSPARENT
        list_style.color = p.MUTED if use_graph else p.TEXT
        graph_style.color = p.TEXT if use_graph else p.MUTED

        for surface in gesture_surfaces:
            surface.active = use_graph

        render(keep_selection=True)

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
