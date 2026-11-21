"""Resizable right-hand panel, shared by task details and Queries."""

from collections.abc import Callable

import flet as ft

import palette

HANDLE_WIDTH = 12
DOCKED_WORKSPACE_WIDTH = 1000
MIN_LIST_WIDTH = 470
MIN_PANEL_WIDTH = 280


class SidePanel:
    def __init__(self, workspace_width: float, on_close: Callable[[], None]) -> None:
        self._workspace_width = workspace_width
        self._preferred_width: float | None = None
        self._drag_origin: tuple[float, float] | None = None

        self._panel = ft.Container(
            top=0,
            right=0,
            bottom=0,
            bgcolor=palette.SURFACE,
            border=ft.Border(left=ft.BorderSide(1, palette.DIVIDER)),
            visible=False,
        )
        self._reserved_space = ft.Container(visible=False)
        self._backdrop = ft.Container(
            left=0,
            right=0,
            top=0,
            bottom=0,
            bgcolor="#66000000",
            visible=False,
            on_click=on_close,
        )

        self._handle = ft.GestureDetector(
            ft.Container(
                ft.Container(width=2, height=24, bgcolor=palette.MUTED, border_radius=1),
                alignment=ft.Alignment.CENTER,
                bgcolor=ft.Colors.TRANSPARENT,
            ),
            width=HANDLE_WIDTH,
            top=0,
            bottom=0,
            visible=False,
            drag_interval=16,
            mouse_cursor=ft.MouseCursor.RESIZE_LEFT_RIGHT,
            tooltip="Drag to resize side panel",
            on_horizontal_drag_down=self._begin_drag,
            on_horizontal_drag_update=self._drag,
            on_horizontal_drag_end=self._end_drag,
            on_horizontal_drag_cancel=self._cancel_drag,
        )

        self._layout()

    def wrap(self, board: ft.Control) -> ft.Stack:
        workspace = ft.Row(
            [board, self._reserved_space],
            spacing=0,
            vertical_alignment=ft.CrossAxisAlignment.STRETCH,
        )

        return ft.Stack(
            [workspace, self._backdrop, self._panel, self._handle],
            expand=True,
            fit=ft.StackFit.EXPAND,
            on_size_change=self._resize,
        )

    def show(self, content: ft.Control | None) -> None:
        self._panel.content = content
        self._panel.visible = content is not None

        self._layout()

    def _layout(self) -> float:
        width = self._workspace_width
        docked = width >= DOCKED_WORKSPACE_WIDTH
        max_width = width - (MIN_LIST_WIDTH if docked else HANDLE_WIDTH)
        default_width = max(340, min(460, width * 0.31))
        panel_width = min(max_width, max(MIN_PANEL_WIDTH, self._preferred_width or default_width))

        self._panel.width = panel_width
        self._handle.right = panel_width - HANDLE_WIDTH / 2
        self._handle.visible = self._panel.visible

        self._reserved_space.width = panel_width
        self._reserved_space.visible = self._panel.visible and docked
        self._backdrop.visible = self._panel.visible and not docked

        return panel_width

    def _resize(self, event: ft.LayoutSizeChangeEvent) -> None:
        self._workspace_width = event.width

        self._layout()

    def _begin_drag(self, event: ft.DragDownEvent) -> None:
        if self._panel.width is not None:
            self._drag_origin = (event.global_position.x, self._panel.width)

    def _drag(self, event: ft.DragUpdateEvent | ft.DragEndEvent) -> None:
        if self._drag_origin is None:
            return

        start_x, start_width = self._drag_origin
        self._preferred_width = start_width + start_x - event.global_position.x

        self._preferred_width = self._layout()

    def _cancel_drag(self) -> None:
        self._drag_origin = None

    def _end_drag(self, event: ft.DragEndEvent) -> None:
        self._drag(event)
        self._cancel_drag()
