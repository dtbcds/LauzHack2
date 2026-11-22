import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / 'src'))

from analysis_data import analysis_message, tasks_from_snapshot
from app.coordinator.analysis import analyze_submissions
from component import task_detail
from graph import TaskGraph
from queries import TaskQueries
from workspace import mount_workspace


def test_saved_graph_connects_list_graph_queries_and_unknown_status():
    def extractor(target, candidates):
        if target['id'].endswith(':ship'):
            return {'dependencies': [{
                'prerequisite_task_id': candidates[0]['id'],
                'dependent_task_id': target['id'], 'type': 'soft',
                'evidence': 'after approval', 'confidence': 0.9,
            }]}
        return {'dependencies': []}

    snapshot = analyze_submissions([
        {'member_id': 'dany', 'events': [{'id': 'approve', 'summary': 'Approve'}]},
        {'member_id': 'hatem', 'events': [{'id': 'ship', 'summary': 'Ship'}]},
    ], extractor=extractor)
    tasks = tasks_from_snapshot(snapshot)
    by_id = {task.id: task for task in tasks}
    assert by_id['hatem:primary:ship'].prerequisites == ('dany:primary:approve',)
    assert all(task.status == 'unknown' for task in tasks)
    assert tasks[0].score == snapshot['nodes'][0]['priority']['priority_score']
    graph = TaskGraph(lambda task: None)
    graph.set_tasks(tasks, snapshot)
    assert graph._graph.edges['dany:primary:approve', 'hatem:primary:ship']['type'] == 'soft'
    graph.render(None, set())
    assert TaskQueries(tasks).slip_impact('dany:primary:approve').direct[0].title == 'Ship'
    task_detail(tasks[1], lambda task: None, {task.id: task.title for task in tasks})

    class Page:
        def add(self, control):
            self.control = control

    update = mount_workspace(Page(), {'live': tasks}, snapshots={'live': snapshot})
    update('live', (), {'nodes': [], 'edges': []})


def test_analysis_states_and_empty_result():
    assert 'uploads' in analysis_message(None)
    assert 'queued' in analysis_message({'status': 'pending'})
    assert 'Analysing' in analysis_message({'status': 'processing'})
    assert 'offline' in analysis_message({'status': 'failed', 'error': 'offline'})
    assert 'previous graph' in analysis_message({'status': 'processing', 'result': {'nodes': []}})
    assert '1/3 tasks checked' in analysis_message({
        'status': 'processing',
        'result': {'nodes': [], 'analysis_progress': {'completed': 1, 'total': 3}},
    })
    assert 'partial graph' in analysis_message({
        'status': 'failed', 'error': 'invalid link',
        'result': {'nodes': [], 'analysis_progress': {'completed': 1, 'total': 3}},
    })
    assert analysis_message({'status': 'ready', 'result': {'nodes': []}}) == ''
    assert tasks_from_snapshot({'nodes': [], 'edges': []}) == ()


def test_refresh_button_requests_selected_collection(tmp_path, monkeypatch):
    import asyncio
    import importlib.util
    from app.coordinator.storage import SubmissionStore

    spec = importlib.util.spec_from_file_location('relay_ui_main', Path(__file__).parents[1] / 'src/main.py')
    ui = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ui)
    database = tmp_path / 'coordinator.sqlite3'
    store = SubmissionStore(database)
    store.register_member('team', 'dany')
    monkeypatch.setenv('RELAY_DATABASE', str(database))
    monkeypatch.setenv('RELAY_PROJECT_ID', 'team')
    monkeypatch.setenv('RELAY_COLLECTION_ID', 'round-2')
    captured = {}

    def mount(page, organisations, **kwargs):
        captured.update(kwargs)
        return lambda *args: None

    monkeypatch.setattr(ui, 'mount_workspace', mount)

    class Page:
        class Window:
            pass
        window = Window()

        def update(self):
            pass

        def run_task(self, handler):
            self.handler = handler

    ui.main(Page())
    button = captured['refresh_control']
    asyncio.run(button.on_click())
    assert store.get_refresh_revision('team', 'round-2') == 1
    assert not button.disabled
    assert 'dany' in captured['status_control'].controls[0].value


def test_coordinator_can_be_excluded_from_refresh_without_losing_access(tmp_path):
    from app.coordinator.storage import SubmissionStore
    database = tmp_path / 'coordinator.sqlite3'
    store = SubmissionStore(database)
    secret = store.register_member('team', 'nil')
    store.register_member('team', 'dany')
    store.set_refresh_enabled('team', 'nil', False)
    store.request_refresh('team', 'round-1')
    restarted = SubmissionStore(database)
    assert restarted.get_refresh_status('team', 'round-1')['members'] == {'dany': 'waiting'}
    assert restarted.is_authorized('team', 'nil', secret)
    restarted.set_refresh_enabled('team', 'nil', True)
    assert set(restarted.get_refresh_status('team', 'round-1')['members']) == {'nil', 'dany'}


def test_group_secret_is_requested_before_window_opens(monkeypatch):
    import importlib.util
    spec = importlib.util.spec_from_file_location('relay_startup', Path(__file__).parents[1] / 'src/main.py')
    ui = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ui)
    order = []
    monkeypatch.setattr(ui, 'configure_desktop_client', lambda: order.append('configured'))
    monkeypatch.setattr(ui.getpass, 'getpass', lambda prompt: order.append('secret') or 'test-secret')
    monkeypatch.setattr(ui, 'main', lambda page, *, group_secret: order.append(('mounted', group_secret)))
    def run(callback):
        order.append('window')
        callback(object())
    monkeypatch.setattr(ui.ft, 'run', run)
    ui.launch(['--mode', 'group', '--member-id', 'hatem', '--coordinator-url', 'https://127.0.0.1:8000'])
    assert order == ['configured', 'secret', 'window', ('mounted', 'test-secret')]


def test_group_page_mounts_without_terminal_input(tmp_path, monkeypatch):
    import importlib.util
    spec = importlib.util.spec_from_file_location('relay_group_page', Path(__file__).parents[1] / 'src/main.py')
    ui = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ui)
    monkeypatch.setattr(ui, 'ROOT', tmp_path)
    monkeypatch.setenv('RELAY_MODE', 'group')
    monkeypatch.setenv('RELAY_MEMBER_ID', 'hatem')
    monkeypatch.setenv('RELAY_COORDINATOR_URL', 'https://127.0.0.1:8000')
    def unexpected_prompt(prompt):
        raise AssertionError('Page startup must not wait for terminal input')
    monkeypatch.setattr(ui.getpass, 'getpass', unexpected_prompt)
    class Page:
        class Window:
            pass
        window = Window()
        controls = []
        jobs = []
        def add(self, control):
            self.controls.append(control)
        def run_task(self, callback):
            self.jobs.append(callback)
    page = Page()
    ui.main(page, group_secret='test-secret')
    assert len(page.controls) == 1
    assert len(page.jobs) == 3
    assert 'Group (hatem)' in page.title
