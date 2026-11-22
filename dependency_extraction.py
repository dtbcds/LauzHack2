"""Extract task dependencies with the local Ollama model."""

import json
from copy import deepcopy
import os

import ollama


MODEL = os.getenv("DEPENDENCY_MODEL", "dependency-qwen3-v2:q4")

RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "target_task_id": {"type": "string"},
        "dependencies": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "prerequisite_task_id": {"type": "string"},
                    "dependent_task_id": {"type": "string"},
                    "type": {"type": "string", "enum": ["hard", "soft", "none"]},
                    "weight": {"type": "number", "enum": [1.0, 0.5, 0.0]},
                    "evidence": {"type": "string"},
                    "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                },
                "required": [
                    "prerequisite_task_id",
                    "dependent_task_id",
                    "type",
                    "weight",
                    "evidence",
                    "confidence",
                ],
                "additionalProperties": False,
            },
        },
    },
    "required": ["target_task_id", "dependencies"],
    "additionalProperties": False,
}


PROMPT = """Identify which candidate tasks the target task depends on.
Use task descriptions as the primary context. Do not infer dependencies only
from shared employees, projects, or meetings. A hard dependency means the
target cannot proceed until the prerequisite is complete (weight 1.0). A soft
dependency means the target can proceed, but completing the prerequisite first
is beneficial (weight 0.5). An optional candidate task can be soft when its
specific output would directly improve the target, even if the target does not
mention it. Vague coordination, possible contact, or work in the same area is
not enough; require a concrete output and a clear benefit to the target.
For each candidate, ask whether completing its specific deliverable would
enable or improve the target. Determine the direction from the supporting
statement: "A waits for B" supports B as the prerequisite and A as the dependent.
That statement alone does not support A as a prerequisite of B. If a candidate
needs the target's output, the candidate is downstream; this alone is not evidence
that the target needs the candidate. Return a candidate-to-target dependency only
when evidence supports that direction. Separate evidence may support the opposite
direction too: if A waits for B and B waits for A, preserve both supported
dependencies across their respective target checks, even though they form a cycle.
Do not invent a reverse dependency or suppress a supported one to make a graph
acyclic. A general request to coordinate with a team
does not establish a dependency on one of that team's tasks. A review that
suggests improvements to the target's draft is a soft dependency.
For example, a dashboard for launch metrics is not a prerequisite for launch
materials merely because the materials owner may coordinate with analytics;
the materials must actually use the dashboard or its output.
Use type none and weight 0 for no meaningful
dependency; normally omit such candidates from dependencies. Return multiple
dependencies when appropriate. Only use candidate IDs exactly as supplied;
never invent IDs, and omit any dependency that cannot be matched to a candidate.
Evidence must be an exact supporting phrase copied from a task description.
For each candidate separately, copy one contiguous substring verbatim. Prefer
the candidate's full description if a target sentence names several inputs.
Never paraphrase, omit words with ellipses, or combine fragments.
Set confidence from 0 to 1. Return only JSON matching the supplied schema.
/no_think

Tasks:
"""


def build_user_message(target_task: dict, candidate_tasks: list[dict]) -> str:
    """Keep training and Ollama inference inputs identical."""
    return PROMPT + json.dumps(
        {"target_task": target_task, "candidate_tasks": candidate_tasks},
        ensure_ascii=False,
    )


def extract_dependencies(target_task: dict, candidate_tasks: list[dict]) -> dict:
    """Return validated dependencies for target_task using Ollama."""
    if not isinstance(target_task, dict) or not isinstance(candidate_tasks, list):
        raise ValueError("Expected a target task and a list of candidate tasks")
    if any(not isinstance(task, dict) for task in candidate_tasks):
        raise ValueError("Candidate tasks must be objects")
    target_id = target_task.get("id", "")
    if not isinstance(target_id, str) or not target_id:
        raise ValueError("Target task ID must be a nonempty string")
    candidate_id_list = [task.get("id") for task in candidate_tasks]
    if any(not isinstance(task_id, str) or not task_id for task_id in candidate_id_list):
        raise ValueError("Candidate task IDs must be nonempty strings")
    if len(candidate_id_list) != len(set(candidate_id_list)):
        raise ValueError("Duplicate candidate task IDs")
    candidate_ids = {
        task["id"]
        for task in candidate_tasks
        if isinstance(task.get("id"), str) and task["id"] and task["id"] != target_id
    }
    if not candidate_ids:
        return {"target_task_id": target_id, "dependencies": []}
    # Constrain copied identifiers at generation time; Calendar IDs are long and
    # the model can otherwise shorten them or return a candidate as the target.
    schema = deepcopy(RESPONSE_SCHEMA)
    schema["properties"]["target_task_id"]["enum"] = [target_id]
    fields = schema["properties"]["dependencies"]["items"]["properties"]
    fields["dependent_task_id"]["enum"] = [target_id]
    fields["prerequisite_task_id"]["enum"] = sorted(candidate_ids)
    try:
        response = ollama.chat(
            model=MODEL,
            messages=[
                {
                    "role": "user",
                    "content": build_user_message(target_task, candidate_tasks),
                }
            ],
            format=schema,
            options={"temperature": 0, "seed": 0},
        )
        content = response.message.content
        result = json.loads(content) if isinstance(content, str) else content
    except Exception as exc:
        raise RuntimeError("Dependency extraction failed") from exc

    if not isinstance(result, dict) or result.get("target_task_id") != target_id:
        raise ValueError("Ollama returned an invalid target task ID")
    if not isinstance(result.get("dependencies"), list):
        raise ValueError("Ollama returned an invalid dependencies list")

    dependencies = []
    for item in result.get("dependencies", []):
        if not isinstance(item, dict):
            continue
        prerequisite_id = item.get("prerequisite_task_id")
        kind = item.get("type")
        weight = item.get("weight")
        evidence = item.get("evidence")
        confidence = item.get("confidence")
        expected_weight = {"hard": 1.0, "soft": 0.5, "none": 0.0}.get(kind)
        candidate = next(
            (task for task in candidate_tasks if task.get("id") == prerequisite_id), {}
        )
        target_description = target_task.get("description", "")
        candidate_description = candidate.get("description", "")
        if (
            prerequisite_id not in candidate_ids
            or item.get("dependent_task_id") != target_id
            or expected_weight is None
            or isinstance(weight, bool)
            or weight != expected_weight
            or not isinstance(evidence, str)
            or not evidence
            or not isinstance(target_description, str)
            or not isinstance(candidate_description, str)
            or not (evidence in target_description or evidence in candidate_description)
            or isinstance(confidence, bool)
            or not isinstance(confidence, (int, float))
            or not 0 <= confidence <= 1
        ):
            continue
        if kind == "none":
            continue
        dependencies.append(
            {
                "prerequisite_task_id": prerequisite_id,
                "dependent_task_id": target_id,
                "type": kind,
                "weight": expected_weight,
                "evidence": evidence,
                "confidence": confidence,
            }
        )

    return {"target_task_id": target_id, "dependencies": dependencies}
