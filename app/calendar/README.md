# Google Calendar setup

This folder fetches Calendar events and exports the fields Dany needs for task
extraction. Run commands from the repository root.

## Two different credential files

- `credentials.json` identifies the **OAuth desktop app**. It contains the app's
  client ID and client secret. Team members using the same Google Cloud project
  and OAuth client can use the same downloaded file; they do **not** each need
  to create a different client ID.
- `token.json` or a file under `tokens/` stores one person's authorization after
  they sign in. Each person needs their **own token**. Never copy another
  person's token to use their calendar.

The repository ignores `credentials.json`, `token.json`, and `tokens/`. Share
the app credentials file with teammates privately, outside Git. Keep token files
on the machine where authorization happened. On macOS and other Unix systems,
the script saves token files with owner-only permissions and restricts the
`tokens/` directory. This file-based storage is for the hackathon prototype;
a released app should use the operating system's secure credential store.

## Set up the app credentials

1. In [Google Cloud Console](https://console.cloud.google.com/), select the
   project for this app and enable the **Google Calendar API**.
2. Configure **Google Auth Platform → Audience**. If the app is External and in
   Testing, add every teammate who will sign in under **Test users**. Each must
   use that exact Google account when the consent page opens.
3. Under **Google Auth Platform → Clients**, create an OAuth client of type
   **Desktop app** (or use the one the team already created). This app calls the
   regular Calendar API; it does not use Google Calendar MCP tools.
4. Download the client's JSON file. Copy it into the repository root and name
   it exactly `credentials.json`. Do not paste its values into Python code or
   commit the file.
5. From the repository root, install dependencies if needed:

   ```sh
   python3 -m venv .venv
   source .venv/bin/activate
   python -m pip install -r requirements.txt
   ```

Google's [Python quickstart](https://developers.google.com/workspace/calendar/api/quickstart/python)
documents the Desktop app setup, and its [OAuth consent guide](https://developers.google.com/workspace/guides/configure-oauth-consent)
explains test users.

## Connect one group member

With the virtual environment active, run this from the repository root:

```sh
python -m app.calendar.google_calendar --member-id nils --output /tmp/nils_events.json
```

The first run opens a browser. Choose **Nils's Google account**, then approve
read-only Calendar access. The script creates a token file under `tokens/` for
the `nils` member ID. Repeating the command reuses that member's token. For
another member, change both the member ID and output filename, and have that
person choose their own Google account in the browser.

The script currently **does not verify** that the account chosen in the browser
belongs to the supplied `--member-id`. Use stable, distinct member IDs and
check the account carefully at sign-in. The original single-user command,
without `--member-id`, still uses `token.json`.

By default, a run fetches the next 14 days of that account's `primary`
calendar. Use `--calendar-id` for a different calendar or `--days-ahead` for a
different forward window. The JSON contains an `events` array; each item has
`id`, `member_id`, `calendar_id`, `summary`, `description`, `start`, `end`,
`organizer`, and `attendees`. It does not contain inferred task owners or
dependencies. Group-wide aggregation is a later step.

To check event count and description coverage without printing private content:

```sh
python -c "import json; e=json.load(open('/tmp/nils_events.json'))['events']; print('events:', len(e)); print('with descriptions:', sum(bool(x['description']) for x in e))"
```
