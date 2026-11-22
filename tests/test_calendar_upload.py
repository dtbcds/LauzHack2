import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError

from app.calendar.send_to_coordinator import (
    CalendarSnapshotSync,
    on_demand_calendar,
    send_calendar_snapshot,
    submission_endpoint,
    wait_for_refresh,
    watch_calendar,
)
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

    @patch("app.calendar.send_to_coordinator.fetch_events")
    def test_sync_detects_add_edit_and_delete_without_reuploading_unchanged_events(self, fetch_events):
        first = {"id": "event-1", "summary": "Draft plan", "description": "First draft"}
        second = {"id": "event-2", "summary": "Approve plan", "description": "Approve the draft"}
        edited = {**second, "description": "Approve the revised draft"}
        fetch_events.side_effect = [
            [first, second], [second, first], [first, edited], [], [],
        ]
        sync = CalendarSnapshotSync(
            project_id="demo", collection_id="round-1", member_id="dany",
            coordinator_url=self.url, secret=self.secret, service=object(),
        )

        self.assertEqual(sync.sync_once()["analysis_revision"], 1)
        self.assertIsNone(sync.sync_once())
        self.assertEqual(self.server.store.get_analysis("demo", "round-1")["revision"], 1)
        self.assertEqual(sync.sync_once()["analysis_revision"], 2)
        self.assertEqual(sync.sync_once()["analysis_revision"], 3)
        self.assertIsNone(sync.sync_once())
        self.assertEqual(self.server.store.list_for_collection("demo", "round-1")[0]["events"], [])

    @patch("app.calendar.send_to_coordinator.fetch_events")
    def test_failed_upload_is_retried_on_next_check(self, fetch_events):
        fetch_events.return_value = [{"id": "event-1", "summary": "Draft plan"}]
        sync = CalendarSnapshotSync(
            project_id="demo", collection_id="round-1", member_id="dany",
            coordinator_url=self.url, secret="wrong-secret", service=object(),
        )
        with self.assertRaises(HTTPError) as raised:
            sync.sync_once()
        self.assertEqual(raised.exception.code, 401)
        sync.secret = self.secret
        self.assertEqual(sync.sync_once()["event_count"], 1)

    @patch("app.calendar.send_to_coordinator.fetch_events")
    def test_watch_rechecks_and_uploads_a_deletion(self, fetch_events):
        fetch_events.side_effect = [
            [{"id": "event-1", "summary": "Draft plan"}],
            [{"id": "event-1", "summary": "Draft plan"}],
            [],
        ]
        sync = CalendarSnapshotSync(
            project_id="demo", collection_id="round-1", member_id="dany",
            coordinator_url=self.url, secret=self.secret, service=object(),
        )

        class ThreeChecks:
            checks = 0

            def is_set(self):
                return self.checks >= 3

            def wait(self, _seconds):
                self.checks += 1

        watch_calendar(sync, interval_seconds=30, stop_event=ThreeChecks())

        self.assertEqual(fetch_events.call_count, 3)
        self.assertEqual(self.server.store.get_analysis("demo", "round-1")["revision"], 2)
        self.assertEqual(self.server.store.list_for_collection("demo", "round-1")[0]["events"], [])

    @patch("app.calendar.send_to_coordinator.fetch_events", return_value=[])
    def test_on_demand_refresh_acknowledges_unchanged_calendar(self, fetch_events):
        sync = CalendarSnapshotSync(
            project_id="demo", collection_id="round-1", member_id="dany",
            coordinator_url=self.url, secret=self.secret, service=object(),
        )
        revision = self.server.store.request_refresh("demo", "round-1")

        class UntilReceived:
            def is_set(inner_self):
                return (self.server.store.get_refresh_status("demo", "round-1")
                        ["members"]["dany"] == "received")

            def wait(inner_self, _seconds):
                pass

        on_demand_calendar(sync, stop_event=UntilReceived())

        self.assertEqual(fetch_events.call_count, 2)
        self.assertEqual(self.server.store.get_refresh_revision("demo", "round-1"), revision)
        self.assertEqual(self.server.store.get_refresh_status("demo", "round-1")["members"],
                         {"dany": "received"})
        self.assertEqual(self.server.store.get_analysis("demo", "round-1")["revision"], 2)

    def test_refresh_poll_rejects_wrong_secret(self):
        sync = CalendarSnapshotSync(
            project_id="demo", collection_id="round-1", member_id="dany",
            coordinator_url=self.url, secret="wrong-secret", service=object(),
        )
        with self.assertRaises(HTTPError) as raised:
            wait_for_refresh(sync, after=0)
        self.assertEqual(raised.exception.code, 401)


if __name__ == "__main__":
    unittest.main()
