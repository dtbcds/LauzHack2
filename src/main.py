import asyncio
import os
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.coordinator.storage import SubmissionStore
from app.coordinator.refresh import request_collection_refresh
from analysis_data import analysis_message, refresh_message, tasks_from_snapshot

import flet as ft

import palette
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

    project = os.environ.get("RELAY_PROJECT_ID", "demo")
    collection = os.environ.get("RELAY_COLLECTION_ID", "round-1")
    database = Path(os.environ.get("RELAY_DATABASE", str(ROOT / "data/coordinator.sqlite3")))
    store = SubmissionStore(database)
    name = project
    status = ft.Text(color=palette.MUTED, visible=False)
    refresh_status = ft.Text(color=palette.MUTED, visible=False)
    refresh_error = None

    async def refresh_calendars() -> None:
        nonlocal refresh_error
        if refresh_button.disabled:
            return
        refresh_button.disabled = True
        refresh_error = None
        page.update()
        try:
            progress = await asyncio.to_thread(
                request_collection_refresh, project, collection, database=database,
            )
            refresh_status.value = refresh_message(progress)
        except (sqlite3.Error, OSError, ValueError) as error:
            refresh_error = f"Could not request refresh: {error}"
            refresh_status.value = refresh_error
        finally:
            refresh_status.visible = bool(refresh_status.value)
            refresh_button.disabled = False
            page.update()

    refresh_button = ft.TextButton(
        "Refresh", icon=ft.Icons.REFRESH,
        tooltip="Ask members to sync their Calendars",
        style=palette.control_button_style(), on_click=refresh_calendars,
    )
    update_analysis = mount_workspace(
        page, {name: ()}, status_control=ft.Column([refresh_status, status], spacing=4),
        refresh_control=refresh_button,
    )

    async def follow_analysis() -> None:
        previous = object()
        previous_progress = object()
        while True:
            try:
                state = await asyncio.to_thread(store.get_analysis, project, collection)
                progress = await asyncio.to_thread(store.get_refresh_status, project, collection)
                changed = progress != previous_progress
                if changed:
                    refresh_status.value = refresh_error or refresh_message(progress)
                    refresh_status.visible = bool(refresh_status.value)
                    previous_progress = progress
                if state != previous:
                    snapshot = state.get("result") if state else None
                    tasks = tasks_from_snapshot(snapshot) if snapshot is not None else ()
                    update_analysis(name, tasks, snapshot)
                    status.value = analysis_message(state)
                    status.visible = bool(status.value)
                    previous = state
                    changed = True
                if changed:
                    page.update()
            except (sqlite3.Error, ValueError, KeyError, TypeError) as error:
                status.value = f"Cannot load analysis: {error}"
                status.visible = True
                page.update()
            await asyncio.sleep(1)

    page.run_task(follow_analysis)


if __name__ == "__main__":
    configure_desktop_client()
    ft.run(main)
