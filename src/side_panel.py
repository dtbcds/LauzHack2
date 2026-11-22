"""Right-hand task and query panel; Flutter owns its resize gesture."""

from collections.abc import Callable

import flet as ft

import palette
from native_motion import ResizableWorkspace


class SidePanel:
    def __init__(self, on_close: Callable[[], None]) -> None:
        self._panel = ft.Container(
            bgcolor=palette.SURFACE,
            border=ft.Border(left=ft.BorderSide(1, palette.DIVIDER)),
        )
        self._workspace = ResizableWorkspace(
            content=ft.Container(), panel=self._panel,
            expand=True, on_close=on_close,
        )

    def wrap(self, board: ft.Control) -> ResizableWorkspace:
        self._workspace.content = board

        return self._workspace

    def show(self, content: ft.Control | None) -> None:
        self._panel.content = content
        self._workspace.panel_open = content is not None
