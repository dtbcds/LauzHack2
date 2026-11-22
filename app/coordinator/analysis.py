"""Convert submitted Calendar events into Dany's task and graph pipeline."""

from __future__ import annotations

import argparse
import json
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Callable

from app.coordinator.storage import SubmissionStore


def event_to_task(event: dict[str, Any], member_id: str) -> dict[str, Any]:
    """Make a stable task from an event without inventing its completion status."""
    calendar_id = event.get("calendar_id") or "primary"
    end = event.get("end")
    if not isinstance(end, dict):
        end = {}
    deadline = end.get("dateTime")
    if not deadline and end.get("date"):
        # Google's all-day event end date is exclusive.
        deadline = (date.fromisoformat(end["date"]) - timedelta(days=1)).isoformat()
    title = event.get("summary")
    description = event.get("description")
    return {
        "id": f"{member_id}:{calendar_id}:{event['id']}",
        "title": title if isinstance(title, str) and title else "Untitled calendar event",
        "description": description if isinstance(description, str) else "",
        "owner": member_id,
        "deadline": deadline,
        "status": None,
    }


def analyze_submissions(
    submissions: list[dict[str, Any]],
    extractor: Callable[[dict[str, Any], list[dict[str, Any]]], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Run the full LLM dependency pass and build UI-ready graph data."""
    from graph_construction import build_graph, graph_to_ui_data

    tasks = [
        event_to_task(event, submission["member_id"])
        for submission in submissions
        for event in submission["events"]
    ]
    if len(tasks) > 1 and extractor is None:
        from dependency_extraction import extract_dependencies

        extractor = extract_dependencies
    dependencies: list[dict[str, Any]] = []
    for task in tasks:
        candidates = [candidate for candidate in tasks if candidate["id"] != task["id"]]
        if candidates:
            dependencies.extend(extractor(task, candidates)["dependencies"])
    graph = build_graph(tasks, dependencies)
    return graph_to_ui_data(graph)


def main() -> None:
    parser = argparse.ArgumentParser(description="Show the latest coordinator analysis")
    parser.add_argument("project_id")
    parser.add_argument("collection_id")
    parser.add_argument("--database", type=Path, default=Path("data/coordinator.sqlite3"))
    args = parser.parse_args()
    state = SubmissionStore(args.database).get_analysis(args.project_id, args.collection_id)
    print(json.dumps(state, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
