import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError

from app.calendar.send_to_coordinator import send_calendar_snapshot, submission_endpoint
from app.coordinator.server import CoordinatorServer


class CalendarUploadTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.server = CoordinatorServer(
            ("127.0.0.1", 0), Path(self.directory.name) / "coordinator.sqlite3",
            analyzer=lambda submissions: {"event_count": sum(len(item["events"]) for item in submissions)},
        )
        self.secret = self.server.store.register_member("demo", "dany")
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self):
        self.server.shutdown()
        self.thread.join(timeout=2)
        self.server.server_close()
        self.directory.cleanup()

    @patch("app.calendar.send_to_coordinator.fetch_events")
    @patch("app.calendar.send_to_coordinator.connect_calendar")
    def test_uploads_prepared_calendar_snapshot(self, connect_calendar, fetch_events):
        service = object()
        connect_calendar.return_value = service
        fetch_events.return_value = [{
            "id": "event-1", "summary": "Approve budget",
            "description": "Review the quote before approval.",
            "extra_google_field": "discard",
        }]

        receipt = send_calendar_snapshot(
            project_id="demo", collection_id="round-1", member_id="dany",
            coordinator_url=self.url, secret=self.secret,
        )

        self.assertEqual(receipt["event_count"], 1)
        connect_calendar.assert_called_once()
        self.assertEqual(connect_calendar.call_args.args[1].parent.name, "tokens")
        self.assertIs(fetch_events.call_args.args[0], service)
        saved = self.server.store.list_for_collection("demo", "round-1")[0]
        self.assertEqual(saved["events"][0]["description"], "Review the quote before approval.")
        self.assertEqual(saved["events"][0]["member_id"], "dany")
        self.assertNotIn("extra_google_field", saved["events"][0])
        self.assertNotIn(self.secret, json.dumps(saved))

    @patch("app.calendar.send_to_coordinator.fetch_events", return_value=[])
    @patch("app.calendar.send_to_coordinator.connect_calendar", return_value=object())
    def test_wrong_secret_cannot_upload(self, _connect_calendar, _fetch_events):
        with self.assertRaises(HTTPError) as raised:
            send_calendar_snapshot(
                project_id="demo", collection_id="round-1", member_id="dany",
                coordinator_url=self.url, secret="wrong-secret",
            )
        self.assertEqual(raised.exception.code, 401)
        self.assertEqual(self.server.store.list_for_collection("demo", "round-1"), [])

    def test_rejects_remote_plain_http(self):
        with self.assertRaises(ValueError):
            submission_endpoint("http://192.168.1.42:8000")


if __name__ == "__main__":
    unittest.main()
