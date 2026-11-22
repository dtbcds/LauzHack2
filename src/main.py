import argparse
import asyncio
import getpass
import os
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.calendar.personal import PersonalCalendar
from app.calendar.group import GroupCalendar, GroupConnection
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
    mode = os.environ.get("RELAY_MODE", "coordinator")
    member_label = os.environ.get("RELAY_MEMBER_ID", "").strip()
    mode_label = "Group host" if mode == "group-host" else "Group" if mode == "group" else "Personal" if mode == "personal" else "Coordinator"
    page.title = f"Relay — {mode_label}" + (f" ({member_label})" if member_label else "")
    print(f"Relay mode: {mode}; member: {member_label or 'none'}; project: {project}/{collection}.", flush=True)
    personal = None
    group = None
    if mode in ("group", "group-host"):
        member = os.environ.get("RELAY_MEMBER_ID", "").strip()
        if not member:
            raise ValueError("Set RELAY_MEMBER_ID to your member ID")
        host_store = SubmissionStore(database) if mode == "group-host" else None
        connection = GroupConnection(
            project, collection, member,
            url=os.environ.get("RELAY_COORDINATOR_URL"),
            secret=getpass.getpass("Your member upload secret: ") if host_store is None else None,
            ca_cert=os.environ.get("RELAY_CA_CERT", str(ROOT / "data/coordinator.crt")) if host_store is None else None,
            host_store=host_store,
        )
        # Keep member analysis in a different DB from the host's uploaded snapshots.
        import hashlib
        key = hashlib.sha256(member.encode()).hexdigest()[:16]
        cache = ROOT / "data" / f"group-{key}.sqlite3"
        group = GroupCalendar(connection, cache, credentials=str(ROOT / "credentials.json"))
    if mode == "personal":
        personal = PersonalCalendar(
            os.environ.get("RELAY_MEMBER_ID", ""), database,
            credentials=str(ROOT / "credentials.json"),
        )
        project, collection = personal.project_id, personal.collection_id
    store = group.store if group else personal.store if personal else SubmissionStore(database)
    name = "My Calendar" if personal else project
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
            if group:
                await asyncio.to_thread(group.refresh)
                refresh_status.value = group.message
            elif personal:
                refresh_status.value = "Fetching your Calendar and analysing dependencies…"
                refresh_status.visible = True
                page.update()
                await asyncio.to_thread(personal.sync)
                refresh_status.value = "Calendar fetched."
            else:
                progress = await asyncio.to_thread(
                    request_collection_refresh, project, collection, database=database,
                )
                refresh_status.value = refresh_message(progress)
        except Exception as error:
            refresh_error = f"Could not request refresh: {error}"
            refresh_status.value = refresh_error
        finally:
            refresh_status.visible = bool(refresh_status.value)
            refresh_button.disabled = False
            page.update()

    refresh_button = ft.TextButton(
        "Refresh", icon=ft.Icons.REFRESH,
        tooltip="Refresh group Calendars" if group else "Fetch my Calendar" if personal else "Ask members to sync their Calendars",
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
                state = (await asyncio.to_thread(group.view) if group else
                         await asyncio.to_thread(personal.view) if personal else
                         await asyncio.to_thread(store.get_analysis, project, collection))
                progress = ({} if personal or group else
                            await asyncio.to_thread(store.get_refresh_status, project, collection))
                changed = progress != previous_progress
                if group:
                    group_message = refresh_error or group.message
                    if refresh_status.value != group_message:
                        refresh_status.value = group_message
                        refresh_status.visible = bool(group_message)
                        changed = True
                if changed and not personal and not group:
                    refresh_status.value = refresh_error or refresh_message(progress)
                    refresh_status.visible = bool(refresh_status.value)
                    previous_progress = progress
                previous_progress = progress
                if state != previous:
                    snapshot = state.get("result") if state else None
                    tasks = tasks_from_snapshot(snapshot) if snapshot is not None else ()
                    update_analysis(name, tasks, snapshot)
                    status.value = analysis_message(state)
                    if personal and state and state["status"] != "ready":
                        status.value = (f"Dependency analysis failed: {state['error']}" if state["status"] == "failed"
                                        else "Analysing dependencies…") + " Showing your Calendar items."
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

    async def sync_group() -> None:
        while True:
            try:
                await asyncio.to_thread(group.poll)
            except Exception as error:
                group.message = f"Group sync failed: {error}. Retrying…"
            await asyncio.sleep(3)

    async def analyze_group() -> None:
        while True:
            await asyncio.to_thread(group.analyze_pending)
            await asyncio.sleep(1)

    page.run_task(follow_analysis)
    if group:
        page.run_task(sync_group)
        page.run_task(analyze_group)
    if personal:
        page.run_task(refresh_calendars)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run Relay")
    parser.add_argument("--mode", choices=["coordinator", "personal", "group", "group-host"])
    parser.add_argument("--member-id")
    parser.add_argument("--coordinator-url")
    parser.add_argument("--ca-cert")
    parser.add_argument("--project-id")
    parser.add_argument("--collection-id")
    parser.add_argument("--database")
    args = parser.parse_args()
    for key, value in vars(args).items():
        if value is not None:
            os.environ["RELAY_" + key.upper()] = value
    configure_desktop_client()
    ft.run(main)
