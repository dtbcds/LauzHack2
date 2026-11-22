import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from component import format_deadline
from demo_data import FINANCE_TASKS as TASKS
from filters import visible_tasks


def test_filters_by_owner_and_query():
    results = visible_tasks(TASKS, query="presentation", owner="Alex")
    assert [task.title for task in results] == ["Review presentation"]


def test_sorts_by_dependency_impact():
    results = visible_tasks(TASKS, sort_by="Dependency impact")
    assert results[0].title == "Collect sales figures"
    assert results[-1].downstream_count == 0


def test_bottleneck_filter_and_unknown_deadline():
    assert all(task.bottleneck for task in visible_tasks(TASKS, bottlenecks_only=True))
    assert format_deadline(None) == "Unknown deadline"
