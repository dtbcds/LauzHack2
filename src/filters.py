"""Task filtering, sorting, and the controls that drive the list."""

from collections.abc import Callable
from dataclasses import dataclass

import flet as ft

import palette as p
from component import Task

SORT_KEYS: dict[str, Callable[[Task], float | str]] = {
    "Priority": lambda task: -task.score,
    "Dependency impact": lambda task: -task.downstream_count,
    "People affected": lambda task: -task.affected_people,
    "Deadline": lambda task: task.deadline or "9999",
}

COMPLETED_STATUSES = {"done", "complete", "completed"}


def is_blocked(task: Task, tasks: tuple[Task, ...]) -> bool:
    """Whether an unfinished hard prerequisite prevents this task from starting."""
    references = task.blocking_prerequisites
    if references is None:
        references = task.prerequisites
    by_id = {record.id: record for record in tasks}
    by_title = {record.title: record for record in tasks}
    for reference in references:
        prerequisite = by_id.get(reference) or by_title.get(reference)
        if prerequisite is None or prerequisite.status.casefold() not in COMPLETED_STATUSES:
            return True
    return False


def visible_tasks(
    tasks: tuple[Task, ...],
    query: str = "",
    owner: str = "All",
    sort_by: str = "Priority",
    bottlenecks_only: bool = False,
    *,
    min_priority: int = 0,
    min_downstream: int = 0,
    min_people: int = 0,
    bottleneck: bool | None = None,
) -> list[Task]:
    query = query.casefold().strip()
    filtered = [
        task
        for task in tasks
        if (query in task.title.casefold() or query in task.description.casefold())
        and (owner == "All" or task.owner == owner)
        and (not bottlenecks_only or task.bottleneck)
        and (bottleneck is None or task.bottleneck == bottleneck)
        and task.score >= min_priority
        and task.downstream_count >= min_downstream
        and task.affected_people >= min_people
    ]

    return sorted(filtered, key=SORT_KEYS[sort_by])


@dataclass(frozen=True)
class TaskFilters:
    toolbar: ft.Row
    popover: ft.Container
    dismiss_area: ft.Container
    dismiss: Callable[[], bool]
    set_owners: Callable[[tuple[Task, ...]], None]
    resize_search: Callable[[float], None]
    resize_popover: Callable[[float], None]
    set_query_override: Callable[[bool], None]
    matching_tasks: Callable[[tuple[Task, ...]], list[Task]]
    selected_owner: Callable[[], str]


def task_filters(tasks: tuple[Task, ...], on_change: Callable[[], None]) -> TaskFilters:
    query_override = False

    search = ft.TextField(
        hint_text="Search tasks",
        prefix_icon=ft.Icons.SEARCH,
        width=240,
        dense=True,
        border=p.INPUT_BORDER,
        text_size=p.CONTROL_TEXT,
        filled=True,
        fill_color=p.CONTROL,
        height=p.CONTROL_HEIGHT,
        content_padding=ft.Padding.symmetric(horizontal=12),
        text_vertical_align=ft.VerticalAlignment.CENTER,
    )

    def owner_choices(records: tuple[Task, ...]) -> dict[str, str]:
        owners = sorted({task.owner for task in records if task.owner})
        choices = {"All": "All owners"}

        for name in owners:
            choices[name] = name

        return choices

    owner, replace_owners = p.select_menu(
        "Owner",
        owner_choices(tasks),
        on_change,
        value="All",
    )

    sort, _replace_sort_choices = p.select_menu(
        "Sort tasks", {key: key for key in SORT_KEYS}, on_change, value="Priority"
    )

    flag_values = {"any": None, "yes": True, "no": False}
    flag = ft.SegmentedButton(
        selected=["any"],
        show_selected_icon=False,
        segments=[
            ft.Segment(value=key, label=ft.Text(label, size=12))
            for key, label in (("any", "Any"), ("yes", "Yes"), ("no", "No"))
        ],
        style=ft.ButtonStyle(padding=ft.Padding.symmetric(horizontal=p.SMALL)),
    )

    def minimum(label: str) -> tuple[ft.TextField, ft.Row]:
        field = ft.TextField(
            hint_text="Any",
            tooltip=label,
            text_align=ft.TextAlign.CENTER,
            keyboard_type=ft.KeyboardType.NUMBER,
            input_filter=ft.NumbersOnlyInputFilter(),
            collapsed=True,
            border=ft.NoInputBorder(),
            content_padding=0,
            text_size=13,
        )

        box = ft.Container(
            field,
            width=76,
            height=32,
            alignment=ft.Alignment.CENTER,
            bgcolor=p.CONTROL,
            border=ft.Border.all(1, p.DIVIDER),
            border_radius=5,
        )

        def set_focus(focused: bool) -> None:
            box.border = ft.Border.all(1, p.ACCENT if focused else p.DIVIDER)

        field.on_focus = lambda: set_focus(True)
        field.on_blur = lambda: set_focus(False)

        row = ft.Row(
            [ft.Text(label, size=13, color=p.MUTED, expand=True), box],
            spacing=p.MEDIUM,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )

        return field, row

    priority, priority_box = minimum("Min. priority")
    downstream, downstream_box = minimum("Min. downstream")
    people, people_box = minimum("Min. people affected")
    thresholds = (priority, downstream, people)

    clear_button = ft.TextButton(
        "Clear",
        height=32,
        style=ft.ButtonStyle(padding=ft.Padding.symmetric(horizontal=p.SMALL)),
        on_click=lambda: clear_filters(),
    )

    filter_button = ft.IconButton(
        ft.Icons.FILTER_LIST,
        tooltip="Show filters",
        width=p.CONTROL_HEIGHT,
        height=p.CONTROL_HEIGHT,
        icon_size=19,
        icon_color=p.TEXT,
        bgcolor=p.CONTROL,
        style=ft.ButtonStyle(
            padding=0,
            shape=ft.RoundedRectangleBorder(radius=5),
            side=ft.BorderSide(1, p.DIVIDER),
        ),
        on_click=lambda: set_filters_open(not popover.visible),
    )

    popover = ft.Container(
        ft.Column(
            [
                ft.Row(
                    [
                        ft.Text("Filters", size=14, weight=ft.FontWeight.W_600),
                        clear_button,
                    ],
                    alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                ),
                priority_box,
                downstream_box,
                people_box,
                ft.Divider(height=p.SMALL, color=p.DIVIDER),
                ft.Text("Bottleneck status", size=13, color=p.MUTED),
                flag,
            ],
            spacing=p.SMALL,
            tight=True,
            scroll=ft.ScrollMode.AUTO,
        ),
        width=244,
        height=264,
        top=0,
        right=0,
        visible=False,
        bgcolor=p.SURFACE,
        padding=p.SMALL,
        border=ft.Border.all(1, p.DIVIDER),
        border_radius=6,
        shadow=ft.BoxShadow(blur_radius=12, color="#55000000"),
        on_click=lambda: None,  # Keep taps in the popover from reaching the workspace.
    )

    dismiss_area = ft.Container(
        left=0,
        right=0,
        top=0,
        bottom=0,
        visible=False,
        bgcolor=ft.Colors.TRANSPARENT,
        on_click=lambda: dismiss(),
    )

    toolbar_fields = ft.Row(
        [search, owner, sort],
        spacing=p.SMALL,
        run_spacing=p.SMALL,
        wrap=True,
        expand=True,
    )
    toolbar = ft.Row(
        [toolbar_fields, filter_button],
        spacing=p.SMALL,
        vertical_alignment=ft.CrossAxisAlignment.END,
    )

    def set_filters_open(opened: bool) -> None:
        popover.visible = dismiss_area.visible = opened
        filter_button.bgcolor = p.SELECTED if opened else p.CONTROL
        filter_button.tooltip = "Hide filters" if opened else "Show filters"

    def dismiss() -> bool:
        if not popover.visible:
            return False

        set_filters_open(False)
        return True

    search.on_click = search.on_focus = owner.on_open = sort.on_open = dismiss

    def clear_filters() -> None:
        for field in thresholds:
            field.value = ""

        flag.selected = ["any"]
        on_change()

    def set_owners(records: tuple[Task, ...]) -> None:
        replace_owners(owner_choices(records))

    def resize_search(available: float) -> None:
        search.width = available if available < 520 else min(400, available * 0.44)

    def resize_popover(available: float) -> None:
        popover.height = min(264, available)

    def set_query_override(active: bool) -> None:
        nonlocal query_override

        if active:
            dismiss()

        query_override = active
        search.disabled = owner.disabled = filter_button.disabled = active

    def matching_tasks(records: tuple[Task, ...]) -> list[Task]:
        if query_override:
            return visible_tasks(records, sort_by=sort.data)

        bottleneck = flag_values[flag.selected[0]]
        active_filters = sum(bool(field.value) for field in thresholds)

        if bottleneck is not None:
            active_filters += 1

        if active_filters:
            filter_button.badge = ft.Badge(
                label=str(active_filters),
                bgcolor=p.ACCENT,
                text_color=p.BACKGROUND,
            )
        else:
            filter_button.badge = None

        clear_button.disabled = not active_filters

        return visible_tasks(
            records,
            search.value,
            owner.data,
            sort.data,
            min_priority=int(priority.value or 0),
            min_downstream=int(downstream.value or 0),
            min_people=int(people.value or 0),
            bottleneck=bottleneck,
        )

    search.on_change = flag.on_change = on_change

    for field in thresholds:
        field.on_change = on_change

    return TaskFilters(
        toolbar=toolbar,
        popover=popover,
        dismiss_area=dismiss_area,
        dismiss=dismiss,
        set_owners=set_owners,
        resize_search=resize_search,
        resize_popover=resize_popover,
        set_query_override=set_query_override,
        matching_tasks=matching_tasks,
        selected_owner=lambda: "All" if query_override else owner.data,
    )
