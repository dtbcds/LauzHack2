"""Convert graph_to_ui_data output to the records used by list/detail controls."""

from component import Task


def tasks_from_snapshot(snapshot: dict) -> tuple[Task, ...]:
    nodes = {node["id"]: node for node in snapshot["nodes"]}
    upstream = {key: [] for key in nodes}
    downstream = {key: [] for key in nodes}
    evidence = {key: [] for key in nodes}
    for edge in snapshot["edges"]:
        source, target = edge["source"], edge["target"]
        if source not in nodes or target not in nodes:
            raise ValueError("Dependency references an unknown task")
        upstream[target].append(source)
        downstream[source].append(target)
        if edge.get("evidence"):
            evidence[target].append(edge)

    records = []
    for key, node in nodes.items():
        priority, impact = node["priority"], node["impact"]
        supporting = evidence[key]
        records.append(Task(
            id=key, title=node["title"], description=node.get("description") or "",
            owner=node.get("owner_display") or "Unknown", deadline=node.get("deadline"),
            score=priority["priority_score"], status=node.get("status") or "unknown",
            bottleneck=node["is_bottleneck"], downstream_count=impact["downstream_count"],
            affected_people=impact["affected_people"],
            prerequisites=tuple(upstream[key]), dependents=tuple(downstream[key]),
            evidence="\n".join(edge["evidence"] for edge in supporting) or None,
            confidence=(supporting[0].get("confidence") if len(supporting) == 1 else None),
            score_breakdown=tuple(round(priority[field] * weight, 2) for field, weight in (
                ("downstream_component", 40), ("urgency_component", 25),
                ("people_component", 20), ("critical_path_component", 15),
            )),
        ))
    return tuple(records)


def analysis_message(state: dict | None) -> str:
    if state is None:
        return "Waiting for Calendar uploads."
    status = state["status"]
    if status == "ready":
        return ""  # An empty ready snapshot is a valid result too.
    result = state.get("result")
    progress = result.get("analysis_progress") if isinstance(result, dict) else None
    if status == "processing" and isinstance(progress, dict):
        return "Analysing group dependencies with OpenAI…" if progress['total'] == 1 else (
            f"Building graph: {progress['completed']}/{progress['total']} tasks checked. "
            "Links appear as they are found.")
    message = {
        "pending": "Analysis queued.", "processing": "Analysing Calendar events…",
        "failed": f"Analysis failed: {state.get('error') or 'Unknown error'}",
    }.get(status, "Waiting for analysis.")
    if result is not None:
        message += " Showing the partial graph." if progress else " Showing the previous graph."
    return message


def refresh_message(state: dict) -> str:
    if not state["revision"]:
        return ""
    members = state["members"]
    if not members:
        return "No members need to send a Calendar refresh."
    waiting = [member for member, status in members.items() if status != "received"]
    received = len(members) - len(waiting)
    if waiting:
        return f"Calendar refresh: {received}/{len(members)} received. Waiting for: {', '.join(waiting)}."
    return f"Calendar refresh: all {received} members received."
