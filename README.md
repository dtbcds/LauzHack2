# LauzHack2

## Fine-tune task dependency classification

`train_dependency_model.py` fine-tunes the Hugging Face `Qwen/Qwen3-8B`
checkpoint with 4-bit QLoRA. Training requires a CUDA GPU, its matching PyTorch
build, and the packages in `requirements-train.txt`. The packaged inference model
is `dist/release/dependency-qwen3-v2-Q4_K_M.gguf` (about 5 GB); its Ollama name is
`dependency-qwen3-v2:q4`.

Create separate UTF-8 JSONL files for training and validation. Each line is one
target task with its complete candidate list and gold dependencies:

```json
{"target_task":{"id":"T","title":"Launch","description":"Cannot launch until finance approves the budget."},"candidate_tasks":[{"id":"A","title":"Approve budget","description":"Finance approves the campaign budget."}],"dependencies":[{"prerequisite_task_id":"A","dependent_task_id":"T","type":"hard","weight":1.0,"evidence":"Cannot launch until finance approves the budget.","confidence":1.0}]}
```

Use `[]` for no dependencies. Include only `hard` (weight `1.0`) and `soft`
(weight `0.5`) labels. Evidence must be an exact substring of the target or
corresponding candidate description. Keep related tasks in the same split to
avoid leakage. Validation rejects unknown or duplicate candidate IDs, duplicate
dependency labels, mismatched weights, and unsupported evidence.

```powershell
python -m pip install -r requirements-train.txt
python train_dependency_model.py validate data/v2/train.jsonl data/v2/validation.jsonl data/v2/test.jsonl
python train_dependency_model.py train --train data/v2/train.jsonl --validation data/v2/validation.jsonl --output runs/dependency-qwen3-v2
ollama create dependency-qwen3-v2:q4 -f dist/release/Modelfile
python train_dependency_model.py evaluate --data data/v2/test.jsonl --model dependency-qwen3-v2:q4
```

The backend uses `dependency-qwen3-v2:q4` by default; set `DEPENDENCY_MODEL` to
override it. Keep `models/Qwen3-8B`, `runs/dependency-qwen3-v2/checkpoint-300`,
and `data/v2` to retrain or rebuild the packaged model. The evaluation command
reports per-class confusion and exact match.

## Desktop bottleneck notifications

Install `requirements.txt`, then pass the existing bottleneck results to the
notification check after scoring:

```python
from graph_construction import calculate_priority, detect_bottlenecks
from notifications import run_bottleneck_check

scores = calculate_priority(graph)
run_bottleneck_check(detect_bottlenecks(graph, scores))
```

Pending bottlenecks with priority at least 75 and at least three downstream tasks
or two affected coworkers generate a native Windows toast or macOS notification.
Successful sends are limited to one per task every four hours, including across
restarts. Windows uses `winotify`; macOS uses the built-in `osascript` command.

## UI graph data

Use `graph_to_ui_data(graph)` to give a Flet view plain dictionaries instead of
NetworkX objects:

```python
from graph_construction import graph_to_ui_data

view = graph_to_ui_data(graph)
for node in view["nodes"]:
    print(node["title"], node["priority"]["priority_score"])
for edge in view["edges"]:
    print(edge["source"], edge["target"], edge["type"])
```

The result contains `as_of`, topologically ordered `nodes`, directed `edges`,
and priority-sorted `bottleneck_ids`. Each node includes a `layer` for left-to-right
layout, display fields, downstream impact, priority breakdown, and bottleneck
reason. The payload can be serialized with `json.dumps`.
