<img src="assets/relay.svg" alt="Relay logo" width="88" />

# Relay

**See what’s holding the team back. Keep work moving.**

Relay turns Google Calendar events into a shared map of work. Using AI to identify dependencies, it reveals how tasks connect, which ones need to happen first, and where delays could hold up the team.

An interactive graph makes those connections visible, while a list view separates blocking and non-blocking tasks. Search, owner filters, and sorting help teams focus. Each task includes its prerequisites, downstream impact, priority breakdown, and evidence supporting its dependencies.

Desktop notifications alert users to high-impact bottlenecks. Predefined queries help teams plan an owner’s work before a deadline, assess the impact of a delay, trace blockers, and find which task would unblock another teammate.

## From calendars to connections

Relay reads Calendar events and analyses their descriptions to identify relationships between tasks. It distinguishes between two types of dependency:

- **Hard dependencies:** a task cannot move forward until its prerequisite is complete.
- **Soft dependencies:** a task can proceed, but completing another task first would improve its outcome.

Each identified connection includes a supporting excerpt and a confidence score. Opening a task makes that reasoning available alongside its prerequisites and dependents.

Relay can work with one Calendar or combine multiple members’ Calendar snapshots through a shared coordinator. Calendar access is read-only, and Google authorization tokens remain on each member’s computer.

## Understand the impact of a task

Relay follows dependencies beyond the next task. It distinguishes direct dependents from work affected further down the chain and counts how many coworkers could be affected.

Priority scores combine four factors:

| Factor | Weight | What it captures |
| --- | --- | --- |
| Downstream impact | 40% | How much work depends on the task |
| Deadline urgency | 25% | How close the task’s deadline is |
| People affected | 20% | How many coworkers depend on downstream work |
| Critical path | 15% | The task’s position along long dependency chains leading to deadlines |

The breakdown is visible in the task details, so the score has an explanation. Desktop notification support targets high-impact bottlenecks, with a cooldown to avoid repeatedly alerting users about the same task.

## Explore the same work in two ways

**Graph view** presents the organisation’s dependencies as a connected picture. Tasks flow from prerequisites to dependents, with red hotspots at the connections affected by bottlenecks. Horizontal and vertical layouts make it possible to follow the graph in either direction across the screen.

See [group setup](app/calendar/GROUP.md) to upload each member’s Calendar and
show the combined group on every computer, with OpenAI dependency inference and
local graph construction on each.

Both views open the same task details: owner, deadline, prerequisites, downstream impact, priority breakdown, and dependency evidence.

## Ask questions that filters cannot answer

Relay includes four predefined queries for exploring connected work:

1. **Plan work:** find an owner’s task order before a deadline, accounting for dependencies and the teammates those tasks unblock.
2. **Check a delay:** see which tasks could be affected if a task slips.
3. **Trace blockers:** follow a task’s prerequisites to find what is holding it up.
4. **Unblock an owner:** find which task would free up the most work for another owner.

Items appear while analysis runs, and remain visible if the API request fails.
Configure OpenAI as described below. Personal data is stored under a separate collection
`personal:<member_id>/calendar`; no upload secret or HTTP server is required.
This mode displays only your Calendar. Keep the separate upload client running
if you also want to send snapshots to the group coordinator.

## Credits

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

Install `requirements.txt`, then pass the existing bottleneck results to the
notification check after scoring:

```python
from graph_construction import calculate_priority, detect_bottlenecks
from notifications import run_bottleneck_check

scores = calculate_priority(graph)
run_bottleneck_check(detect_bottlenecks(graph, scores))
```

Bottlenecks with priority at least 75 and at least three downstream tasks
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
