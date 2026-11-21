import os
import stat
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from app.calendar.google_calendar import _save_token, fetch_events, prepare_event, token_path_for_member


class FakeRequest:
    def __init__(self, response):
        self.response = response

    def execute(self):
        return self.response


class FakeEvents:
    def __init__(self):
        self.calls = []

    def list(self, **kwargs):
        self.calls.append(kwargs)
        if kwargs["pageToken"] is None:
            return FakeRequest({
                "items": [{"id": "a", "description": "full description"}],
                "nextPageToken": "page-2",
            })
        return FakeRequest({"items": [{"id": "b"}, {"id": "c", "status": "cancelled"}]})


class FakeService:
    def __init__(self):
        self.event_resource = FakeEvents()

    def events(self):
        return self.event_resource


class GoogleCalendarTests(unittest.TestCase):
    def test_fetches_all_pages_and_excludes_cancelled(self):
        service = FakeService()
        start = datetime(2026, 11, 21, tzinfo=timezone.utc)
        end = datetime(2026, 11, 28, tzinfo=timezone.utc)
        events = fetch_events(service, time_min=start, time_max=end)
        self.assertEqual([event["id"] for event in events], ["a", "b"])
        self.assertEqual(events[0]["description"], "full description")
        self.assertEqual(service.event_resource.calls[1]["pageToken"], "page-2")

    def test_handoff_preserves_context_without_inferred_task_fields(self):
        event = {
            "id": "event-123",
            "summary": "Prepare report",
            "description": "Cannot start until the budget is approved.",
            "start": {"dateTime": "2026-11-22T10:00:00+01:00"},
            "end": {"dateTime": "2026-11-22T11:00:00+01:00"},
            "organizer": {"email": "organizer@example.com"},
            "attendees": [{"email": "dany@example.com"}],
            "irrelevant_calendar_metadata": "not part of handoff",
        }
        prepared = prepare_event(event, member_id="dany", calendar_id="primary")
        self.assertEqual(prepared["member_id"], "dany")
        self.assertEqual(prepared["calendar_id"], "primary")
        self.assertEqual(prepared["description"], event["description"])
        self.assertEqual(prepared["organizer"], event["organizer"])
        self.assertEqual(prepared["attendees"], event["attendees"])
        self.assertNotIn("owner", prepared)
        self.assertNotIn("depends_on", prepared)
        self.assertNotIn("irrelevant_calendar_metadata", prepared)

    def test_member_tokens_are_separate_and_legacy_token_is_preserved(self):
        self.assertEqual(str(token_path_for_member(None)), "token.json")
        self.assertEqual(token_path_for_member("dany"), token_path_for_member("dany"))
        self.assertNotEqual(token_path_for_member("dany"), token_path_for_member("hatem"))
        self.assertEqual(token_path_for_member("dany").parent.name, "tokens")
        with self.assertRaises(ValueError):
            token_path_for_member("  ")

    def test_saved_token_is_private_even_when_replacing_an_old_file(self):
        with tempfile.TemporaryDirectory() as directory:
            token_path = Path(directory) / "tokens" / "member.json"
            _save_token(token_path, '{"token":"first"}')
            self.assertEqual(token_path.read_text(), '{"token":"first"}')
            if os.name == "posix":
                self.assertEqual(stat.S_IMODE(token_path.stat().st_mode), 0o600)
            token_path.chmod(0o644)
            _save_token(token_path, '{"token":"new"}')
            self.assertEqual(token_path.read_text(), '{"token":"new"}')
            if os.name == "posix":
                self.assertEqual(stat.S_IMODE(token_path.stat().st_mode), 0o600)


if __name__ == "__main__":
    unittest.main()
