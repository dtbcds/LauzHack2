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
