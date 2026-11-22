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


def test_linked_task_notes_replace_placeholder_across_pages():
    from unittest.mock import Mock
    from app.calendar.google_calendar import fill_task_descriptions
    service = Mock()
    service.tasklists.return_value.list.return_value.execute.side_effect = [
        {'items': [{'id': 'list1'}], 'nextPageToken': 'lists2'},
        {'items': [{'id': 'list2'}]},
    ]
    service.tasks.return_value.list.return_value.execute.side_effect = [
        {'items': [{'id': 'api-a', 'title': 'Same title', 'notes': 'Wrong task',
                    'webViewLink': 'https://tasks.google.com/task/other'}], 'nextPageToken': 'tasks2'},
        {'items': [{'id': 'api-b', 'title': 'Same title', 'notes': 'Wait for architecture',
                    'webViewLink': 'https://tasks.google.com/task/link-b'}]},
        {'items': [{'id': 'api-c', 'webViewLink': 'https://tasks.google.com/task/link-c'}]},
    ]
    events = [
        {'id': 'event1', 'description': 'Placeholder https://tasks.google.com/task/link-b.'},
        {'id': 'event2', 'description': 'Placeholder https://tasks.google.com/task/link-c.'},
        {'id': 'event3', 'description': 'Ordinary description'},
    ]
    result = fill_task_descriptions(events, service)
    assert [event['description'] for event in result] == ['Wait for architecture', '', 'Ordinary description']
    assert events[0]['description'].startswith('Placeholder')
    assert service.tasklists.return_value.list.call_args_list[1].kwargs['pageToken'] == 'lists2'
    assert service.tasks.return_value.list.call_args_list[1].kwargs['pageToken'] == 'tasks2'


def test_regular_events_do_not_fetch_tasks_and_unmatched_links_fail():
    import pytest
    from unittest.mock import Mock
    from app.calendar.google_calendar import fill_task_descriptions
    service = Mock()
    events = [{'id': 'ordinary', 'description': 'No task link'}]
    assert fill_task_descriptions(events, service) == events
    service.tasklists.assert_not_called()
    service.tasklists.return_value.list.return_value.execute.return_value = {'items': []}
    with pytest.raises(RuntimeError, match='Could not match Google Tasks link'):
        fill_task_descriptions([{'id': 'linked', 'description': 'https://tasks.google.com/task/missing'}], service)


def test_calendar_only_token_requests_both_scopes_again(tmp_path):
    from unittest.mock import Mock, patch
    from app.calendar.google_calendar import connect_calendar, SCOPES
    credential_file = tmp_path / 'credentials.json'
    token_file = tmp_path / 'token.json'
    credential_file.write_text('{}')
    token_file.write_text('{}')
    old = Mock(valid=True)
    old.has_scopes.return_value = False
    fresh = Mock()
    fresh.to_json.return_value = '{"scopes": []}'
    with patch('google.oauth2.credentials.Credentials.from_authorized_user_file', return_value=old) as load, \
         patch('google_auth_oauthlib.flow.InstalledAppFlow.from_client_secrets_file') as flow, \
         patch('googleapiclient.discovery.build') as build:
        flow.return_value.run_local_server.return_value = fresh
        connect_calendar(credential_file, token_file)
        load.assert_called_once_with(str(token_file))
        flow.assert_called_once_with(str(credential_file), SCOPES)
        assert build.call_args_list[0].kwargs['credentials'] is fresh
        assert build.call_args_list[1].args == ('tasks', 'v1')
        assert token_file.read_text() == fresh.to_json.return_value
