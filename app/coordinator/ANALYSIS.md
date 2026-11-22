# Analysis after Calendar uploads

Each accepted `POST /submissions` saves the member's latest event snapshot and
queues a full analysis for that project and collection. The upload returns
immediately; one coordinator worker runs analysis in the background. A newer
upload supersedes an older result if the older run is still in progress.

The coordinator maps each event to a task: event summary becomes the title,
description stays intact, the submitting member becomes the owner, and the
event's scheduled end becomes a provisional deadline. Google Calendar does not
provide task completion status, so status remains unknown. Task IDs include
member and calendar IDs to keep events from different members distinct.

For each task, the worker calls Dany's `extract_dependencies` with the other
tasks as candidates, then passes the collected edges to `build_graph` and
`graph_to_ui_data`. With zero or one event, no Ollama call is needed. The result
and its `pending`, `processing`, `ready`, or `failed` status are saved in the
coordinator's SQLite database. An analysis failure does not discard the uploaded
events or the previous graph result. Failed runs are retried when the
coordinator restarts, so installing a missing dependency does not require
another employee upload.

On the coordinator computer, inspect the latest state without stopping the
server:

```sh
python -m app.coordinator.analysis demo round-1
```

Use `--database` if the server uses a different SQLite path. The server prints
when each analysis finishes or fails. For two or more tasks, Ollama must be
running on the coordinator with the model selected by `DEPENDENCY_MODEL`
(default `qwen3:8b`). Restart the coordinator server after updating this code.
Automatic Calendar polling and a live graph screen are separate future steps.

While the model is unavailable or training, start the coordinator with
`--no-analysis`. It still accepts and stores uploads; their analysis status
stays `pending`. Restart the coordinator without that flag when the model is
ready, and it will process the latest saved collection without asking members
to upload again.
