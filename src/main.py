from functools import partial

import flet as ft

import palette
from ask import ask_panel
from board import task_board
from component import Task, task_detail
from demo_data import DEMO_ORGANISATIONS


def main(page: ft.Page) -> None:
    page.title = "Dependency Intelligence"
    page.theme_mode = ft.ThemeMode.DARK
    page.theme = ft.Theme(font_family="Segoe UI", color_scheme_seed=palette.ACCENT)
    page.bgcolor = palette.BACKGROUND
    page.padding = 0
    page.spacing = 0

    page.window.width = 1280
    page.window.height = 820
    page.window.min_width = 420
    page.window.min_height = 440

    organisations = DEMO_ORGANISATIONS
    organisation = next(iter(organisations))

    sidebar_width = 56
    width = (page.width or 1280) - sidebar_width

    preferred_peek_width: float | None = None
    drag_origin: tuple[float, float] | None = None

    active_task: Task | None = None

    asking = False
    ask_content: ft.Column | None = None
    query_task_ids: set[str] | None = None

    peek = ft.Container(
        top=0,
        right=0,
        bottom=0,
        bgcolor=palette.SURFACE,
        border=ft.Border(left=ft.BorderSide(1, palette.DIVIDER)),
        visible=False,
    )
    reserved_space = ft.Container(visible=False)
    backdrop = ft.Container(
        left=0,
        right=0,
        top=0,
        bottom=0,
        bgcolor="#66000000",
        visible=False,
        on_click=lambda: close_peek(),
    )

    handle_width = 12
    handle = ft.GestureDetector(
        ft.Container(
            ft.Container(width=2, height=24, bgcolor=palette.MUTED, border_radius=1),
            alignment=ft.Alignment.CENTER,
            bgcolor=ft.Colors.TRANSPARENT,
        ),
        width=handle_width,
        top=0,
        bottom=0,
        visible=False,
        drag_interval=16,
        mouse_cursor=ft.MouseCursor.RESIZE_LEFT_RIGHT,
        tooltip="Drag to resize side panel",
    )

    def layout_detail():
        docked = width >= 1000
        max_width = width - (470 if docked else 12)
        default_width = max(340, min(460, width * 0.31))
        panel_width = min(max_width, max(280, preferred_peek_width or default_width))

        peek.width = panel_width
        handle.right = panel_width - handle_width / 2
        handle.visible = peek.visible
        reserved_space.width = panel_width
        reserved_space.visible = peek.visible and docked
        backdrop.visible = peek.visible and not docked

        return panel_width

    def begin_drag(event: ft.DragDownEvent):
        nonlocal drag_origin

        if peek.width is not None:
            drag_origin = (event.global_position.x, peek.width)

    def drag_detail(event: ft.DragUpdateEvent | ft.DragEndEvent):
        nonlocal preferred_peek_width

        if drag_origin is None:
            return

        start_x, start_width = drag_origin
        preferred_peek_width = start_width + start_x - event.global_position.x
        preferred_peek_width = layout_detail()

    def cancel_drag() -> None:
        nonlocal drag_origin

        drag_origin = None

    def end_drag(event: ft.DragEndEvent):
        drag_detail(event)
        cancel_drag()

    handle.on_horizontal_drag_down = begin_drag
    handle.on_horizontal_drag_update = drag_detail
    handle.on_horizontal_drag_end = end_drag
    handle.on_horizontal_drag_cancel = cancel_drag

    def resize(event: ft.LayoutSizeChangeEvent):
        nonlocal width

        width = event.width

        layout_detail()

    def refresh_peek():
        peek.visible = asking or active_task is not None

        if asking:
            peek.content = ask_content
        else:
            peek.content = task_detail(active_task, board.select) if active_task else None

        ask_style.bgcolor = palette.SELECTED if asking else palette.CONTROL

        layout_detail()

    def show_task(task: Task | None):
        nonlocal active_task, asking

        active_task = task
        if task is not None and asking:
            asking = False
            board.show_query_result(None)

        if not asking:
            refresh_peek()

    def close_peek():
        nonlocal asking

        board.dismiss_filters()
        if asking:
            asking = False
            board.show_query_result(None)

            refresh_peek()
        else:
            board.select(None)

    def highlight_query(task_ids: set[str] | None):
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

    def select_organisation(name: str):
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
        "Product Operations": ft.Icons.INVENTORY_2_OUTLINED,
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

    def handle_keyboard(event: ft.KeyboardEvent):
        if event.key != "Escape":
            return

        if board.dismiss_filters():
            return

        if asking or active_task is not None:
            close_peek()

    page.on_keyboard_event = handle_keyboard
    layout_detail()

    workspace = ft.Stack(
        [
            ft.Row(
                [board.control, reserved_space],
                spacing=0,
                vertical_alignment=ft.CrossAxisAlignment.STRETCH,
            ),
            backdrop,
            peek,
            handle,
        ],
        expand=True,
        fit=ft.StackFit.EXPAND,
        on_size_change=resize,
    )

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


if __name__ == "__main__":
    ft.run(main)
