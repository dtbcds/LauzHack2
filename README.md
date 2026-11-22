# Relay

See what’s holding the team back. Keep work moving.

## Desktop UI

Graph gestures and side-panel resizing run in the custom Flutter client in
`flutter_client/`. Python receives the settled graph transform and panel width;
it handles data, filters, queries, and task selection.

The graph opens horizontally, with prerequisites on the left and dependents on
the right. Turn on **Vertical layout** to switch to vertical flow. Zoom stays bounded
by the complete graph and the full breadth of each layer; scrolling follows the
chosen axis.

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

The app mark in `assets/relay.svg` is adapted from Lucide's Workflow icon.
Its ISC license is included in `assets/LICENSE.lucide`. The matching PNG preview
and Windows ICO are included; the desktop build embeds the ICO automatically.

## Display coordinator analysis

The UI reads the coordinator's SQLite database and displays the saved
`graph_to_ui_data` result in the list, graph, details, and Queries panel. It checks
for changes every second; this only reads saved analysis and does not call Google
or the model. A previous graph stays visible while a newer analysis runs or fails.
An empty ready result clears removed tasks. Calendar completion status appears as
Unknown.

Defaults are project `demo`, collection `round-1`, and
`data/coordinator.sqlite3` under the repository root. These IDs refer to real
employee uploads. Set `RELAY_PROJECT_ID`, `RELAY_COLLECTION_ID`, and optionally
`RELAY_DATABASE` before launching to select another collection/database. The UI
and coordinator must read the same database on the coordinator computer.

Click **Refresh** to ask registered project members for fresh Calendar snapshots.
The screen shows how many members responded and who is still waiting. Each
member must keep the Calendar client running with `--on-demand`; offline members
remain waiting. Analysis continues in the coordinator after uploads, and the
screen displays its saved result automatically. The button can request another
refresh if a member needs to reconnect.

On macOS, install Flutter and Xcode, then build the same custom controls with:

```sh
bash tools/build-client-macos.sh
.venv/bin/python src/main.py
```

The build script finds Flutter on PATH or under `build/flutter-sdk/`. You can
also pass its executable path as the first argument. Install Python dependencies
with `.venv/bin/python -m pip install -r requirements.txt`. Rebuild after Dart
changes; Python changes only require restarting the app. The launcher selects
the Windows or macOS build automatically.

## Personal Calendar on each computer

To fetch and analyse your own Calendar locally without running a coordinator,
set personal mode before starting the UI. On Dany's Windows PowerShell:

```powershell
$env:RELAY_MODE = "personal"
$env:RELAY_MEMBER_ID = "dany"
.\.venv\Scripts\python.exe src/main.py
```

The UI fetches the next 14 days from the primary Calendar at startup. Refresh
fetches again and runs analysis on this computer. Calendar events and linked
Google Tasks notes use the member's existing local OAuth token. Keep
`credentials.json` in the repository root; Google may request authorization.
The Windows custom Flutter client must already be built as described above.

Items appear while analysis runs, and remain visible if the local model fails.
For dependencies, run Ollama locally with the configured `DEPENDENCY_MODEL`
(default `qwen3:8b`). Personal data is stored under a separate collection
`personal:<member_id>/calendar`; no upload secret or HTTP server is required.
This mode displays only your Calendar. Keep the separate upload client running
if you also want to send snapshots to the group coordinator.

On macOS, set `RELAY_MODE=personal RELAY_MEMBER_ID=nil` before the launch command.
To return to coordinator mode in PowerShell, run
`$env:RELAY_MODE = "coordinator"` before launching again.

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
