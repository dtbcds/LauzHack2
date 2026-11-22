"""Build and validate a directed task dependency graph."""

from datetime import date, datetime, timezone

import networkx as nx


def build_graph(tasks, dependencies):
    """Return a DAG where prerequisite tasks point to their dependents."""
    graph = nx.DiGraph()
    if not isinstance(tasks, list) or any(not isinstance(task, dict) for task in tasks):
        raise ValueError("Tasks must be a list of objects")
    task_ids = [task.get("id") for task in tasks]
    if any(not isinstance(task_id, str) or not task_id for task_id in task_ids):
        raise ValueError("Task IDs must be nonempty strings")
    if len(task_ids) != len(set(task_ids)):
        duplicates = sorted({task_id for task_id in task_ids if task_ids.count(task_id) > 1})
        raise ValueError(f"Duplicate task IDs: {duplicates}")

    for task in tasks:
        task_id = task["id"]
        attributes = {**task, "task_id": task_id}
        graph.add_node(task_id, **attributes)

    if isinstance(dependencies, dict):
        dependencies = dependencies.get("dependencies", [])
    if not isinstance(dependencies, list) or any(not isinstance(item, dict) for item in dependencies):
        raise ValueError("Dependencies must be a list of objects")

    for dependency in dependencies:
        kind = dependency.get("type")
        if kind == "none":
            continue
        prerequisite = dependency.get("prerequisite_task_id")
        dependent = dependency.get("dependent_task_id")
        if prerequisite not in graph or dependent not in graph:
            continue
        if prerequisite == dependent:
            raise ValueError(f"Self-dependency for task: {prerequisite}")
        if kind not in ("hard", "soft"):
            continue
        if graph.has_edge(prerequisite, dependent):
            if graph.edges[prerequisite, dependent]["type"] != kind:
                raise ValueError(f"Conflicting dependency for tasks: {prerequisite}, {dependent}")
            continue
        graph.add_edge(
            prerequisite,
            dependent,
            type=kind,
            weight=1.0 if kind == "hard" else 0.5,
            evidence=dependency.get("evidence"),
            confidence=dependency.get("confidence"),
        )

    cycle_tasks = sorted(
        task_id
        for component in nx.strongly_connected_components(graph)
        if len(component) > 1
        for task_id in component
    )
    if cycle_tasks:
        raise ValueError(f"Circular dependencies involve tasks: {cycle_tasks}")
    return graph


def calculate_downstream_impact(graph):
    """Calculate direct, reachable, weighted, and owner impact per task."""
    order = list(nx.topological_sort(graph))
    impacts = {}
    for task_id in graph:
        strongest_path = {task_id: 1.0}
        for node in order:
            if node not in strongest_path:
                continue
            for dependent, attributes in graph[node].items():
                contribution = strongest_path[node] * attributes["weight"]
                if contribution > strongest_path.get(dependent, 0):
                    strongest_path[dependent] = contribution

        downstream = set(strongest_path) - {task_id}
        owner = graph.nodes[task_id].get("owner")
        downstream_owners = {
            graph.nodes[node].get("owner")
            for node in downstream
            if graph.nodes[node].get("owner") != owner
            and graph.nodes[node].get("owner") is not None
            and (
                not isinstance(graph.nodes[node].get("owner"), str)
                or graph.nodes[node].get("owner").strip().lower() not in ("", "unknown")
            )
        }
        impacts[task_id] = {
            "direct_dependents": graph.out_degree(task_id),
            "downstream_count": len(downstream),
            "weighted_downstream_impact": sum(strongest_path[node] for node in downstream),
            "affected_people": len(downstream_owners),
        }
    return impacts


def _as_utc(value, default_timezone=timezone.utc):
    """Parse a deadline or reference time, interpreting naive values in the given zone."""
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if not isinstance(value, datetime):
        raise ValueError("Expected an ISO 8601 string or datetime")
    if value.tzinfo is None:
        value = value.replace(tzinfo=default_timezone)
    return value.astimezone(timezone.utc)


def calculate_urgency(deadline, now=None, deadline_timezone=timezone.utc):
    """Return urgency; date-only and naive deadlines use deadline_timezone."""
    if deadline is None or deadline == "":
        return 0.20

    try:
        due = _as_utc(deadline, deadline_timezone)
        current = _as_utc(now) if now is not None else datetime.now(timezone.utc)
    except (TypeError, ValueError, OverflowError):
        return 0.20

    remaining = due - current
    if remaining.total_seconds() < 0:
        return 1.00
    if remaining.total_seconds() <= 24 * 60 * 60:
        return 0.90
    if remaining.total_seconds() <= 3 * 24 * 60 * 60:
        return 0.70
    if remaining.total_seconds() <= 7 * 24 * 60 * 60:
        return 0.40
    return 0.20


def calculate_critical_path(graph):
    """Score tasks on longest or near-longest source-to-deadline-terminal paths."""
    order = list(nx.topological_sort(graph))
    endpoints = set()
    for node in graph:
        deadline = graph.nodes[node].get("deadline")
        if graph.out_degree(node) == 0 and deadline not in (None, ""):
            try:
                _as_utc(deadline)
            except (TypeError, ValueError, OverflowError):
                continue
            endpoints.add(node)
    if not endpoints:
        return {node: 0.0 for node in graph}

    prefix_lengths = {node: 0 for node in graph}
    for node in order:
        for predecessor in graph.predecessors(node):
            prefix_lengths[node] = max(prefix_lengths[node], prefix_lengths[predecessor] + 1)

    suffix_lengths = {node: None for node in graph}
    for node in reversed(order):
        if node in endpoints:
            suffix_lengths[node] = 0
        for dependent in graph.successors(node):
            if suffix_lengths[dependent] is not None:
                length = suffix_lengths[dependent] + 1
                suffix_lengths[node] = max(suffix_lengths[node] or 0, length)

    longest = max(prefix_lengths[endpoint] for endpoint in endpoints)
    scores = {}
    for node in graph:
        if suffix_lengths[node] is None:
            scores[node] = 0.0
            continue
        length = prefix_lengths[node] + suffix_lengths[node]
        if length == longest:
            scores[node] = 1.0
        elif length == longest - 1:
            scores[node] = 0.5
        else:
            scores[node] = 0.0
    return scores


def calculate_priority(graph, now=None, deadline_timezone=timezone.utc):
    """Combine normalized downstream, urgency, people, and critical-path scores."""
    now = now if now is not None else datetime.now(timezone.utc)
    downstream = calculate_downstream_impact(graph)
    critical_path = calculate_critical_path(graph)
    max_impact = max((item["weighted_downstream_impact"] for item in downstream.values()), default=0)
    max_people = max((item["affected_people"] for item in downstream.values()), default=0)

    priorities = {}
    for task_id, attributes in graph.nodes(data=True):
        downstream_component = (
            downstream[task_id]["weighted_downstream_impact"] / max_impact if max_impact else 0.0
        )
        people_component = (
            downstream[task_id]["affected_people"] / max_people if max_people else 0.0
        )
        urgency_component = calculate_urgency(attributes.get("deadline"), now, deadline_timezone)
        critical_component = critical_path[task_id]
        score = 100 * (
            0.40 * downstream_component
            + 0.25 * urgency_component
            + 0.20 * people_component
            + 0.15 * critical_component
        )
        priorities[task_id] = {
            "priority_score": round(score, 2),
            "downstream_component": downstream_component,
            "urgency_component": urgency_component,
            "people_component": people_component,
            "critical_path_component": critical_component,
        }
    return priorities


def detect_bottlenecks(graph, scores):
    """Return pending tasks meeting downstream or coworker impact thresholds."""
    impacts = calculate_downstream_impact(graph)
    hard_graph = nx.DiGraph(
        (source, target)
        for source, target, data in graph.edges(data=True)
        if data.get("type") == "hard"
    )
    hard_graph.add_nodes_from(graph)
    bottlenecks = []
    for task_id, attributes in graph.nodes(data=True):
        status = attributes.get("status")
        normalized = status.strip().lower() if isinstance(status, str) else "unknown"
        if normalized not in {"pending", "unknown", "", "open", "needsaction", "in_progress"}:
            continue

        downstream_count = impacts[task_id]["downstream_count"]
        blocked_count = len(nx.descendants(hard_graph, task_id))
        affected_people = impacts[task_id]["affected_people"]
        if blocked_count < 3 and affected_people < 2:
            continue

        task_scores = scores.get(task_id, {})
        priority_score = task_scores.get("priority_score", 0.0)
        critical_path_impact = task_scores.get("critical_path_component", 0.0)
        owner = attributes.get("owner")
        reason = f"Blocks {blocked_count} tasks and affects {affected_people} coworkers."
        if normalized in {"unknown", ""}:
            reason = "Potential bottleneck; completion status is unknown. " + reason
        bottlenecks.append(
            {
                "task_id": task_id,
                "title": attributes.get("title"),
                "owner": owner,
                "deadline": attributes.get("deadline"),
                "priority_score": priority_score,
                "downstream_count": downstream_count,
                "blocked_count": blocked_count,
                "affected_people": affected_people,
                "critical_path_impact": critical_path_impact,
                "ownership_gap": (
                    owner is None
                    or isinstance(owner, str)
                    and owner.strip().lower() in ("", "unknown")
                ),
                "reason": reason,
            }
        )
    return sorted(bottlenecks, key=lambda item: item["priority_score"], reverse=True)


def graph_to_ui_data(graph, now=None, deadline_timezone=timezone.utc):
    """Return a JSON-ready graph snapshot for a UI to render without NetworkX."""
    reference_time = _as_utc(now) if now is not None else datetime.now(timezone.utc)
    scores = calculate_priority(graph, reference_time, deadline_timezone)
    impacts = calculate_downstream_impact(graph)
    bottlenecks = detect_bottlenecks(graph, scores)
    bottleneck_by_id = {item["task_id"]: item for item in bottlenecks}
    order = list(nx.topological_sort(graph))
    layers = {}
    for task_id in order:
        layers[task_id] = max(
            (layers[prerequisite] + 1 for prerequisite in graph.predecessors(task_id)),
            default=0,
        )

    nodes = []
    for task_id in order:
        attributes = graph.nodes[task_id]
        owner = attributes.get("owner")
        owner_display = (
            owner if isinstance(owner, str) and owner.strip()
            and owner.strip().lower() != "unknown" else "Unknown"
        )
        deadline = attributes.get("deadline")
        if isinstance(deadline, (date, datetime)):
            deadline = deadline.isoformat()
        nodes.append({
            "id": task_id,
            "title": attributes.get("title") or task_id,
            "description": attributes.get("description"),
            "owner": owner,
            "owner_display": owner_display,
            "deadline": deadline,
            "status": attributes.get("status"),
            "layer": layers[task_id],
            "impact": impacts[task_id],
            "priority": scores[task_id],
            "is_bottleneck": task_id in bottleneck_by_id,
            "bottleneck_reason": bottleneck_by_id.get(task_id, {}).get("reason"),
        })

    edges = [
        {
            "source": source,
            "target": target,
            "type": attributes["type"],
            "weight": attributes["weight"],
            "evidence": attributes.get("evidence"),
            "confidence": attributes.get("confidence"),
        }
        for source, target, attributes in graph.edges(data=True)
    ]
    return {
        "as_of": reference_time.isoformat(),
        "nodes": nodes,
        "edges": edges,
        "bottleneck_ids": [item["task_id"] for item in bottlenecks],
    }
