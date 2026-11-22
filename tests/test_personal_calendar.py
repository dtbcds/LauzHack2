from unittest.mock import patch

from app.calendar.personal import PersonalCalendar
from app.coordinator.analysis import analyze_submissions


def test_personal_items_visible_before_and_after_local_analysis(tmp_path):
    holder = {}

    def analyze(submissions):
        # During model work the UI must already see fetched items.
        view = holder['calendar'].view()
        assert view['status'] == 'processing'
        assert [node['title'] for node in view['result']['nodes']] == ['Approve', 'Ship']
        def extract(target, candidates):
            if target['title'] == 'Ship':
                return {'dependencies': [{
                    'prerequisite_task_id': candidates[0]['id'], 'dependent_task_id': target['id'],
                    'type': 'hard', 'evidence': 'after approval', 'confidence': 1,
                }]}
            return {'dependencies': []}
        return analyze_submissions(submissions, extractor=extract)

    calendar = PersonalCalendar('dany', tmp_path / 'local.sqlite3', service=object(), analyzer=analyze)
    holder['calendar'] = calendar
    with patch('app.calendar.personal.fetch_events', return_value=[
        {'id': 'a', 'summary': 'Approve'},
        {'id': 'b', 'summary': 'Ship', 'description': 'Ship after approval'},
    ]):
        calendar.sync()
    state = calendar.view()
    assert state['status'] == 'ready'
    assert len(state['result']['edges']) == 1
    assert state['project_id'] == 'personal:dany'


def test_personal_model_failure_still_shows_items_and_deletion(tmp_path):
    def fail(submissions):
        raise RuntimeError('OpenAI unavailable')

    calendar = PersonalCalendar('dany', tmp_path / 'local.sqlite3', service=object(), analyzer=fail)
    with patch('app.calendar.personal.fetch_events', return_value=[{'id': 'a', 'summary': 'My task'}]):
        calendar.sync()
    state = calendar.view()
    assert state['status'] == 'failed'
    assert state['error'] == 'OpenAI unavailable'
    assert state['result']['nodes'][0]['title'] == 'My task'
    assert calendar.view() == state
    with patch('app.calendar.personal.fetch_events', return_value=[]):
        calendar.sync()
    assert calendar.view()['result']['nodes'] == []
