import json
import os
import stat
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from app.calendar.google_calendar import prepare_event
from app.coordinator.server import CoordinatorServer
from app.coordinator.storage import SubmissionStore


class CoordinatorServerTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.database_path = Path(self.directory.name) / "coordinator.sqlite3"
        self.server = CoordinatorServer(("127.0.0.1", 0), self.database_path)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base_url = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self):
        self.server.shutdown()
        self.thread.join(timeout=2)
        self.server.server_close()
        self.directory.cleanup()

    def post(self, payload):
        request = Request(
            self.base_url + "/submissions",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        return urlopen(request, timeout=2)

    def test_receives_and_replaces_member_snapshot(self):
        event = prepare_event(
            {"id": "event-1", "summary": "Approve budget", "description": "Approve the budget."},
            member_id="dany",
        )
        payload = {
            "project_id": "demo", "collection_id": "round-1", "member_id": "dany",
            "events": [event],
        }
        with self.post(payload) as response:
            receipt = json.load(response)
        self.assertTrue(receipt["received"])
        self.assertEqual(receipt["event_count"], 1)
        self.assertEqual(self.server.store.list_for_collection("demo", "round-1"), [payload])

        payload["events"] = [{"id": "event-2", "member_id": "dany"}]
        with self.post(payload):
            pass
        saved = SubmissionStore(self.database_path).list_for_collection("demo", "round-1")
        self.assertEqual(len(saved), 1)
        self.assertEqual(saved[0]["events"][0]["id"], "event-2")
        if os.name == "posix":
            self.assertEqual(stat.S_IMODE(self.database_path.stat().st_mode), 0o600)

    def test_rejects_a_mismatched_member(self):
        payload = {
            "project_id": "demo", "collection_id": "round-1", "member_id": "dany",
            "events": [{"id": "event-1", "member_id": "hatem"}],
        }
        with self.assertRaises(HTTPError) as raised:
            self.post(payload)
        self.assertEqual(raised.exception.code, 400)
        self.assertEqual(self.server.store.list_for_collection("demo", "round-1"), [])

    def test_rejects_unexpected_token_field(self):
        payload = {
            "project_id": "demo", "collection_id": "round-1", "member_id": "dany",
            "events": [], "token": "must-not-be-uploaded",
        }
        with self.assertRaises(HTTPError) as raised:
            self.post(payload)
        self.assertEqual(raised.exception.code, 400)
        self.assertEqual(self.server.store.list_for_collection("demo", "round-1"), [])

    def test_health_route(self):
        with urlopen(self.base_url + "/health", timeout=2) as response:
            self.assertEqual(json.load(response), {"status": "ok"})


if __name__ == "__main__":
    unittest.main()
