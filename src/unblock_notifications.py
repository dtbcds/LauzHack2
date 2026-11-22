"""Detect when a removed hard prerequisite changes an owner's top task."""


DONE = {"done", "complete", "completed"}


def _open(node: dict) -> bool:
    return str(node.get("status") or "").casefold() not in DONE


def _blockers(snapshot: dict, nodes: dict[str, dict]) -> dict[str, set[str]]:
    blockers = {key: set() for key in nodes}
    for edge in snapshot["edges"]:
        source, target = edge["source"], edge["target"]
        if edge.get("type") != "soft" and source in nodes and target in nodes and _open(nodes[source]):
            blockers[target].add(source)
    return blockers


def newly_unblocked_top_task(previous: dict, current: dict, owner: str) -> tuple[str, str] | None:
    """Return (new task title, removed blocker title) when the owner's top task changes."""
    owner = owner.strip().casefold()
    if not owner:
        return None

    old_nodes = {node["id"]: node for node in previous["nodes"]}
    new_nodes = {node["id"]: node for node in current["nodes"]}
    old_blockers = _blockers(previous, old_nodes)
    new_blockers = _blockers(current, new_nodes)

    def top_ready(nodes: dict[str, dict], blockers: dict[str, set[str]]) -> str | None:
        ready = (
            node for node in nodes.values()
            if str(node.get("owner") or "").strip().casefold() == owner
            and _open(node) and not blockers[node["id"]]
        )
        top = max(ready, key=lambda node: (node["priority"]["priority_score"], node["id"]), default=None)
        return top["id"] if top else None

    old_top = top_ready(old_nodes, old_blockers)
    new_top = top_ready(new_nodes, new_blockers)
    if new_top is None or new_top == old_top or new_top not in old_nodes:
        return None
    if not old_blockers[new_top] or new_blockers[new_top]:
        return None

    removed = [key for key in old_blockers[new_top] if key not in new_nodes]
    if not removed:
        return None
    main_blocker = max(removed, key=lambda key: old_nodes[key]["priority"]["priority_score"])
    return new_nodes[new_top]["title"], old_nodes[main_blocker]["title"]
