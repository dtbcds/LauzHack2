from dataclasses import dataclass
from collections.abc import Callable

import flet as ft

import palette as p
from component import Task, format_deadline


SORT_KEYS = {
    "Priority": lambda task: -task.score,
    "Dependency impact": lambda task: -task.downstream_count,
    "People affected": lambda task: -task.affected_people,
    "Deadline": lambda task: task.deadline or "9999",
}
TOOLBAR_HEIGHT = p.CONTROL_HEIGHT


def visible_tasks(
    tasks: tuple[Task, ...], query: str = "", owner: str = "All",
    sort_by: str = "Priority", bottlenecks_only: bool = False,
    *, min_priority: int = 0, min_downstream: int = 0, min_people: int = 0,
    bottleneck: bool | None = None,
) -> list[Task]:
    query = query.casefold().strip()
    filtered = [
        task for task in tasks
        if (query in task.title.casefold() or query in task.description.casefold())
        and (owner == "All" or task.owner == owner)
        and (not bottlenecks_only or task.bottleneck)
        and (bottleneck is None or task.bottleneck == bottleneck)
        and task.score >= min_priority
        and task.downstream_count >= min_downstream
        and task.affected_people >= min_people
    ]
    return sorted(filtered, key=SORT_KEYS[sort_by])


@dataclass
class TaskBoard:
    control: ft.Container
    select: Callable[[Task | None], None]
    dismiss_filters: Callable[[], None]
    set_tasks: Callable[[tuple[Task, ...]], None]
    highlight: Callable[[set[str]], None]


def task_board(tasks: tuple[Task, ...], on_select: Callable[[Task | None], None],
               ask_button: ft.Control | None = None) -> TaskBoard:
    selected = None
    highlighted: set[str] = set()
    compact = False
    narrow = False
    rows = ft.ListView(expand=True, spacing=0)
    count = ft.Text(size=12, color=p.MUTED)
    impact_title = ft.Text(size=13, color=p.TEXT, weight=ft.FontWeight.W_600)
    impact_detail = ft.Text(size=12, color=p.MUTED)
    impact_callout = ft.Container(
        ft.Row([
            ft.Icon(ft.Icons.ACCOUNT_TREE_OUTLINED, size=17, color=p.AMBER),
            ft.Column([
                ft.Text("Highest-impact bottleneck", size=12, color=p.AMBER),
                impact_title,
                impact_detail,
            ], spacing=2, expand=True),
            ft.Icon(ft.Icons.CHEVRON_RIGHT, size=16, color=p.MUTED),
        ], spacing=p.SMALL),
        padding=ft.Padding.symmetric(vertical=p.SMALL, horizontal=12),
        bgcolor=p.SURFACE, border=ft.Border.all(1, p.DIVIDER), border_radius=6,
        visible=False, ink=True, tooltip="Open bottleneck details",
    )
    field_style = dict(
        dense=True, border_radius=5, border_color=p.DIVIDER,
        focused_border_color=p.ACCENT, text_size=13, filled=True, fill_color=p.CONTROL,
        height=TOOLBAR_HEIGHT, content_padding=ft.Padding.symmetric(horizontal=12),
        text_vertical_align=ft.VerticalAlignment.CENTER,
    )
    search = ft.TextField(
        hint_text="Search tasks", prefix_icon=ft.Icons.SEARCH, width=240, **field_style,
    )

    def owner_choices(records):
        owners = sorted({task.owner for task in records if task.owner})
        return {"All": "All owners", **{name: name for name in owners}}

    owner, replace_owners = p.select_menu(
        "Filter by owner", owner_choices(tasks), lambda: render(), value="All",
    )
    sort, _ = p.select_menu("Sort tasks", {key: key for key in SORT_KEYS},
                            lambda: render(), value="Priority")
    flag_values = {"any": None, "yes": True, "no": False}
    flag = ft.SegmentedButton(
        selected=["any"], show_selected_icon=False,
        segments=[
            ft.Segment(value=key, label=ft.Text(label, size=12))
            for key, label in (("any", "Any"), ("yes", "Yes"), ("no", "No"))
        ],
        style=ft.ButtonStyle(padding=ft.Padding.symmetric(horizontal=p.SMALL)),
    )

    def minimum(label):
        field = ft.TextField(
            hint_text="Any", tooltip=label, text_align=ft.TextAlign.CENTER,
            keyboard_type=ft.KeyboardType.NUMBER, input_filter=ft.NumbersOnlyInputFilter(),
            collapsed=True, border=ft.InputBorder.NONE, content_padding=0, text_size=13,
        )
        box = ft.Container(
            field, width=76, height=32, alignment=ft.Alignment.CENTER,
            bgcolor=p.CONTROL, border=ft.Border.all(1, p.DIVIDER), border_radius=5,
        )

        def set_focus(focused):
            box.border = ft.Border.all(1, p.ACCENT if focused else p.DIVIDER)

        field.on_focus = lambda _: set_focus(True)
        field.on_blur = lambda _: set_focus(False)
        row = ft.Row(
            [ft.Text(label, size=13, color=p.MUTED, expand=True), box],
            spacing=p.MEDIUM, vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )
        return field, row

    priority, priority_box = minimum("Min. priority")
    downstream, downstream_box = minimum("Min. downstream")
    people, people_box = minimum("Min. people affected")
    thresholds = (priority, downstream, people)
    clear_button = ft.TextButton(
        "Clear", height=32, style=ft.ButtonStyle(padding=ft.Padding.symmetric(horizontal=p.SMALL)),
        on_click=lambda _: clear_filters(),
    )
    filter_button = ft.IconButton(
        ft.Icons.FILTER_LIST, tooltip="Show filters", width=TOOLBAR_HEIGHT,
        height=TOOLBAR_HEIGHT, icon_size=19, icon_color=p.TEXT, bgcolor=p.CONTROL,
        style=ft.ButtonStyle(padding=0, shape=ft.RoundedRectangleBorder(radius=5),
                             side=ft.BorderSide(1, p.DIVIDER)),
        on_click=lambda _: set_filters_open(not popover.visible),
    )
    popover = ft.Container(
        ft.Column([
            ft.Row([ft.Text("Filters", size=14, weight=ft.FontWeight.W_600), clear_button],
                   alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
            priority_box, downstream_box, people_box,
            ft.Divider(height=p.SMALL, color=p.DIVIDER),
            ft.Text("Bottleneck status", size=13, color=p.MUTED),
            flag,
        ], spacing=p.SMALL, tight=True),
        width=244, top=0, right=0, visible=False, bgcolor=p.SURFACE,
        padding=p.SMALL, border=ft.Border.all(1, p.DIVIDER), border_radius=6,
        shadow=ft.BoxShadow(blur_radius=12, color="#55000000"),
        on_click=lambda _: None,  # Keep taps in the popover from reaching the workspace.
    )
    dismiss_area = ft.Container(
        left=0, right=0, top=0, bottom=0, visible=False,
        bgcolor=ft.Colors.TRANSPARENT, on_click=lambda _: set_filters_open(False),
    )
    toolbar_fields = ft.Row([search, owner, sort], spacing=p.SMALL,
                            run_spacing=p.SMALL, wrap=True, expand=True)
    toolbar = ft.Row([toolbar_fields, filter_button], spacing=p.SMALL,
                     vertical_alignment=ft.CrossAxisAlignment.END)

    def set_filters_open(opened: bool):
        popover.visible = dismiss_area.visible = opened
        filter_button.bgcolor = p.SELECTED if opened else p.CONTROL
        filter_button.tooltip = "Hide filters" if opened else "Show filters"

    def dismiss_filters(_=None):
        set_filters_open(False)

    search.on_click = search.on_focus = owner.on_open = sort.on_open = dismiss_filters

    def clear_filters():
        for field in thresholds:
            field.value = ""
        flag.selected = ["any"]
        render()

    def line(cells):
        task, owner_cell, deadline, priority_cell, downstream_cell, flag_cell = cells
        columns = [task]
        if not compact:
            columns.append(owner_cell)
        if not narrow:
            columns.append(deadline)
        columns.extend([priority_cell, downstream_cell])
        if not compact:
            columns.append(flag_cell)
        return ft.Row(columns, spacing=p.SMALL, vertical_alignment=ft.CrossAxisAlignment.CENTER)

    def divider_row(content, **kwargs):
        return ft.Container(
            content, padding=ft.Padding.symmetric(horizontal=p.SMALL),
            border=ft.Border(bottom=ft.BorderSide(1, p.DIVIDER)), **kwargs,
        )

    def task_row(task, *, highest_impact):
        active = selected is not None and selected.id == task.id
        return divider_row(
            line([
                ft.TextButton(
                    content=ft.Row([
                        ft.Text(task.title, size=13,
                                color=p.ACCENT if task.id in highlighted else p.TEXT, expand=True,
                                max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
                        *([ft.Icon(ft.Icons.WARNING_AMBER_ROUNDED, size=15, color=p.AMBER,
                                   tooltip="Bottleneck")] if compact and task.bottleneck else []),
                    ], spacing=p.SMALL),
                    expand=True, tooltip=task.title,
                    style=ft.ButtonStyle(padding=0, alignment=ft.Alignment.CENTER_LEFT),
                    on_click=lambda _: select(task),
                ),
                ft.Text(task.owner or "Unknown", width=62, size=13, color=p.MUTED),
                ft.Text(format_deadline(task.deadline), width=122, size=12, color=p.MUTED),
                ft.Text(str(task.score), width=50, size=13, color=p.TEXT,
                        tooltip="Weighted priority out of 100. Open the task for the breakdown."),
                ft.Text(
                    str(task.downstream_count), width=76, size=13,
                    color=p.AMBER if highest_impact else p.MUTED,
                    weight=ft.FontWeight.W_600 if highest_impact else None,
                    tooltip="Most downstream tasks among visible bottlenecks" if highest_impact else None,
                ),
                ft.Container(
                    p.tag("Bottleneck", highlighted=True) if task.bottleneck else None,
                    width=84, alignment=ft.Alignment.CENTER_LEFT,
                ),
            ]),
            height=42, bgcolor=p.SELECTED if active else p.CONTROL if task.id in highlighted else None,
            ink=True, on_click=lambda _: select(task),
        )

    def render(_=None, *, keep_selection=False):
        nonlocal selected
        bottleneck = flag_values[flag.selected[0]]
        shown = visible_tasks(
            tasks, search.value, owner.data, sort.data,
            min_priority=int(priority.value or 0), min_downstream=int(downstream.value or 0),
            min_people=int(people.value or 0),
            bottleneck=bottleneck,
        )
        if not keep_selection and selected is not None and selected not in shown:
            selected = None
            on_select(None)
        lead = max((task for task in shown if task.bottleneck and task.downstream_count),
                   key=lambda task: (task.downstream_count, task.score), default=None)
        impact_callout.visible = lead is not None
        if lead is not None:
            impact_title.value = lead.title
            impact_detail.value = f"{lead.downstream_count} downstream tasks · {lead.affected_people} people affected"
            impact_callout.on_click = lambda _: select(lead)
        rows.controls = [
            task_row(task, highest_impact=task is lead)
            for task in shown
        ] or [
            ft.Container(ft.Text("No tasks match these filters.", color=p.MUTED, size=13),
                         padding=p.MEDIUM)
        ]
        count.value = f"{len(shown)} {'task' if len(shown) == 1 else 'tasks'}"
        active_filters = sum(bool(field.value) for field in thresholds) + (bottleneck is not None)
        filter_button.badge = (
            ft.Badge(label=str(active_filters), bgcolor=p.ACCENT, text_color=p.BACKGROUND)
            if active_filters else None
        )
        clear_button.disabled = not active_filters

    def select(task):
        nonlocal selected
        selected = task
        on_select(task)
        render(keep_selection=True)

    def highlight(task_ids: set[str]):
        nonlocal highlighted
        highlighted = task_ids
        render(keep_selection=True)

    def set_tasks(records):
        nonlocal tasks, selected
        tasks = records
        selected = None
        highlighted.clear()
        dismiss_filters()
        replace_owners(owner_choices(records))
        on_select(None)
        render()

    search.on_change = flag.on_change = render
    for field in thresholds:
        field.on_change = render
    headers = [
        ft.Text(label, size=12, color=p.MUTED, width=width, expand=width is None)
        for label, width in (("Task", None), ("Owner", 62), ("Deadline", 122),
                             ("Priority", 50), ("Downstream", 76), ("Flag", 84))
    ]
    header_row = divider_row(line(headers), height=34)

    def resize(event: ft.LayoutSizeChangeEvent):
        nonlocal compact, narrow
        new_compact = event.width < 610
        new_narrow = event.width < 470
        gutter = p.MEDIUM if new_compact else p.GUTTER
        available = max(0, event.width - 2 * gutter - TOOLBAR_HEIGHT - p.SMALL)
        search.width = available if available < 520 else min(400, available * 0.44)
        control.padding = ft.Padding.symmetric(vertical=p.LARGE, horizontal=gutter)
        if (compact, narrow) != (new_compact, new_narrow):
            compact, narrow = new_compact, new_narrow
            header_row.content = line(headers)
            render()

    control = ft.Container(
        ft.Column([
            ft.Text("Tasks", size=36, weight=ft.FontWeight.W_700, color=p.TEXT),
            ft.Row([
                ft.Icon(ft.Icons.VIEW_LIST_OUTLINED, size=16, color=p.ACCENT),
                ft.Text("List", size=13, color=p.TEXT),
                ft.Container(expand=True),
                *([ask_button] if ask_button is not None else []),
            ], spacing=p.SMALL),
            toolbar,
            ft.Stack([
                ft.Column([
                    impact_callout,
                    ft.Column([header_row, rows], spacing=0, expand=True),
                    count,
                ], spacing=p.MEDIUM),
                dismiss_area,
                popover,
            ], expand=True, fit=ft.StackFit.EXPAND),
        ], spacing=p.MEDIUM),
        padding=ft.Padding.symmetric(vertical=p.LARGE, horizontal=p.GUTTER),
        expand=True,
        on_size_change=resize,
    )
    render()
    return TaskBoard(control, select, dismiss_filters, set_tasks, highlight)
