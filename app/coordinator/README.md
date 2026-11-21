# Coordinator receiver: first local step

This is a small HTTP receiver for one employee's Calendar event JSON. It is
bound to `127.0.0.1`, so only programs on the same computer can reach it. It
does not use SQLite yet, accept remote employees, or run analysis. Submissions
are held in memory and disappear when the process stops.

From the repository root, start it in one terminal:

```sh
python -m app.coordinator.server
```

In a second terminal, check that it is running:

```sh
curl http://127.0.0.1:8000/health
```

Then send one sample submission:

```sh
curl -X POST http://127.0.0.1:8000/submissions \
  -H 'Content-Type: application/json' \
  --data '{"project_id":"demo","collection_id":"round-1","member_id":"nils","events":[{"id":"test-event","member_id":"nils"}]}'
```

The response includes `"received": true` and `"event_count": 1`. The actual
Calendar event JSON from the employee client can replace the sample `events`
array. Stop the receiver with Ctrl+C.

The contract is one JSON object with nonempty `project_id`, `collection_id`,
and `member_id` strings plus an `events` array. Each event must have an `id`;
an event's `member_id`, if present, must match the outer `member_id`. The
receiver does not accept Google OAuth tokens.
