import threading
from unittest.mock import patch

import pytest
from urllib.error import HTTPError

from app.calendar.group import GroupCalendar, GroupConnection
from app.coordinator.analysis import analyze_submissions
from app.coordinator.server import CoordinatorServer


@pytest.fixture
def coordinator(tmp_path):
    server = CoordinatorServer(('127.0.0.1', 0), tmp_path / 'coordinator.sqlite3', analyzer=None)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server, f'http://127.0.0.1:{server.server_port}'
    finally:
        server.shutdown()
        thread.join(timeout=2)
        server.server_close()


def test_all_members_receive_same_group_and_analyse_locally(coordinator, tmp_path):
    server, url = coordinator
    calendars = {
        'nil': [{'id': 'design', 'summary': 'Design', 'description': 'Define architecture'}],
        'dany': [{'id': 'code', 'summary': 'Code', 'description': 'Code after Design'}],
        'hatem': [{'id': 'test', 'summary': 'Test', 'description': 'Test the code'}],
    }
    calls = []

    def analyze(submissions):
        calls.append(submissions)
        def extract(target, candidates):
            if target['title'] == 'Code':
                prerequisite = next(item for item in candidates if item['title'] == 'Design')
                return {'dependencies': [{
                    'prerequisite_task_id': prerequisite['id'], 'dependent_task_id': target['id'],
                    'type': 'hard', 'evidence': 'Code after Design', 'confidence': 1,
                }]}
            return {'dependencies': []}
        return analyze_submissions(submissions, extractor=extract)

    clients = []
    for member in calendars:
        if member == 'nil':
            connection = GroupConnection('demo', 'round-1', member, host_store=server.store)
        else:
            secret = server.store.register_member('demo', member)
            connection = GroupConnection('demo', 'round-1', member, url=url, secret=secret)
        clients.append(GroupCalendar(connection, tmp_path / f'{member}.sqlite3', analyzer=analyze))

    # Each sync uses that member's own authorization and Calendar data.
    with patch('app.calendar.send_to_coordinator.connect_calendar', side_effect=lambda credentials, token: token), \
         patch('app.calendar.send_to_coordinator.fetch_events') as fetch:
        for member, client in zip(calendars, clients):
            fetch.return_value = calendars[member]
            client.poll()
        for client in clients:
            client.poll()
            preview = client.view()
            assert {node['owner'] for node in preview['result']['nodes']} == {'nil', 'dany', 'hatem'}
            client.analyze_pending()
            result = client.view()
            assert result['status'] == 'ready'
            assert len(result['result']['edges']) == 1
        assert len(calls) == 3
        for client in clients:
            client.poll()
            client.analyze_pending()
        assert len(calls) == 3  # Unchanged snapshots do not rerun the model.
        # Hatem deletes his event. His new snapshot replaces it everywhere.
        clients[2].refresh()
        fetch.return_value = []
        clients[2].poll()
        # Poll the others after acknowledging the refresh, using their own events.
        for index, member in enumerate(('nil', 'dany')):
            fetch.return_value = calendars[member]
            clients[index].poll()
        for client in clients:
            client.poll()
            client.analyze_pending()
            assert {node['owner'] for node in client.view()['result']['nodes']} == {'nil', 'dany'}
        clients[1].refresh()
        calendars['dany'][0]['description'] = 'Edited description'
        for index, member in enumerate(calendars):
            fetch.return_value = calendars[member] if member != 'hatem' else []
            clients[index].poll()
        for client in clients:
            client.poll()
            descriptions = [node['description'] for node in client.view()['result']['nodes']]
            assert 'Edited description' in descriptions
    assert {item['member_id'] for item in server.store.list_for_collection('demo', 'round-1')} == {'nil', 'dany', 'hatem'}


def test_snapshot_and_refresh_require_project_member_secret(coordinator):
    server, url = coordinator
    secret = server.store.register_member('demo', 'dany')
    server.store.save({'project_id': 'other', 'collection_id': 'round-1', 'member_id': 'private', 'events': []})
    client = GroupConnection('demo', 'round-1', 'dany', url=url, secret=secret)
    assert client.snapshot()['submissions'] == []
    assert client.request_refresh() == 1
    for project, member, supplied in [('other', 'dany', secret), ('demo', 'hatem', secret), ('demo', 'dany', 'wrong')]:
        unauthorized = GroupConnection(project, 'round-1', member, url=url, secret=supplied)
        with pytest.raises(HTTPError) as error:
            unauthorized.snapshot()
        assert error.value.code == 401
        with pytest.raises(HTTPError) as error:
            unauthorized.request_refresh()
        assert error.value.code == 401


def test_local_failure_keeps_group_items_and_no_automatic_model_retry(tmp_path):
    from app.coordinator.storage import SubmissionStore
    source = SubmissionStore(tmp_path / 'source.sqlite3')
    source.save({'project_id': 'demo', 'collection_id': 'round-1', 'member_id': 'hatem',
                 'events': [{'id': 'x', 'summary': 'Hatem task', 'description': 'Real notes'}]})
    calls = []
    def fail(submissions):
        calls.append(submissions)
        raise RuntimeError('Model not running')
    group = GroupCalendar(GroupConnection('demo', 'round-1', 'nil', host_store=source),
                          tmp_path / 'cache.sqlite3', analyzer=fail)
    group._receive(source.collection_snapshot('demo', 'round-1'))
    group.analyze_pending()
    assert group.view()['status'] == 'failed'
    assert group.view()['result']['nodes'][0]['description'] == 'Real notes'
    group.analyze_pending()
    assert len(calls) == 1
    group.refresh()
    group.analyze_pending()
    assert len(calls) == 2


def test_calendar_upload_only_at_startup_or_coordinator_request(coordinator, tmp_path):
    server, url = coordinator
    secret = server.store.register_member('demo', 'hatem')
    group = GroupCalendar(GroupConnection('demo', 'round-1', 'hatem', url=url, secret=secret),
                          tmp_path / 'hatem.sqlite3')
    with patch('app.calendar.send_to_coordinator.connect_calendar', return_value=object()), \
         patch('app.calendar.send_to_coordinator.fetch_events', return_value=[{'id': 'a', 'summary': 'Before'}]) as fetch:
        group.poll()
        assert fetch.call_count == 1
        fetch.return_value = [{'id': 'a', 'summary': 'Edited on Google'}]
        for _ in range(5):
            group.poll()
        assert fetch.call_count == 1
        saved = server.store.list_for_collection('demo', 'round-1')[0]
        assert saved['events'][0]['summary'] == 'Before'
        # Nil requests refresh on the coordinator; Hatem responds on his next poll.
        revision = server.store.request_refresh('demo', 'round-1')
        group.poll()
        assert fetch.call_count == 2
        saved = server.store.list_for_collection('demo', 'round-1')[0]
        assert saved['events'][0]['summary'] == 'Edited on Google'
        assert server.store.get_refresh_status('demo', 'round-1')['members']['hatem'] == 'received'
        assert group.connection.snapshot()['refresh_revision'] == revision
        group.poll()
        assert fetch.call_count == 2


def test_old_qwen_result_is_recomputed_when_group_uses_openai(tmp_path, monkeypatch):
    from app.coordinator.storage import SubmissionStore
    import dependency_extraction
    source = SubmissionStore(tmp_path / 'source.sqlite3')
    group = GroupCalendar(GroupConnection('demo', 'round-1', 'nil', host_store=source), tmp_path / 'cache.sqlite3')
    submissions = [{'project_id': 'demo', 'collection_id': 'round-1', 'member_id': 'nil',
                    'events': [{'id': 'a', 'summary': 'Report'}, {'id': 'b', 'summary': 'Presentation'}]}]
    revision = group.store.replace_collection('demo', 'round-1', submissions)
    group.store.finish_analysis('demo', 'round-1', revision, result={'nodes': [], 'edges': []})
    calls = []
    monkeypatch.setattr(dependency_extraction, 'extract_group_dependencies',
                        lambda tasks: calls.append(tasks) or {'dependencies': []})
    from app.coordinator.analysis import _dependency_cache
    _dependency_cache.clear()
    group.analyze_pending()
    assert len(calls) == 1
    assert group.view()['status'] == 'ready'
    assert group.view()['result']['analysis_engine'] == dependency_extraction.cache_namespace()
    group.analyze_pending()
    assert len(calls) == 1
    _dependency_cache.clear()
