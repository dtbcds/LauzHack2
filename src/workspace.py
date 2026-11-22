"""Compose the task list, organisation sidebar, and Queries panel."""

from collections.abc import Mapping
from functools import partial

import flet as ft

import palette
from ask import ask_panel
from board import task_board
from component import Task, task_detail
from side_panel import SidePanel


def mount_workspace(page: ft.Page, organisations: Mapping[str, tuple[Task, ...]]) -> None:
    organisation = next(iter(organisations))

    sidebar_width = 56

    active_task: Task | None = None

    asking = False
    ask_content: ft.Column | None = None
    query_task_ids: set[str] | None = None

    side_panel = SidePanel(lambda: close_peek())

    def refresh_peek() -> None:
        if asking:
            content = ask_content
        else:
            content = task_detail(active_task, board.select) if active_task else None

        ask_style.bgcolor = palette.SELECTED if asking else palette.CONTROL
        side_panel.show(content)

    def show_task(task: Task | None) -> None:
        nonlocal active_task, asking

        active_task = task
        if task is not None and asking:
            asking = False
            board.show_query_result(None)

        if not asking:
            refresh_peek()

    def close_peek() -> None:
        nonlocal asking

        board.dismiss_filters()
        if asking:
            asking = False
            board.show_query_result(None)

            refresh_peek()
        else:
            board.select(None)

    def highlight_query(task_ids: set[str] | None) -> None:
        nonlocal query_task_ids
        query_task_ids = task_ids

        if asking:
            board.show_query_result(task_ids)

    def toggle_ask() -> None:
        nonlocal asking, ask_content

        if asking:
            close_peek()
            return

        board.dismiss_filters()
        if ask_content is None:
            ask_content = ask_panel(organisations[organisation], close_peek, highlight_query, board.select)

        asking = True
        board.show_query_result(query_task_ids)

        refresh_peek()

    ask_style = palette.control_button_style()
    ask_button = ft.TextButton(
        "Queries",
        icon=ft.Icons.QUERY_STATS,
        tooltip="Run a predefined dependency query",
        style=ask_style,
        on_click=toggle_ask,
    )
    board = task_board(organisations[organisation], show_task, ask_button)

    def select_organisation(name: str) -> None:
        nonlocal organisation, asking, ask_content, query_task_ids

        if name == organisation:
            board.dismiss_filters()

            return

        organisation = name

        asking = False
        ask_content = None
        query_task_ids = None

        board.set_tasks(organisations[name])

        for item in org_buttons:
            item.selected = item.data == name
            item.bgcolor = palette.SELECTED if item.selected else ft.Colors.TRANSPARENT

    org_icons = {
        "Finance Operations": ft.Icons.ACCOUNT_BALANCE_OUTLINED,
        "Product Operations": ft.Icons.WIDGETS_OUTLINED,
    }
    org_buttons = []

    for name in organisations:
        icon = org_icons.get(name, ft.Icons.BUSINESS_OUTLINED)
        org_buttons.append(
            ft.IconButton(
                icon=icon,
                selected_icon=icon,
                tooltip=name,
                data=name,
                selected=name == organisation,
                icon_size=20,
                width=36,
                height=36,
                icon_color=palette.MUTED,
                selected_icon_color=palette.ACCENT,
                bgcolor=(palette.SELECTED if name == organisation else ft.Colors.TRANSPARENT),
                style=ft.ButtonStyle(padding=0, shape=ft.RoundedRectangleBorder(radius=7)),
                on_click=partial(select_organisation, name),
            )
        )

    sidebar = ft.Container(
        ft.Column(
            org_buttons,
            spacing=palette.SMALL,
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            scroll=ft.ScrollMode.AUTO,
        ),
        width=sidebar_width,
        padding=ft.Padding.only(top=palette.MEDIUM),
        bgcolor=palette.SURFACE,
        border=ft.Border(right=ft.BorderSide(1, palette.DIVIDER)),
    )

    def handle_keyboard(event: ft.KeyboardEvent) -> None:
        if event.key != "Escape":
            return

        if board.dismiss_filters():
            return

        if asking or active_task is not None:
            close_peek()

    page.on_keyboard_event = handle_keyboard
    switcher_height = palette.CONTROL_HEIGHT + 2 * palette.MEDIUM + 6
    board.control.margin = ft.Margin.only(top=switcher_height)
    board_surface = board.gesture_surface(board.control, expand=True)
    switcher_surface = board.gesture_surface(
        board.view_switch,
        width=board.view_switch.width,
        height=board.view_switch.height,
    )

    workspace = side_panel.wrap(board_surface, switcher_surface, sidebar_width=sidebar_width)

    page.add(
        ft.Container(
            ft.Row(
                [sidebar, workspace],
                spacing=0,
                vertical_alignment=ft.CrossAxisAlignment.STRETCH,
            ),
            expand=True,
            bgcolor=ft.Colors.TRANSPARENT,
            on_click=board.dismiss_filters,
        )
    )
