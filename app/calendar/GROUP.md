# Shared group data with analysis on each computer

All group apps upload their own prepared Calendar snapshot, download the combined
collection, and compute their own graph using local Ollama. The coordinator
shares event JSON, not Google tokens, member secrets, or its SQLite file. A
registered member's existing secret authorizes reading their project's collection.

Stop the old UI and the separate `send_to_coordinator --on-demand` command on each
computer; the group UI now does both uploading and downloading. Pull the latest
code on each computer. No Flutter rebuild is required for these Python changes.
Keep everyone on the same `demo / round-1` collection for this demo.

## On Nil's Mac

Start the coordinator with analysis disabled, because the UIs now analyse locally:

```sh
.venv/bin/python -m app.coordinator.server --host YOUR_LAN_IP --certfile data/coordinator.crt --keyfile data/coordinator.key --no-analysis
```

In a second terminal start the host UI:

```sh
.venv/bin/python src/main.py --mode group-host --member-id nil
```

The host reads/writes `data/coordinator.sqlite3` directly and keeps its local graph
in a separate cache. It fetches Nil's Calendar on startup (Google may ask Nil to
authorize Calendar and Tasks). Nil does not need a member secret for local host
access and is not added to the remote refresh waiting list. The older registered
`nils` entry remains excluded; Nil's new submissions use `nil`.

## On Dany's Windows computer

```powershell
python src/main.py --mode group --member-id dany --coordinator-url https://YOUR_LAN_IP:8000 --ca-cert .\data\coordinator.crt
```

Hatem runs the same command with `--member-id hatem`. Each enters their own existing
member secret in the terminal. It stays in memory. Google authorization stays on
that member's computer. The certificate must match the coordinator's current IP.

## Updating and analysis

The apps check the combined snapshot every 3 seconds and check their own Google
Calendar every 30 seconds. Refresh on any group UI requests a new upload from
members; running group UIs respond on their next check. Nil's host UI fetches and
adds Nil's own events too. Changes, including edits and deletions, replace the
previous member snapshot. Offline members' last uploads remain visible until they
reconnect. A group snapshot can include older data from an offline member.

Only changed combined event data triggers automatic local analysis. Calendar
items appear before dependency inference finishes. On model failure, items still
appear and the error is shown; Refresh retries. Use the same `DEPENDENCY_MODEL`
on each machine for comparable graphs. Local model results can still differ.

The app caches group data and analysis in `data/group-<member hash>.sqlite3`,
separate from personal mode and the coordinator's database. Restarting loads the
cache and reconnects. Network failures retain the last downloaded view and retry;
look at the sync status for an incorrect secret, address, or certificate.

Scope remains the primary Calendar's next 14 days, including linked Google Tasks
notes. Standalone Tasks without fetched Calendar entries are not included.
