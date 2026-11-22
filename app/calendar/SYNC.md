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
