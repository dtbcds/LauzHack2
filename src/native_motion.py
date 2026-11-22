"""Flet controls whose continuous interaction state belongs to Flutter."""

import os
from pathlib import Path

import flet as ft


@ft.control("GraphViewport")
class GraphViewport(ft.LayoutControl):
    content: ft.Control
    channel: str
    scene_width: float = 1
    scene_height: float = 1
    node_height: float = 120
    node_width: float = 208
    horizontal: bool = True
    reset_token: int = 0
    zoom: float = 1
    scroll_top: float = 0
    scroll_left: float = 0


@ft.control("GraphToolbar")
class GraphToolbar(ft.LayoutControl):
    channel: str


@ft.control("GraphGestureSurface")
class GraphGestureSurface(ft.LayoutControl):
    content: ft.Control
    channel: str
    active: bool = False


@ft.control("ResizableWorkspace")
class ResizableWorkspace(ft.LayoutControl):
    content: ft.Control
    panel: ft.Control
    overlay: ft.Control | None = None
    overlay_width: float = 278
    overlay_center_offset: float = 0
    panel_open: bool = False
    panel_width: float | None = None
    on_close: ft.ControlEventHandler | None = None


@ft.control("SettledSize")
class SettledSize(ft.LayoutControl):
    content: ft.Control
    on_settled: ft.EventHandler[ft.LayoutSizeChangeEvent] | None = None


def configure_desktop_client() -> None:
    """Use the locally built client for the extension, including debugpy launches."""
    client = (
        Path(__file__).resolve().parents[1]
        / "build/native_client/build/windows/x64/runner/Release"
    )
    if not (client / "flet.exe").is_file():
        raise RuntimeError("Build the motion controls first: .\\tools\\build-client.ps1")

    os.environ["FLET_VIEW_PATH"] = str(client)
