import json
import os
from types import SimpleNamespace

import pytest

import dependency_extraction as extraction


target = {
    "id": "task_003",
    "title": "Launch campaign",
    "description": "Launch cannot proceed until the budget is approved.",
    "owner": "Ari",
    "deadline": "2026-12-01",
}
candidates = [
    {
        "id": "task_001",
        "title": "Approve budget",
        "description": "The budget is approved by finance.",
        "owner": "Sam",
        "deadline": "2026-11-25",
    },
    {
        "id": "task_002",
        "title": "Prepare audience research",
        "description": "Audience research helps tailor the launch campaign.",
        "owner": "Lee",
        "deadline": "2026-11-27",
    },
]


def mock_response(monkeypatch, dependencies):
    payload = {"target_task_id": "task_003", "dependencies": dependencies}
    monkeypatch.setattr(
        extraction.ollama,
        "chat",
        lambda **kwargs: SimpleNamespace(
            message=SimpleNamespace(content=json.dumps(payload))
        ),
    )


def dependency(task_id, kind, weight, evidence):
    return {
        "prerequisite_task_id": task_id,
        "dependent_task_id": "task_003",
        "type": kind,
        "weight": weight,
        "evidence": evidence,
        "confidence": 0.95,
    }


def test_hard_dependency(monkeypatch):
    mock_response(
        monkeypatch,
        [dependency("task_001", "hard", 1.0, "cannot proceed until the budget is approved")],
    )
    result = extraction.extract_dependencies(target, candidates)
    assert result["dependencies"][0]["type"] == "hard"


def test_soft_dependency(monkeypatch):
    mock_response(
        monkeypatch,
        [dependency("task_002", "soft", 0.5, "helps tailor the launch campaign")],
    )
    result = extraction.extract_dependencies(target, candidates)
    assert result["dependencies"][0]["weight"] == 0.5


def test_no_dependency(monkeypatch):
    mock_response(monkeypatch, [])
    assert extraction.extract_dependencies(target, candidates)["dependencies"] == []


def test_multiple_dependencies(monkeypatch):
    mock_response(
        monkeypatch,
        [
            dependency("task_001", "hard", 1.0, "cannot proceed until the budget is approved"),
            dependency("task_002", "soft", 0.5, "helps tailor the launch campaign"),
        ],
    )
    assert len(extraction.extract_dependencies(target, candidates)["dependencies"]) == 2


def test_invalid_task_id_is_discarded(monkeypatch):
    mock_response(
        monkeypatch,
        [dependency("invented_task", "hard", 1.0, "cannot proceed until the budget is approved")],
    )
    assert extraction.extract_dependencies(target, candidates)["dependencies"] == []


def test_malformed_response_reports_failure(monkeypatch):
    monkeypatch.setattr(
        extraction.ollama,
        "chat",
        lambda **kwargs: SimpleNamespace(message=SimpleNamespace(content="not json")),
    )
    with pytest.raises(RuntimeError, match="Dependency extraction failed"):
        extraction.extract_dependencies(target, candidates)


def test_malformed_candidate_and_duplicate_ids_are_rejected():
    with pytest.raises(ValueError, match="Candidate tasks must be objects"):
        extraction.extract_dependencies(target, [None])
    with pytest.raises(ValueError, match="Duplicate candidate"):
        extraction.extract_dependencies(target, [candidates[0], candidates[0]])


def task(task_id, title, description, owner="Ari"):
    return {"id": task_id, "title": title, "description": description, "owner": owner}


# Expected mapping: prerequisite ID -> dependency type. Empty means no dependency.
LIVE_SCENARIOS = [
    ("explicit hard", task("T", "Launch campaign", "Cannot launch until finance approves the budget."),
     [task("A", "Approve budget", "Finance approves the campaign budget.", "Sam")], {"A": "hard"}),
    ("implicit hard", task("T", "Integrate checkout", "Connect checkout to the production payment API endpoint."),
     [task("A", "Build payment API", "Implement and publish the production payment API endpoint.", "Lee")], {"A": "hard"}),
    ("explicit soft", task("T", "Draft campaign", "Audience interviews would help tailor the campaign, but drafting can start now."),
     [task("A", "Interview audience", "Conduct audience interviews.", "Sam")], {"A": "soft"}),
    ("implicit soft", task("T", "Write onboarding copy", "Write the first version of onboarding copy using the current product brief."),
     [task("A", "Review tone", "Review product tone and suggest wording improvements for onboarding copy.", "Lee")], {"A": "soft"}),
    ("unrelated", task("T", "Submit tax forms", "File the quarterly tax forms."),
     [task("A", "Fix login", "Repair the mobile login screen.")], {}),
    ("multiple hard", task("T", "Ship mobile release", "Release requires completed security sign-off and app store approval."),
     [task("A", "Security sign-off", "Complete security sign-off.", "Sam"), task("B", "App store approval", "Obtain app store approval.", "Lee")], {"A": "hard", "B": "hard"}),
    ("mixed", task("T", "Publish report", "Cannot publish before legal approval; a design review would improve readability but is optional."),
     [task("A", "Legal approval", "Approve the report for publication.", "Sam"), task("B", "Design review", "Review report layout and suggest readability improvements.", "Lee")], {"A": "hard", "B": "soft"}),
    ("different employees", task("T", "Deploy service", "Deploy after Sam merges the database migration.", "Ari"),
     [task("A", "Merge migration", "Sam merges the database migration.", "Sam")], {"A": "hard"}),
    ("similar names", task("T", "Launch Project Atlas website", "Publish the Atlas marketing website."),
     [task("A", "Launch Project Atlas survey", "Send an independent customer survey for Atlas.")], {}),
    ("shared employee", task("T", "Write sales deck", "Create a deck for the sales team.", "Ari"),
     [task("A", "Update payroll", "Process monthly payroll.", "Ari")], {}),
    ("ambiguous", task("T", "Prepare launch materials", "Coordinate with the analytics team as needed."),
     [task("A", "Analytics dashboard", "Build a dashboard for launch metrics.", "Lee")], {}),
    ("missing reference", task("T", "Publish handbook", "Wait for legal approval before publishing the handbook."),
     [task("A", "Edit illustrations", "Polish handbook illustrations.", "Sam")], {}),
    ("implicit hard artifact", task("T", "Print event badges", "Print badges with each registered attendee's name."),
     [task("A", "Finalize attendee list", "Finalize the registered attendee list with names.", "Lee")], {"A": "hard"}),
    ("cross employee soft", task("T", "Draft demo script", "Ari can draft now; Sam's customer notes may make the examples more relevant.", "Ari"),
     [task("A", "Gather customer notes", "Sam collects customer notes for demo examples.", "Sam")], {"A": "soft"}),
    ("same project meeting", task("T", "Configure billing", "Set up recurring billing for Project Nova."),
     [task("A", "Nova kickoff meeting", "Hold the Project Nova kickoff meeting.", "Lee")], {}),
]


@pytest.mark.skipif(os.getenv("RUN_LIVE_OLLAMA") != "1", reason="set RUN_LIVE_OLLAMA=1")
def test_live_qwen_scenarios(monkeypatch):
    original_chat = extraction.ollama.chat
    rows = []
    for name, target_task, candidate_tasks, expected in LIVE_SCENARIOS:
        raw = {}

        def capture(**kwargs):
            response = original_chat(**kwargs)
            raw.update(json.loads(response.message.content))
            return response

        monkeypatch.setattr(extraction.ollama, "chat", capture)
        result = extraction.extract_dependencies(target_task, candidate_tasks)
        actual = {item["prerequisite_task_id"]: item["type"] for item in result["dependencies"]}
        valid = all(
            item["weight"] == {"hard": 1.0, "soft": 0.5}[item["type"]]
            and item["evidence"] in target_task["description"] + " "
            + next(t["description"] for t in candidate_tasks if t["id"] == item["prerequisite_task_id"])
            and 0 <= item["confidence"] <= 1
            for item in result["dependencies"]
        )
        rows.append({"scenario": name, "expected": expected, "actual": actual,
                     "correct": actual == expected and valid, "raw": raw, "result": result})
    for row in rows:
        print(json.dumps(row, ensure_ascii=False))
    totals = {kind: [0, 0] for kind in ("hard", "soft", "none")}
    for row in rows:
        if not row["expected"]:
            totals["none"][1] += 1
            totals["none"][0] += row["correct"]
        for task_id, kind in row["expected"].items():
            totals[kind][1] += 1
            totals[kind][0] += row["actual"].get(task_id) == kind
    print(json.dumps({"overall": [sum(row["correct"] for row in rows), len(rows)],
                      "by_class": totals}))
    assert all(row["correct"] for row in rows)
