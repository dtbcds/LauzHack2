# Coordinator receiver

The coordinator accepts one employee's Calendar event JSON at `POST /submissions`
and saves the latest snapshot for each project, collection, and member in SQLite.
Google OAuth tokens stay on the employee's computer. The database defaults to
`data/coordinator.sqlite3`; `data/` is ignored by Git.

## Start on one computer

From the repository root, create an upload secret for each member in the project:

```sh
python -m app.coordinator.members demo nils
python -m app.coordinator.members demo dany
python -m app.coordinator.members demo hatem
```

Give each person only their own printed secret. It is shown once and stored as a
hash in the coordinator database. Running the command again for the same member
rotates their secret and invalidates the old one. Use `--database` with both
commands if the database is elsewhere.

For a same-computer test, start the receiver:

```sh
python -m app.coordinator.server
curl http://127.0.0.1:8000/health
```

To accept connections from other computers, use the coordinator's LAN IP and
HTTPS. Create a short-lived, self-signed certificate that names that IP:

```sh
COORDINATOR_IP=192.168.1.42  # replace with this computer's LAN IP
mkdir -p data
umask 077
openssl req -x509 -newkey rsa:2048 -noenc -sha256 -days 7 \
  -keyout data/coordinator.key -out data/coordinator.crt \
  -subj "/CN=$COORDINATOR_IP" -addext "subjectAltName=IP:$COORDINATOR_IP"
python -m app.coordinator.server --host "$COORDINATOR_IP" \
  --certfile data/coordinator.crt --keyfile data/coordinator.key
```

Share **only** `data/coordinator.crt` with employees, alongside the coordinator
IP, project ID, and each employee's own upload secret. Confirm the certificate
came from the coordinator before trusting it. Keep `coordinator.key`
on the coordinator. Every employee must be able to reach the IP on port 8000
through the local network and firewall. The receiver refuses non-local listening
without a certificate and private key.

## Send a sample from an employee computer

Create `data/` if needed and save the shared certificate as
`data/coordinator.crt` on that computer. Enter the
member's secret without recording it in shell history:

```sh
read -r -s MEMBER_SECRET
```

Paste the secret and press Enter, then send a test event (change the IP and
member ID to match the registered member):

```sh
printf 'header = "Authorization: Bearer %s"\n' "$MEMBER_SECRET" | \
  curl --config - --cacert data/coordinator.crt \
    -H 'Content-Type: application/json' \
    --data '{"project_id":"demo","collection_id":"round-1","member_id":"dany","events":[{"id":"test-event","member_id":"dany"}]}' \
    "https://192.168.1.42:8000/submissions"
unset MEMBER_SECRET
```

To fetch and upload **your own actual Calendar events**, put the shared
`credentials.json` OAuth client file on your computer and run:

```sh
python -m app.calendar.send_to_coordinator \
  --project-id demo --collection-id round-1 --member-id dany \
  --coordinator-url https://192.168.1.42:8000 \
  --ca-cert data/coordinator.crt
```

Use your own member ID and the coordinator's real IP. The command prompts for
your upload secret. Google may open a browser the first time to authorize your
Calendar; the resulting Google token stays on your computer under `tokens/`.
It fetches events from your primary calendar for the next 14 days by default.
Use `--days-ahead` or `--calendar-id` to change that window or calendar.

The response includes `"received": true` and `"event_count": 1` for the sample.
Repeating the same project, collection, and member replaces that member's saved
snapshot. Stop the receiver with Ctrl+C.

The contract is one JSON object with nonempty `project_id`, `collection_id`,
and `member_id` strings plus an `events` array. Each event must have an `id`;
an event's `member_id`, if present, must match the outer `member_id`. The
`Authorization: Bearer` secret must belong to that project and member. The
receiver does not accept Google OAuth tokens.
