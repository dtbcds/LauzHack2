from app.coordinator.analysis import analyze_submissions, event_to_task


def test_calendar_event_maps_to_task_without_inventing_status():
    task = event_to_task({
        "id": "event-1", "calendar_id": "primary", "summary": "Approve budget",
        "description": "Approve the budget.",
        "end": {"date": "2026-11-23"},
    }, "dany")
    assert task == {
        "id": "dany:primary:event-1", "title": "Approve budget",
        "description": "Approve the budget.", "owner": "dany",
        "deadline": "2026-11-22", "status": None,
    }


def test_full_analysis_connects_members_and_builds_graph():
    calls = []

    def extractor(target, candidates):
        calls.append((target["id"], [candidate["id"] for candidate in candidates]))
        if target["id"] == "hatem:primary:ship":
            return {"dependencies": [{
                "prerequisite_task_id": "dany:primary:budget",
                "dependent_task_id": "hatem:primary:ship", "type": "hard",
                "weight": 1.0, "evidence": "after budget approval", "confidence": 0.9,
            }]}
        return {"dependencies": []}

    graph = analyze_submissions([
        {"member_id": "dany", "events": [{
            "id": "budget", "summary": "Approve budget", "description": "Approve the budget.",
        }]},
        {"member_id": "hatem", "events": [{
            "id": "ship", "summary": "Ship product", "description": "Ship after budget approval.",
        }]},
    ], extractor=extractor)

    assert len(calls) == 2
    assert {node["owner"] for node in graph["nodes"]} == {"dany", "hatem"}
    assert graph["edges"][0]["source"] == "dany:primary:budget"
    assert graph["edges"][0]["target"] == "hatem:primary:ship"


def test_empty_snapshot_builds_empty_graph_without_model_call():
    graph = analyze_submissions(
        [{"member_id": "dany", "events": []}],
        extractor=lambda _target, _candidates: (_ for _ in ()).throw(AssertionError("unexpected model call")),
    )
    assert graph["nodes"] == []
    assert graph["edges"] == []


def test_single_event_builds_a_node_without_model_call():
    graph = analyze_submissions(
        [{"member_id": "dany", "events": [{"id": "budget", "summary": "Approve budget"}]}],
        extractor=lambda _target, _candidates: (_ for _ in ()).throw(AssertionError("unexpected model call")),
    )
    assert len(graph["nodes"]) == 1
    assert graph["nodes"][0]["id"] == "dany:primary:budget"
    assert graph["nodes"][0]["status"] is None
    assert graph["edges"] == []
