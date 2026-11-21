import json
from datetime import datetime, timedelta, timezone

import pytest

from graph_construction import (
    build_graph,
    calculate_critical_path,
    calculate_downstream_impact,
    detect_bottlenecks,
    calculate_priority,
    calculate_urgency,
    graph_to_ui_data,
)


def task(task_id):
    return {
        "id": task_id,
        "title": f"Task {task_id}",
        "owner": "Ari",
        "deadline": "2026-12-01",
        "status": "open",
    }


def dependency(prerequisite, dependent, kind="hard"):
    return {
        "prerequisite_task_id": prerequisite,
        "dependent_task_id": dependent,
        "type": kind,
        "evidence": "supporting phrase",
        "confidence": 0.9,
    }


def test_simple_chain():
    graph = build_graph(
        [task("A"), task("B"), task("C")],
        [dependency("A", "B"), dependency("B", "C")],
    )
    assert list(graph.edges) == [("A", "B"), ("B", "C")]
    assert graph.nodes["A"]["title"] == "Task A"


def test_multiple_prerequisites_and_hard_soft_weights():
    graph = build_graph(
        [task("A"), task("B"), task("C")],
        [dependency("A", "C", "hard"), dependency("B", "C", "soft")],
    )
    assert graph.in_degree("C") == 2
    assert graph.edges["A", "C"]["weight"] == 1.0
    assert graph.edges["B", "C"]["weight"] == 0.5
    assert graph.edges["B", "C"]["type"] == "soft"


def test_no_dependencies_and_none_type_create_no_edges():
    graph = build_graph([task("A"), task("B")], [dependency("A", "B", "none")])
    assert graph.number_of_nodes() == 2
    assert graph.number_of_edges() == 0


def test_missing_task_ids_are_ignored():
    graph = build_graph([task("A"), task("B")], [dependency("missing", "B")])
    assert graph.number_of_edges() == 0


def test_duplicate_task_ids_are_rejected():
    with pytest.raises(ValueError, match="Duplicate task IDs"):
        build_graph([task("A"), task("A")], [])


def test_circular_dependencies_are_rejected_with_involved_tasks():
    with pytest.raises(ValueError, match="A.*B.*C"):
        build_graph(
            [task("A"), task("B"), task("C")],
            [dependency("A", "B"), dependency("B", "C"), dependency("C", "A")],
        )


def test_self_dependency_is_rejected():
    with pytest.raises(ValueError, match="Self-dependency.*A"):
        build_graph([task("A")], [dependency("A", "A")])


def test_hard_dependency_chain_impact():
    tasks = [task("A"), task("B"), task("C")]
    tasks[0]["owner"], tasks[1]["owner"], tasks[2]["owner"] = "Ari", "Bo", "Cy"
    graph = build_graph(tasks, [dependency("A", "B"), dependency("B", "C")])
    impact = calculate_downstream_impact(graph)
    assert impact["A"] == {
        "direct_dependents": 1,
        "downstream_count": 2,
        "weighted_downstream_impact": 2.0,
        "affected_people": 2,
    }


def test_soft_dependency_chain_impact():
    graph = build_graph(
        [task("A"), task("B"), task("C")],
        [dependency("A", "B", "soft"), dependency("B", "C", "soft")],
    )
    impact = calculate_downstream_impact(graph)
    assert impact["A"]["weighted_downstream_impact"] == 0.75
    assert impact["A"]["downstream_count"] == 2


def test_mixed_hard_and_soft_dependency_impact():
    graph = build_graph(
        [task("A"), task("B"), task("C")],
        [dependency("A", "B", "hard"), dependency("B", "C", "soft")],
    )
    assert calculate_downstream_impact(graph)["A"]["weighted_downstream_impact"] == 1.5


def test_multiple_paths_use_strongest_contribution_once():
    graph = build_graph(
        [task("A"), task("B"), task("C")],
        [
            dependency("A", "B", "hard"),
            dependency("B", "C", "soft"),
            dependency("A", "C", "soft"),
        ],
    )
    impact = calculate_downstream_impact(graph)
    assert impact["A"]["downstream_count"] == 2
    assert impact["A"]["weighted_downstream_impact"] == 1.5


def test_affected_people_are_unique_and_missing_owners_ignored():
    tasks = [task("A"), task("B"), task("C"), task("D")]
    tasks[0]["owner"] = "Ari"
    tasks[1]["owner"] = tasks[2]["owner"] = "Bo"
    tasks[3]["owner"] = None
    graph = build_graph(
        tasks,
        [dependency("A", "B"), dependency("A", "C"), dependency("A", "D")],
    )
    assert calculate_downstream_impact(graph)["A"]["affected_people"] == 1


def test_affected_people_counts_distinct_downstream_owners():
    tasks = [task("A"), task("B"), task("C")]
    tasks[0]["owner"], tasks[1]["owner"], tasks[2]["owner"] = "Ari", "Bo", "Cy"
    graph = build_graph(tasks, [dependency("A", "B"), dependency("A", "C")])
    assert calculate_downstream_impact(graph)["A"]["affected_people"] == 2


def test_affected_people_excludes_original_owner_when_reachable_downstream():
    tasks = [task("A"), task("B"), task("C")]
    tasks[0]["owner"], tasks[1]["owner"], tasks[2]["owner"] = "Ari", "Bo", "Ari"
    graph = build_graph(tasks, [dependency("A", "B"), dependency("B", "C")])
    assert calculate_downstream_impact(graph)["A"]["affected_people"] == 1


def test_affected_people_ignores_unknown_and_blank_owners():
    tasks = [task("A"), task("B"), task("C"), task("D")]
    tasks[1]["owner"], tasks[2]["owner"], tasks[3]["owner"] = "unknown", " ", None
    graph = build_graph(
        tasks,
        [dependency("A", "B"), dependency("A", "C"), dependency("A", "D")],
    )
    assert calculate_downstream_impact(graph)["A"]["affected_people"] == 0


def test_affected_people_counts_owner_once_across_multiple_paths():
    tasks = [task("A"), task("B"), task("C"), task("D")]
    tasks[0]["owner"], tasks[1]["owner"] = "Ari", "Bo"
    tasks[2]["owner"], tasks[3]["owner"] = "Cy", "Dee"
    graph = build_graph(
        tasks,
        [
            dependency("A", "B"),
            dependency("A", "C"),
            dependency("B", "D"),
            dependency("C", "D"),
        ],
    )
    assert calculate_downstream_impact(graph)["A"]["affected_people"] == 3


def test_task_without_dependents_has_zero_impact():
    graph = build_graph([task("A"), task("B")], [dependency("A", "B")])
    assert calculate_downstream_impact(graph)["B"] == {
        "direct_dependents": 0,
        "downstream_count": 0,
        "weighted_downstream_impact": 0,
        "affected_people": 0,
    }


def test_longer_chain_multiplies_weights_across_each_edge():
    graph = build_graph(
        [task("A"), task("B"), task("C"), task("D")],
        [
            dependency("A", "B", "hard"),
            dependency("B", "C", "soft"),
            dependency("C", "D", "soft"),
        ],
    )
    impact = calculate_downstream_impact(graph)
    assert impact["A"]["downstream_count"] == 3
    assert impact["A"]["weighted_downstream_impact"] == 1.75


def test_urgency_deadline_buckets():
    now = "2026-11-21T12:00:00+00:00"
    assert calculate_urgency("2026-11-21T11:00:00+00:00", now) == 1.00
    assert calculate_urgency("2026-11-22T00:00:00+00:00", now) == 0.90
    assert calculate_urgency("2026-11-23T12:00:00+00:00", now) == 0.70
    assert calculate_urgency("2026-11-26T12:00:00+00:00", now) == 0.40
    assert calculate_urgency("2026-12-01T12:00:00+00:00", now) == 0.20


def test_urgency_missing_deadline():
    assert calculate_urgency(None, "2026-11-21T12:00:00") == 0.20


def test_urgency_normalizes_timezone_aware_and_naive_values_to_utc():
    assert calculate_urgency(
        "2026-11-22T01:00:00+01:00", "2026-11-21T12:00:00"
    ) == 0.90


def test_urgency_exact_threshold_boundaries():
    now = "2026-11-21T12:00:00+00:00"
    assert calculate_urgency("2026-11-22T12:00:00+00:00", now) == 0.90
    assert calculate_urgency("2026-11-24T12:00:00+00:00", now) == 0.70
    assert calculate_urgency("2026-11-28T12:00:00+00:00", now) == 0.40
    assert calculate_urgency("2026-11-28T12:00:00.000001+00:00", now) == 0.20


def test_critical_path_scores_linear_chain():
    tasks = [task("A"), task("B"), task("C")]
    tasks[-1]["deadline"] = "2026-12-01"
    graph = build_graph(tasks, [dependency("A", "B"), dependency("B", "C")])
    assert calculate_critical_path(graph) == {"A": 1.0, "B": 1.0, "C": 1.0}


def test_critical_path_scores_longest_and_one_step_shorter_branches():
    tasks = [task(node) for node in "RABDZ X".replace(" ", "")]
    tasks[3]["deadline"] = "2026-12-01"  # D is a known-deadline terminal.
    tasks[5]["deadline"] = "2026-12-02"  # X is a separate, short terminal.
    graph = build_graph(
        tasks,
        [
            dependency("R", "A"),
            dependency("A", "B"),
            dependency("B", "D"),
            dependency("R", "Z"),
            dependency("Z", "D"),
        ],
    )
    scores = calculate_critical_path(graph)
    assert [scores[node] for node in "RABD"] == [1.0, 1.0, 1.0, 1.0]
    assert scores["Z"] == 0.5
    assert scores["X"] == 0.0


def test_critical_path_handles_equally_long_paths():
    tasks = [task(node) for node in "SABT"]
    tasks[-1]["deadline"] = "2026-12-01"
    graph = build_graph(
        tasks,
        [
            dependency("S", "A"),
            dependency("A", "T"),
            dependency("S", "B"),
            dependency("B", "T"),
        ],
    )
    assert set(calculate_critical_path(graph).values()) == {1.0}


def test_critical_path_scores_one_shorter_chain_and_excludes_outside_task():
    tasks = [task(node) for node in "RABCXYDZ"]
    tasks[6]["deadline"] = "2026-12-01"  # D is a known-deadline terminal.
    tasks[7]["deadline"] = "2026-12-02"  # Z is an isolated terminal.
    graph = build_graph(
        tasks,
        [
            dependency("R", "A"),
            dependency("A", "B"),
            dependency("B", "C"),
            dependency("C", "D"),
            dependency("R", "X"),
            dependency("X", "Y"),
            dependency("Y", "D"),
        ],
    )
    scores = calculate_critical_path(graph)
    assert [scores[node] for node in "RABCD"] == [1.0, 1.0, 1.0, 1.0, 1.0]
    assert scores["X"] == 0.5
    assert scores["Y"] == 0.5
    assert scores["Z"] == 0.0


def test_critical_path_uses_all_known_deadline_terminals():
    tasks = [task(node) for node in "RABXYZ"]
    tasks[4]["deadline"] = "2026-12-01"  # X ends a two-edge path.
    tasks[5]["deadline"] = "2026-12-02"  # Z ends a three-edge path.
    graph = build_graph(
        tasks,
        [
            dependency("R", "A"),
            dependency("A", "X"),
            dependency("R", "B"),
            dependency("B", "Y"),
            dependency("Y", "Z"),
        ],
    )
    scores = calculate_critical_path(graph)
    assert [scores[node] for node in "RBYZ"] == [1.0, 1.0, 1.0, 1.0]
    assert scores["A"] == 0.5
    assert scores["X"] == 0.5


def test_critical_path_without_known_deadline_terminal_returns_zeroes():
    tasks = [task("A"), task("B")]
    for item in tasks:
        item["deadline"] = None
    graph = build_graph(tasks, [dependency("A", "B")])
    assert calculate_critical_path(graph) == {"A": 0.0, "B": 0.0}


def test_critical_path_with_one_known_deadline_task():
    task_a = task("A")
    task_a["deadline"] = "2026-12-01"
    graph = build_graph([task_a], [])
    assert calculate_critical_path(graph) == {"A": 1.0}


def test_priority_maximum_components_score_100():
    tasks = [task("A"), task("B")]
    tasks[0]["deadline"] = "2026-11-20T12:00:00+00:00"
    tasks[1]["deadline"] = "2026-12-01T12:00:00+00:00"
    tasks[0]["owner"], tasks[1]["owner"] = "Ari", "Bo"
    graph = build_graph(tasks, [dependency("A", "B")])
    result = calculate_priority(graph, "2026-11-21T12:00:00+00:00")
    assert result["A"]["priority_score"] == 100.0
    assert result["A"]["downstream_component"] == 1.0
    assert result["A"]["urgency_component"] == 1.0
    assert result["A"]["people_component"] == 1.0
    assert result["A"]["critical_path_component"] == 1.0


def test_priority_zero_downstream_and_people_components():
    tasks = [task("A"), task("B")]
    graph = build_graph(tasks, [dependency("A", "B")])
    result = calculate_priority(graph, "2026-11-21T12:00:00+00:00")
    assert result["B"]["downstream_component"] == 0.0
    assert result["B"]["people_component"] == 0.0


def test_priority_unknown_deadline_uses_base_urgency():
    task_a = task("A")
    task_a["deadline"] = None
    graph = build_graph([task_a], [])
    result = calculate_priority(graph, "2026-11-21T12:00:00+00:00")
    assert result["A"]["urgency_component"] == 0.2
    assert result["A"]["priority_score"] == 5.0


def test_priority_graph_without_dependencies():
    graph = build_graph([task("A"), task("B")], [])
    result = calculate_priority(graph, "2026-11-21T12:00:00+00:00")
    assert all(item["downstream_component"] == 0.0 for item in result.values())
    assert all(item["people_component"] == 0.0 for item in result.values())


def test_priority_normalizes_downstream_and_people_across_tasks():
    tasks = [task("A"), task("B"), task("C")]
    tasks[0]["owner"], tasks[1]["owner"], tasks[2]["owner"] = "Ari", "Bo", "Cy"
    graph = build_graph(tasks, [dependency("A", "B"), dependency("B", "C")])
    result = calculate_priority(graph, "2026-11-21T12:00:00+00:00")
    assert result["A"]["downstream_component"] == 1.0
    assert result["B"]["downstream_component"] == 0.5
    assert result["A"]["people_component"] == 1.0
    assert result["B"]["people_component"] == 0.5


def test_priority_applies_all_four_formula_weights():
    tasks = [task("A"), task("B")]
    tasks[0]["deadline"] = "2026-11-22T00:00:00+00:00"
    tasks[1]["deadline"] = "2026-12-01T12:00:00+00:00"
    tasks[0]["owner"], tasks[1]["owner"] = "Ari", "Bo"
    graph = build_graph(tasks, [dependency("A", "B")])
    result = calculate_priority(graph, "2026-11-21T12:00:00+00:00")
    assert result["A"] == {
        "priority_score": 97.5,
        "downstream_component": 1.0,
        "urgency_component": 0.9,
        "people_component": 1.0,
        "critical_path_component": 1.0,
    }


def test_bottleneck_with_three_downstream_tasks_is_reported():
    tasks = [task("A"), task("B"), task("C"), task("D")]
    tasks[0]["status"] = "pending"
    graph = build_graph(
        tasks,
        [dependency("A", "B"), dependency("A", "C"), dependency("A", "D")],
    )
    scores = {"A": {"priority_score": 82.5, "critical_path_component": 1.0}}
    result = detect_bottlenecks(graph, scores)
    assert len(result) == 1
    assert result[0]["task_id"] == "A"
    assert result[0]["downstream_count"] == 3
    assert result[0]["priority_score"] == 82.5
    assert result[0]["critical_path_impact"] == 1.0


def test_bottleneck_with_two_affected_coworkers_is_reported():
    tasks = [task("A"), task("B"), task("C")]
    tasks[0]["status"] = "pending"
    tasks[0]["owner"], tasks[1]["owner"], tasks[2]["owner"] = "Ari", "Bo", "Cy"
    graph = build_graph(tasks, [dependency("A", "B"), dependency("A", "C")])
    result = detect_bottlenecks(graph, {"A": {"priority_score": 50}})
    assert result[0]["affected_people"] == 2


def test_bottlenecks_meeting_both_rules_are_sorted_by_priority():
    tasks = [task(node) for node in "ABCDEFG"]
    tasks[0]["status"] = tasks[1]["status"] = "pending"
    for item, owner in zip(tasks, ["Ari", "Bo", "Cy", "Dee", "Eve", "Fox", "Gia"]):
        item["owner"] = owner
    edges = [dependency("A", node) for node in "CDE"]
    edges += [dependency("B", node) for node in "EFG"]
    graph = build_graph(tasks, edges)
    scores = {
        "A": {"priority_score": 40, "critical_path_component": 0.5},
        "B": {"priority_score": 90, "critical_path_component": 1.0},
    }
    result = detect_bottlenecks(graph, scores)
    assert [item["task_id"] for item in result] == ["B", "A"]
    assert all(item["downstream_count"] >= 3 and item["affected_people"] >= 2 for item in result)


def test_high_priority_task_without_bottleneck_impact_is_omitted():
    tasks = [task("A"), task("B")]
    tasks[0]["status"] = "pending"
    graph = build_graph(tasks, [dependency("A", "B")])
    assert detect_bottlenecks(graph, {"A": {"priority_score": 100}}) == []


def test_completed_task_is_excluded():
    tasks = [task("A"), task("B"), task("C"), task("D")]
    tasks[0]["status"] = "completed"
    graph = build_graph(
        tasks,
        [dependency("A", "B"), dependency("A", "C"), dependency("A", "D")],
    )
    assert detect_bottlenecks(graph, {"A": {"priority_score": 100}}) == []


def test_missing_owner_is_reported_as_ownership_gap():
    tasks = [task("A"), task("B"), task("C")]
    tasks[0]["status"] = "pending"
    tasks[0]["owner"] = None
    tasks[1]["owner"], tasks[2]["owner"] = "Bo", "Cy"
    graph = build_graph(tasks, [dependency("A", "B"), dependency("A", "C")])
    result = detect_bottlenecks(graph, {"A": {"priority_score": 50}})
    assert result[0]["ownership_gap"] is True


def test_task_without_downstream_dependencies_is_not_a_bottleneck():
    tasks = [task("A")]
    tasks[0]["status"] = "pending"
    graph = build_graph(tasks, [])
    assert detect_bottlenecks(graph, {"A": {"priority_score": 100}}) == []


def test_conflicting_duplicate_edges_are_rejected():
    with pytest.raises(ValueError, match="Conflicting dependency"):
        build_graph([task("A"), task("B")], [dependency("A", "B"), dependency("A", "B", "soft")])


def test_malformed_records_are_rejected_and_metadata_is_preserved():
    with pytest.raises(ValueError, match="Tasks must be"):
        build_graph([None], [])
    with pytest.raises(ValueError, match="nonempty strings"):
        build_graph([{"id": []}], [])
    with pytest.raises(ValueError, match="Dependencies must be"):
        build_graph([task("A")], [None])
    item = {**task("A"), "description": "Original description", "source_event": "event-1"}
    graph = build_graph([item], [])
    assert graph.nodes["A"]["description"] == "Original description"
    assert graph.nodes["A"]["source_event"] == "event-1"


def test_invalid_deadline_is_not_a_critical_terminal():
    item = task("A")
    item["deadline"] = "not-a-date"
    assert calculate_critical_path(build_graph([item], [])) == {"A": 0.0}


def test_date_only_deadline_uses_configured_timezone():
    now = "2026-11-20T23:30:00+00:00"
    assert calculate_urgency("2026-11-22", now, timezone(timedelta(hours=1))) == 0.9
    assert calculate_urgency("2026-11-22", now) == 0.7


def test_priority_breakdown_reconstructs_displayed_score():
    tasks = [task(node) for node in "ABCD"]
    for item, owner in zip(tasks, ["Ari", "Bo", "Cy", "Dee"]):
        item["owner"] = owner
    graph = build_graph(tasks, [dependency("A", "B"), dependency("A", "C"),
                                dependency("A", "D"), dependency("B", "D")])
    result = calculate_priority(graph, "2026-11-21T12:00:00+00:00")
    for values in result.values():
        rebuilt = 100 * (0.4 * values["downstream_component"]
                         + 0.25 * values["urgency_component"]
                         + 0.2 * values["people_component"]
                         + 0.15 * values["critical_path_component"])
        assert round(rebuilt, 2) == values["priority_score"]


def test_soft_only_descendants_do_not_count_as_blocked():
    tasks = [task(node) for node in "ABCD"]
    tasks[0]["status"] = "pending"
    graph = build_graph(tasks, [dependency("A", node, "soft") for node in "BCD"])
    assert detect_bottlenecks(graph, {"A": {"priority_score": 90}}) == []
    for item, owner in zip(tasks, ["Ari", "Bo", "Cy", "Ari"]):
        item["owner"] = owner
    graph = build_graph(tasks, [dependency("A", node, "soft") for node in "BCD"])
    bottleneck = detect_bottlenecks(graph, {"A": {"priority_score": 90}})[0]
    assert bottleneck["blocked_count"] == 0
    assert bottleneck["downstream_count"] == 3
    assert bottleneck["affected_people"] == 2
    assert "Blocks 0 tasks" in bottleneck["reason"]


def test_ui_data_has_renderable_nodes_edges_and_scores():
    tasks = [task(node) for node in "ABC"]
    tasks[0].update(status="pending", owner=None, description="Budget approval",
                    deadline=datetime(2026, 11, 22, tzinfo=timezone.utc))
    tasks[1]["owner"], tasks[2]["owner"] = "Bo", "Cy"
    graph = build_graph(tasks, [dependency("A", "B"), dependency("A", "C", "soft")])
    view = graph_to_ui_data(graph, datetime(2026, 11, 21, tzinfo=timezone.utc))
    assert json.loads(json.dumps(view)) == view
    assert view["as_of"] == "2026-11-21T00:00:00+00:00"
    assert [node["id"] for node in view["nodes"]] == ["A", "B", "C"]
    assert [node["layer"] for node in view["nodes"]] == [0, 1, 1]
    assert view["nodes"][0]["owner_display"] == "Unknown"
    assert view["nodes"][0]["deadline"] == "2026-11-22T00:00:00+00:00"
    assert view["nodes"][0]["impact"]["affected_people"] == 2
    assert view["nodes"][0]["priority"]["priority_score"] > 0
    assert view["nodes"][0]["is_bottleneck"] is True
    assert "affects 2 coworkers" in view["nodes"][0]["bottleneck_reason"]
    assert view["bottleneck_ids"] == ["A"]
    assert [(edge["source"], edge["target"], edge["type"]) for edge in view["edges"]] == [
        ("A", "B", "hard"), ("A", "C", "soft")
    ]
    assert isinstance(graph.nodes["A"]["deadline"], datetime)


def test_ui_data_handles_empty_graph():
    view = graph_to_ui_data(build_graph([], []), "2026-11-21T00:00:00+00:00")
    assert view == {
        "as_of": "2026-11-21T00:00:00+00:00",
        "nodes": [],
        "edges": [],
        "bottleneck_ids": [],
    }
