import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from unblock_notifications import newly_unblocked_top_task


def node(key, owner, score, status=None):
    return {"id": key, "title": key.title(), "owner": owner, "status": status,
            "priority": {"priority_score": score}}


def snapshot(nodes, edges=()):
    return {"nodes": list(nodes), "edges": list(edges)}


def test_removed_hard_blocker_changes_top_available_task():
    other = node("other", "nil", 45)
    blocked = node("important", "nil", 90)
    blocker = node("approval", "dany", 70)
    old = snapshot([other, blocked, blocker], [
        {"source": "approval", "target": "important", "type": "hard"},
    ])
    new = snapshot([other, blocked])
    assert newly_unblocked_top_task(old, new, "nil") == ("Important", "Approval")
    assert newly_unblocked_top_task(old, new, "dany") is None
    assert newly_unblocked_top_task(new, new, "nil") is None


def test_only_alerts_when_new_top_task_is_fully_unblocked():
    other = node("other", "nil", 45)
    blocked = node("important", "nil", 90)
    first = node("approval", "dany", 70)
    second = node("design", "dany", 65)
    old = snapshot([other, blocked, first, second], [
        {"source": "approval", "target": "important", "type": "hard"},
        {"source": "design", "target": "important", "type": "hard"},
    ])
    still_blocked = snapshot([other, blocked, second], [
        {"source": "design", "target": "important", "type": "hard"},
    ])
    assert newly_unblocked_top_task(old, still_blocked, "nil") is None
    assert newly_unblocked_top_task(old, snapshot([other, blocked, first], [
        {"source": "approval", "target": "important", "type": "hard"},
    ]), "nil") is None
    assert newly_unblocked_top_task(old, snapshot([other, blocked, node("new", "nil", 95)]), "nil") is None


def test_soft_dependency_does_not_count_as_blocker():
    blocked = node("important", "nil", 90)
    blocker = node("approval", "dany", 70)
    old = snapshot([blocked, blocker], [
        {"source": "approval", "target": "important", "type": "soft"},
    ])
    assert newly_unblocked_top_task(old, snapshot([blocked]), "nil") is None
