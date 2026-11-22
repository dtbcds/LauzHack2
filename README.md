# LauzHack2

## Desktop UI

Graph gestures and side-panel resizing run in the custom Flutter client in
`flutter_client/`. Python receives the settled graph transform and panel width;
it handles data, filters, queries, and task selection.

Build the client once with Flutter 3.47 or later and the Visual Studio C++ desktop
toolchain installed:

```powershell
.\tools\build-client.ps1
.\.venv\Scripts\python.exe src/main.py
```

If Flutter is not on PATH, pass `-Flutter 'C:\path\to\flutter\bin\flutter.bat'`.
The script also recognizes a project-local SDK in `build/flutter-sdk/`.
Rebuild after editing Dart files. Python changes and the existing VS Code launch
configuration use the built client automatically. Generated client files and
binaries stay in the ignored `build/` directory. The Python and Flutter Flet
versions are pinned together at 1.1.2.

## Fine-tune task dependency classification

`train_dependency_model.py` fine-tunes the Hugging Face `Qwen/Qwen3-8B`
checkpoint with 4-bit QLoRA. Training requires a CUDA GPU, its matching PyTorch
build, and the packages in `requirements-train.txt`. Ollama's `qwen3:8b` is used
for inference only; it is not a trainable checkpoint.

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
python train_dependency_model.py validate data/train.jsonl data/validation.jsonl
python train_dependency_model.py train --train data/train.jsonl --validation data/validation.jsonl --output runs/dependency-qwen3
python train_dependency_model.py export --adapter runs/dependency-qwen3/adapter --output runs/dependency-qwen3/merged
cd runs/dependency-qwen3/merged
ollama create dependency-qwen3
cd ../../..
python train_dependency_model.py evaluate --data data/test.jsonl --model dependency-qwen3
```

Set `DEPENDENCY_MODEL=dependency-qwen3` before running the application or live
extraction tests to use the imported model. Reserve a separate test file for
the evaluation command; it reports per-class confusion and exact match. The
export step merges in CPU memory and
requires room for the full 8B model; Ollama imports the merged Safetensors
directory through its generated `Modelfile`.

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
