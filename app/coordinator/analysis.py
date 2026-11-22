"""Convert submitted Calendar events into Dany's task and graph pipeline."""

from __future__ import annotations

import argparse
import json
from collections import OrderedDict
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Callable

from app.coordinator.storage import SubmissionStore


_dependency_cache: OrderedDict[str, tuple[dict[str, Any], ...]] = OrderedDict()


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
    on_progress: Callable[[dict[str, Any], int, int], None] | None = None,
) -> dict[str, Any]:
    """Run the full LLM dependency pass and build UI-ready graph data."""
    from graph_construction import build_graph, graph_to_ui_data

    tasks = [
        event_to_task(event, submission["member_id"])
        for submission in submissions
        for event in submission["events"]
    ]
    dependencies: list[dict[str, Any]] = []

    def publish(completed: int) -> None:
        if on_progress is not None:
            partial = graph_to_ui_data(build_graph(tasks, dependencies))
            on_progress(partial, completed, len(tasks))

    if len(tasks) > 1 and extractor is None:
        from dependency_extraction import cache_namespace, extract_group_dependencies

        model_tasks = [{key: task[key] for key in ("id", "title", "description", "owner")}
                       for task in tasks]
        model_tasks.sort(key=lambda task: task["id"])
        snapshot = cache_namespace() + json.dumps(model_tasks, ensure_ascii=False, sort_keys=True)
        cached = _dependency_cache.get(snapshot)
        if cached is not None:
            _dependency_cache.move_to_end(snapshot)
            dependencies = list(cached)
        else:
            if on_progress:
                on_progress(graph_to_ui_data(build_graph(tasks, [])), 0, 1)
            dependencies = extract_group_dependencies(model_tasks)["dependencies"]
            # Validate the complete graph before caching; real cycles remain errors.
            graph_to_ui_data(build_graph(tasks, dependencies))
            _dependency_cache[snapshot] = tuple(dependencies)
            if len(_dependency_cache) > 8:
                _dependency_cache.popitem(last=False)
        if on_progress:
            on_progress(graph_to_ui_data(build_graph(tasks, dependencies)), 1, 1)
    else:
        publish(0)
        if extractor is not None:
            for index, task in enumerate(tasks, 1):
                candidates = [candidate for candidate in tasks if candidate["id"] != task["id"]]
                if candidates:
                    dependencies.extend(extractor(task, candidates)["dependencies"])
                publish(index)
    graph = build_graph(tasks, dependencies)
    result = graph_to_ui_data(graph)
    if extractor is None:
        from dependency_extraction import cache_namespace
        result["analysis_engine"] = cache_namespace()
    return result


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
