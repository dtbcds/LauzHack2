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
