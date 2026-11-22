import asyncio
import os
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.coordinator.storage import SubmissionStore
from analysis_data import analysis_message, tasks_from_snapshot

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
    update_analysis = mount_workspace(page, {name: ()}, status_control=status)

    async def follow_analysis() -> None:
        previous = object()
        while True:
            try:
                state = await asyncio.to_thread(store.get_analysis, project, collection)
                if state != previous:
                    snapshot = state.get("result") if state else None
                    tasks = tasks_from_snapshot(snapshot) if snapshot is not None else ()
                    update_analysis(name, tasks, snapshot)
                    status.value = analysis_message(state)
                    status.visible = bool(status.value)
                    previous = state
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
