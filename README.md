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

## Shared group view

See [group setup](app/calendar/GROUP.md) to upload each member’s Calendar and
show the combined group on every computer, with OpenAI dependency inference and
local graph construction on each.

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

Items appear while analysis runs, and remain visible if the API request fails.
Configure OpenAI as described below. Personal data is stored under a separate collection
`personal:<member_id>/calendar`; no upload secret or HTTP server is required.
This mode displays only your Calendar. Keep the separate upload client running
if you also want to send snapshots to the group coordinator.

On macOS, set `RELAY_MODE=personal RELAY_MEMBER_ID=nil` before the launch command.
To return to coordinator mode in PowerShell, run
`$env:RELAY_MODE = "coordinator"` before launching again.

## OpenAI setup

Dependency inference now uses the OpenAI Responses API with Structured Outputs.
Ollama, GGUF files, local model imports, and `DEPENDENCY_MODEL` are not used.

1. Install dependencies: `python -m pip install -r requirements.txt`.
2. Copy `.env.example` to `.env` in the repository root (unless `.env` already exists).
3. Put your API key in `.env`:

```dotenv
OPENAI_API_KEY=your-api-key-here
OPENAI_MODEL=gpt-4.1
```

The app reads that file automatically, regardless of its launch directory.
Environment variables override `.env`. The real `.env` is ignored by Git; only
the empty `.env.example` is tracked. Keep your key in the local file rather than
source code, terminal commands, Calendar descriptions, or the group upload.
Each computer running analysis needs its own configured `.env`.

One request considers the whole group's titles, descriptions, and owners together.
Request-local short IDs are mapped back to Calendar IDs. Only relevant task data
is sent to OpenAI; Google tokens, secrets, and API keys are excluded from the input.
Responses are requested with `store=False`, strict JSON schema, a 4096 output-token
limit, a 60-second timeout, and at most one automatic retry for transient failures.
An empty or single-task group needs no model request. Unchanged dependency inputs
reuse an in-memory cache keyed by model, prompt, and schema. Deadline changes can
recompute graph scores without another request in the same process.

The app validates evidence and IDs, constructs the graph, and computes priorities
and bottlenecks deterministically. Unknown Calendar completion status stays unknown;
high-impact tasks can be marked as potential bottlenecks. Explicitly completed
tasks are excluded. A genuine cycle remains an error; it is never silently removed.
Each group UI makes its own requests, so running analysis on three computers uses
more API credits than on one. Check API usage on the OpenAI platform.

Restart the app after upgrading. Old Qwen group results are automatically scheduled
for recomputation once with the configured OpenAI engine. Keep using the existing
group launch commands; no Flutter rebuild or Google OAuth changes are required.

Offline tests do not call OpenAI. To run the small paid regression set:

```sh
RUN_LIVE_OPENAI=1 .venv/bin/python -m pytest tests/test_dependency_direction_live.py -q -s
```

On PowerShell, set `$env:RUN_LIVE_OPENAI = "1"` then run the Python pytest command.
These tests cover independent tasks, ordinary chains, an implicit grading step,
and a genuine circular dependency. Errors distinguish missing keys, authentication,
network, quota, incomplete output, and validation failures.

## Desktop bottleneck notifications

The desktop UI automatically checks each completed (`ready`) analysis snapshot.
It shows a persistent in-app alert and submits native Windows/macOS notifications
for bottlenecks with priority at least 75 and either three downstream tasks or two
affected coworkers. Partial or failed analyses do not notify. Unknown Calendar
completion status is labelled as a potential bottleneck; completed tasks never notify.

Native submissions have a four-hour cooldown per task, project/collection, and
viewer. The app persists cooldowns in ignored `data/notifications.json`, so refreshes
and restarts do not spam alerts. Failed submissions do not start the cooldown.
The in-app alert remains available while qualifying tasks exist, regardless of
native delivery or cooldown. It clears on a later analysis without qualifying tasks.

Windows uses `winotify` (included in requirements); macOS uses `osascript`. OS
notification settings and Focus/Do Not Disturb can suppress a submitted pop-up.
The app can confirm submission, but cannot confirm that the OS displayed it.
Test native delivery without Calendar, OpenAI charges, or cooldown changes:

```sh
python -m notifications --test
```

For the current Report → Presentation → Grade presentation chain with three
owners, Report can qualify as a potential bottleneck because it affects two
coworkers and has high priority. Restart the UI after pulling this change.

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
