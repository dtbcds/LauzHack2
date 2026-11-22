# Keep an employee Calendar in sync

The employee client can keep checking Google Calendar while it runs. It uploads
an initial snapshot, then uploads again only when an event is added, edited, or
removed. Reordered but otherwise identical events do not trigger another upload.
The same `project_id`, `collection_id`, and `member_id` are used each time, so
the coordinator replaces that member's previous snapshot. The upload secret is
entered once when the command starts and remains in memory; it is not written
to a file. Google OAuth remains on the employee's own computer.

From Dany's Windows PowerShell, with the coordinator running and his existing
`credentials.json` and `data\coordinator.crt` in place:

```powershell
py -m app.calendar.send_to_coordinator --project-id demo --collection-id round-1 --member-id dany --coordinator-url https://COORDINATOR_IP:8000 --ca-cert .\data\coordinator.crt --watch
```

Replace `COORDINATOR_IP` with the coordinator's current IP. The default check
interval is 60 seconds (varied slightly to spread requests across clients).
Use `--interval-seconds 30` for faster demo updates; 30 seconds is the minimum.
The command reports uploads and errors, retries temporary failures, and stops
with Ctrl+C. A wrong member secret stops the watch so it can be corrected.
The one-shot command still works without `--watch`.

The watch needs to remain running to notice Calendar changes. After a restart,
it sends an initial snapshot again. If an event leaves the next-14-days window,
it also disappears from the next snapshot. The coordinator acknowledges the
upload immediately; dependency analysis continues there in the background.
The desktop UI can later call `CalendarSnapshotSync.sync_once()` on its own
schedule instead of showing a terminal command.

This full-snapshot polling is intended for the small demo. Google's
[incremental sync guidance](https://developers.google.com/workspace/calendar/api/guides/sync)
is the next step if the project grows beyond a few calendars.

## Refresh when the coordinator asks

For a Refresh button, each employee runs the on-demand mode instead of
`--watch`. It uploads once at startup, then waits for a request over the same
authenticated HTTPS connection. On request, it reads Google Calendar again and
uploads a fresh snapshot even if nothing changed. The coordinator can then show
which members responded. Keep the client running; an offline member stays
`waiting` until they reconnect.

```powershell
py -m app.calendar.send_to_coordinator --project-id demo --collection-id round-1 --member-id dany --coordinator-url https://COORDINATOR_IP:8000 --ca-cert .\data\coordinator.crt --on-demand
```

On the coordinator, trigger a refresh now with:

```sh
python -m app.coordinator.refresh demo round-1
```

Check its progress without starting another refresh:

```sh
python -m app.coordinator.refresh demo round-1 --status
```

The UI can later call
`app.coordinator.refresh.request_collection_refresh(project_id, collection_id)`
and read `SubmissionStore.get_refresh_status(project_id, collection_id)` from
the same coordinator SQLite database. The client uses its existing member
secret and certificate; no new credential is needed. Each acknowledged upload
also queues the usual dependency analysis. With `--no-analysis`, snapshots are
saved and analysis stays pending until a model-enabled coordinator starts.

## Google Tasks linked from Calendar

Enable Google Tasks API in the same Cloud project and add
`https://www.googleapis.com/auth/tasks.readonly` to the OAuth consent configuration.
The client requests Calendar and Tasks read-only access together. Existing
Calendar-only tokens cause a new consent window automatically; approve both
permissions. The credentials file stays the same.

Calendar entries with `https://tasks.google.com/task/...` links are matched to
Tasks by their web link or task ID. Their actual `notes` replace Calendar's
placeholder description before upload. Empty task notes become an empty
description. Ordinary event descriptions are preserved. Tasks without Calendar
entries are not added. An unmatched task link or Tasks API error stops that
snapshot upload and prints an error, so placeholder text is not silently sent
for dependency extraction. Titles are never used to guess a match.

After pulling the update, stop and restart the client. To inspect the resolved
descriptions on Windows before uploading:

```powershell
.\.venv\Scripts\python.exe -m app.calendar.google_calendar --member-id dany
```

Then restart the usual `--on-demand` command and click Refresh on the coordinator.
