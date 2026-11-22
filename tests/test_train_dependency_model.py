import json
from argparse import Namespace

import pytest

from train_dependency_model import evaluate, load_examples


def example():
    return {
        "target_task": {"id": "T", "description": "Launch after budget approval."},
        "candidate_tasks": [{"id": "A", "description": "Approve budget."}],
        "dependencies": [{
            "prerequisite_task_id": "A", "dependent_task_id": "T",
            "type": "hard", "weight": 1.0,
            "evidence": "budget approval", "confidence": 1.0,
        }],
    }


def test_load_examples_matches_inference_prompt(tmp_path):
    path = tmp_path / "train.jsonl"
    path.write_text(json.dumps(example()), encoding="utf-8")
    messages = load_examples(path)[0]["messages"]
    assert "Launch after budget approval." in messages[0]["content"]
    assert json.loads(messages[1]["content"])["dependencies"][0]["type"] == "hard"


@pytest.mark.parametrize("change", [
    lambda row: row["dependencies"][0].update(weight=0.5),
    lambda row: row["dependencies"][0].update(evidence="not in description"),
    lambda row: row["dependencies"][0].update(prerequisite_task_id="missing"),
])
def test_invalid_labels_fail_with_line_number(tmp_path, change):
    row = example()
    change(row)
    path = tmp_path / "train.jsonl"
    path.write_text(json.dumps(row), encoding="utf-8")
    with pytest.raises(ValueError, match="train.jsonl:1"):
        load_examples(path)


def test_evaluate_counts_missing_dependency_as_none(tmp_path, monkeypatch, capsys):
    import dependency_extraction

    path = tmp_path / "test.jsonl"
    path.write_text(json.dumps(example()), encoding="utf-8")
    monkeypatch.setattr(dependency_extraction, "extract_dependencies",
                        lambda target, candidates: {"dependencies": []})
    evaluate(Namespace(data=path, model="test-model"))
    metrics = json.loads(capsys.readouterr().out)
    assert metrics["exact_match"] == 0
    assert metrics["confusion"]["hard"]["none"] == 1
