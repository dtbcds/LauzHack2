import errno
import json
import os
import sqlite3
import stat
import tempfile
import threading
import time
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
        self.analysis_inputs = []

        def analyze(submissions):
            self.analysis_inputs.append(submissions)
            return {"event_count": sum(len(item["events"]) for item in submissions)}

        self.server = CoordinatorServer(("127.0.0.1", 0), self.database_path, analyzer=analyze)
        self.secret = self.server.store.register_member("demo", "dany")
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base_url = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self):
        self.server.shutdown()
        self.thread.join(timeout=2)
        self.server.server_close()
        self.directory.cleanup()

    def post(self, payload, secret=None):
        headers = {"Content-Type": "application/json"}
        if secret is not False:
            headers["Authorization"] = f"Bearer {self.secret if secret is None else secret}"
        request = Request(
            self.base_url + "/submissions",
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        return urlopen(request, timeout=2)

    def wait_for_analysis(self, revision):
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            state = self.server.store.get_analysis("demo", "round-1")
            if state and state["revision"] == revision and state["status"] in ("ready", "failed"):
                return state
            time.sleep(0.01)
        self.fail(f"analysis revision {revision} did not finish")

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

    def test_requires_correct_member_secret(self):
        payload = {
            "project_id": "demo", "collection_id": "round-1", "member_id": "dany",
            "events": [{"id": "event-1", "member_id": "dany"}],
        }
        for secret in (False, "wrong-secret"):
            with self.subTest(secret=secret), self.assertRaises(HTTPError) as raised:
                self.post(payload, secret=secret)
            self.assertEqual(raised.exception.code, 401)
        payload["member_id"] = "hatem"
        payload["events"][0]["member_id"] = "hatem"
        with self.assertRaises(HTTPError) as raised:
            self.post(payload)
        self.assertEqual(raised.exception.code, 401)
        self.assertEqual(self.server.store.list_for_collection("demo", "round-1"), [])

    def test_secret_is_scoped_to_project_and_member_and_can_rotate(self):
        store = self.server.store
        self.assertFalse(store.is_authorized("other", "dany", self.secret))
        self.assertFalse(store.is_authorized("demo", "hatem", self.secret))
        rotated = store.register_member("demo", "dany")
        self.assertNotEqual(rotated, self.secret)
        self.assertFalse(store.is_authorized("demo", "dany", self.secret))
        self.assertTrue(store.is_authorized("demo", "dany", rotated))
        self.assertNotIn(rotated, self.database_path.read_bytes().decode("utf-8", errors="ignore"))

    def test_health_route(self):
        with urlopen(self.base_url + "/health", timeout=2) as response:
            self.assertEqual(json.load(response), {"status": "ok"})

    def test_second_server_reports_port_in_use_without_cleanup_error(self):
        with self.assertRaises(OSError) as raised:
            CoordinatorServer(
                ("127.0.0.1", self.server.server_port), self.database_path,
                analyzer=lambda _submissions: {},
            )
        self.assertEqual(raised.exception.errno, errno.EADDRINUSE)

    def test_analysis_reruns_after_each_snapshot_including_deletion(self):
        payload = {
            "project_id": "demo", "collection_id": "round-1", "member_id": "dany",
            "events": [{"id": "event-1", "member_id": "dany"}],
        }
        with self.post(payload) as response:
            receipt = json.load(response)
        first = self.wait_for_analysis(receipt["analysis_revision"])
        self.assertEqual(first["result"], {"event_count": 1})

        payload["events"] = []
        with self.post(payload) as response:
            receipt = json.load(response)
        second = self.wait_for_analysis(receipt["analysis_revision"])
        self.assertEqual(second["result"], {"event_count": 0})
        self.assertEqual(len(self.analysis_inputs), 2)

    def test_analysis_failure_does_not_reject_submission(self):
        def fail(_submissions):
            raise RuntimeError("model unavailable")

        self.server.analyzer = fail
        payload = {"project_id": "demo", "collection_id": "round-1", "member_id": "dany", "events": []}
        with self.post(payload) as response:
            receipt = json.load(response)
        state = self.wait_for_analysis(receipt["analysis_revision"])
        self.assertEqual(state["status"], "failed")
        self.assertEqual(state["error"], "model unavailable")
        self.assertEqual(self.server.store.list_for_collection("demo", "round-1"), [payload])

    def test_new_upload_supersedes_an_analysis_already_running(self):
        started = threading.Event()
        release = threading.Event()

        def slow_analysis(submissions):
            count = sum(len(item["events"]) for item in submissions)
            if count == 1:
                started.set()
                release.wait(timeout=2)
            return {"event_count": count}

        self.server.analyzer = slow_analysis
        payload = {
            "project_id": "demo", "collection_id": "round-1", "member_id": "dany",
            "events": [{"id": "event-1", "member_id": "dany"}],
        }
        with self.post(payload):
            pass
        self.assertTrue(started.wait(timeout=2))
        payload["events"] = []
        with self.post(payload) as response:
            revision = json.load(response)["analysis_revision"]
        release.set()
        state = self.wait_for_analysis(revision)
        self.assertEqual(state["result"], {"event_count": 0})

    def test_existing_submissions_are_analyzed_when_server_starts(self):
        legacy_path = Path(self.directory.name) / "legacy.sqlite3"
        payload = {"project_id": "demo", "collection_id": "round-1", "member_id": "dany", "events": []}
        with sqlite3.connect(legacy_path) as database:
            database.execute("""
                CREATE TABLE submissions (
                    project_id TEXT NOT NULL, collection_id TEXT NOT NULL,
                    member_id TEXT NOT NULL, received_at TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    PRIMARY KEY (project_id, collection_id, member_id)
                )
            """)
            database.execute(
                "INSERT INTO submissions VALUES (?, ?, ?, ?, ?)",
                ("demo", "round-1", "dany", "2026-11-22T00:00:00+00:00", json.dumps(payload)),
            )

        with CoordinatorServer(
            ("127.0.0.1", 0), legacy_path,
            analyzer=lambda submissions: {"event_count": sum(len(item["events"]) for item in submissions)},
        ) as restarted:
            deadline = time.monotonic() + 2
            while time.monotonic() < deadline:
                state = restarted.store.get_analysis("demo", "round-1")
                if state and state["status"] == "ready":
                    break
                time.sleep(0.01)
            self.assertEqual(state["result"], {"event_count": 0})

    def test_failed_analysis_is_retried_when_server_restarts(self):
        retry_path = Path(self.directory.name) / "retry.sqlite3"
        store = SubmissionStore(retry_path)
        payload = {"project_id": "demo", "collection_id": "round-1", "member_id": "dany", "events": []}
        revision = store.save(payload)
        store.finish_analysis("demo", "round-1", revision, error="networkx missing")

        with CoordinatorServer(
            ("127.0.0.1", 0), retry_path,
            analyzer=lambda submissions: {"event_count": sum(len(item["events"]) for item in submissions)},
        ) as restarted:
            deadline = time.monotonic() + 2
            while time.monotonic() < deadline:
                state = restarted.store.get_analysis("demo", "round-1")
                if state and state["status"] == "ready":
                    break
                time.sleep(0.01)
            self.assertEqual(state["result"], {"event_count": 0})
            self.assertIsNone(state["error"])

    def test_uploads_remain_pending_while_analysis_is_disabled(self):
        paused_path = Path(self.directory.name) / "paused.sqlite3"
        payload = {
            "project_id": "demo", "collection_id": "round-1", "member_id": "dany",
            "events": [{"id": "event-1", "member_id": "dany"}],
        }
        with CoordinatorServer(("127.0.0.1", 0), paused_path, analyzer=None) as paused:
            secret = paused.store.register_member("demo", "dany")
            thread = threading.Thread(target=paused.serve_forever, daemon=True)
            thread.start()
            try:
                request = Request(
                    f"http://127.0.0.1:{paused.server_port}/submissions",
                    data=json.dumps(payload).encode("utf-8"),
                    headers={"Content-Type": "application/json", "Authorization": f"Bearer {secret}"},
                    method="POST",
                )
                with urlopen(request, timeout=2) as response:
                    self.assertEqual(json.load(response)["analysis_status"], "pending")
            finally:
                paused.shutdown()
                thread.join(timeout=2)
            self.assertEqual(paused.store.get_analysis("demo", "round-1")["status"], "pending")
            self.assertEqual(paused.store.list_for_collection("demo", "round-1"), [payload])

        with CoordinatorServer(
            ("127.0.0.1", 0), paused_path,
            analyzer=lambda submissions: {"event_count": sum(len(item["events"]) for item in submissions)},
        ) as resumed:
            deadline = time.monotonic() + 2
            while time.monotonic() < deadline:
                state = resumed.store.get_analysis("demo", "round-1")
                if state and state["status"] == "ready":
                    break
                time.sleep(0.01)
            self.assertEqual(state["result"], {"event_count": 1})


if __name__ == "__main__":
    unittest.main()
