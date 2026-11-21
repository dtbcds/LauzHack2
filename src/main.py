import flet as ft

import palette
from board import task_board
from component import Task, task_detail
from demo_data import DEMO_ORGANISATIONS


def main(page: ft.Page):
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
    preferred_peek_width = None
    drag_origin: tuple[float, float] | None = None
    peek = ft.Container(
        top=0, right=0, bottom=0, bgcolor=palette.SURFACE,
        border=ft.Border(left=ft.BorderSide(1, palette.DIVIDER)), visible=False,
    )
    reserved_space = ft.Container(visible=False)
    backdrop = ft.Container(left=0, right=0, top=0, bottom=0, bgcolor="#66000000",
                            visible=False, on_click=lambda _: board.select(None))
    handle = ft.GestureDetector(
        ft.Container(
            ft.Container(width=2, height=24, bgcolor=palette.MUTED, border_radius=1),
            alignment=ft.Alignment.CENTER, bgcolor=ft.Colors.TRANSPARENT,
        ),
        width=12, top=0, bottom=0, visible=False, drag_interval=16,
        mouse_cursor=ft.MouseCursor.RESIZE_LEFT_RIGHT, tooltip="Drag to resize task details",
    )

    def layout_detail():
        docked = width >= 1000
        max_width = width - (470 if docked else 12)
        default_width = max(340, min(460, width * 0.31))
        peek.width = min(max_width, max(280, preferred_peek_width or default_width))
        handle.right = peek.width - handle.width / 2
        handle.visible = peek.visible
        reserved_space.width = peek.width
        reserved_space.visible = peek.visible and docked
        backdrop.visible = peek.visible and not docked

    def begin_drag(event: ft.DragDownEvent):
        nonlocal drag_origin
        drag_origin = (event.global_position.x, peek.width)

    def drag_detail(event: ft.DragUpdateEvent | ft.DragEndEvent):
        nonlocal preferred_peek_width
        if drag_origin is None:
            return
        start_x, start_width = drag_origin
        preferred_peek_width = start_width + start_x - event.global_position.x
        layout_detail()
        preferred_peek_width = peek.width

    def cancel_drag(_=None):
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

    def show_task(task: Task | None):
        peek.visible = task is not None
        peek.content = task_detail(task, board.select) if task else None
        layout_detail()

    board = task_board(organisations[organisation], show_task)

    def select_organisation(name: str):
        nonlocal organisation
        if name == organisation:
            board.dismiss_filters()
            return
        organisation = name
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
        org_buttons.append(ft.IconButton(
            icon=icon, selected_icon=icon, tooltip=name, data=name,
            selected=name == organisation, icon_size=20, width=36, height=36,
            icon_color=palette.MUTED, selected_icon_color=palette.ACCENT,
            bgcolor=palette.SELECTED if name == organisation else ft.Colors.TRANSPARENT,
            style=ft.ButtonStyle(padding=0, shape=ft.RoundedRectangleBorder(radius=7)),
            on_click=lambda _, name=name: select_organisation(name),
        ))
    sidebar = ft.Container(
        ft.Column(org_buttons, spacing=palette.SMALL,
                  horizontal_alignment=ft.CrossAxisAlignment.CENTER, scroll=ft.ScrollMode.AUTO),
        width=sidebar_width, padding=ft.Padding.only(top=palette.MEDIUM),
        bgcolor=palette.SURFACE, border=ft.Border(right=ft.BorderSide(1, palette.DIVIDER)),
    )

    def handle_keyboard(event: ft.KeyboardEvent):
        if event.key == "Escape":
            board.dismiss_filters()

    page.on_keyboard_event = handle_keyboard
    layout_detail()
    workspace = ft.Stack([
        ft.Row([board.control, reserved_space], spacing=0,
               vertical_alignment=ft.CrossAxisAlignment.STRETCH),
        backdrop, peek, handle,
    ], expand=True, fit=ft.StackFit.EXPAND, on_size_change=resize)
    page.add(ft.Row([sidebar, workspace], spacing=0, expand=True,
                    vertical_alignment=ft.CrossAxisAlignment.STRETCH))


if __name__ == "__main__":
    ft.run(main)
