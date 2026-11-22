from pathlib import Path

import flet as ft

import palette
from demo_data import DEMO_ORGANISATIONS
from workspace import mount_workspace
from native_motion import configure_desktop_client


def main(page: ft.Page) -> None:
    page.title = "Relay"
    page.window.icon = str(Path(__file__).resolve().parents[1] / "assets/relay.ico")
    page.theme_mode = ft.ThemeMode.DARK
    page.theme = ft.Theme(font_family="Segoe UI", color_scheme_seed=palette.ACCENT)
    page.bgcolor = palette.BACKGROUND
    page.padding = 0
    page.spacing = 0

    page.window.width = 1280
    page.window.height = 820
    page.window.min_width = 420
    page.window.min_height = 440

    mount_workspace(page, DEMO_ORGANISATIONS)


if __name__ == "__main__":
    configure_desktop_client()
    ft.run(main)
