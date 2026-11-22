import json
from types import SimpleNamespace

import pytest
import dependency_extraction as extraction

TASKS = [
    {'id': 'calendar:long:A', 'title': 'Report', 'description': 'Make the report', 'owner': 'nil'},
    {'id': 'calendar:long:B', 'title': 'Presentation', 'description': 'Based on the report make a presentation', 'owner': 'dany'},
]


def edge(source='T1', target='T2', kind='hard', evidence='Based on the report make a presentation'):
    return dict(prerequisite_task_id=source, dependent_task_id=target, type=kind, evidence=evidence)


def test_batch_maps_short_ids_and_preserves_evidence(monkeypatch):
    seen = []
    def request(tasks, schema):
        seen.append((tasks, schema))
        return {'dependencies': [edge(), edge()]}
    monkeypatch.setattr(extraction, '_request', request)
    result = extraction.extract_group_dependencies(TASKS)
    assert len(seen) == 1
    assert seen[0][1]['properties']['dependencies']['items']['properties']['dependent_task_id']['enum'] == ['T1', 'T2']
    assert result['dependencies'] == [dict(prerequisite_task_id=TASKS[0]['id'], dependent_task_id=TASKS[1]['id'],
                                         type='hard', weight=1.0, evidence=TASKS[1]['description'])]
    assert 'confidence' not in result['dependencies'][0]


@pytest.mark.parametrize('change', [
    {'prerequisite_task_id': 'invented'}, {'dependent_task_id': 'T1'},
    {'type': 'invented'}, {'evidence': 'fabricated evidence'},
])
def test_invalid_links_fail_instead_of_silently_disappearing(monkeypatch, change):
    monkeypatch.setattr(extraction, '_request', lambda tasks, schema: {'dependencies': [{**edge(), **change}]})
    with pytest.raises(ValueError):
        extraction.extract_group_dependencies(TASKS)


def test_real_reciprocal_links_are_retained(monkeypatch):
    tasks = [dict(id='A', description='Wait for B'), dict(id='B', description='Wait for A')]
    monkeypatch.setattr(extraction, '_request', lambda tasks, schema: {'dependencies': [
        edge('T2', 'T1', evidence='Wait for B'), edge('T1', 'T2', evidence='Wait for A'),
    ]})
    result = extraction.extract_group_dependencies(tasks)
    assert len(result['dependencies']) == 2


def test_no_api_for_zero_or_one_task(monkeypatch):
    def fail(*args):
        raise AssertionError('Unexpected paid API call')
    monkeypatch.setattr(extraction, '_request', fail)
    assert extraction.extract_group_dependencies([]) == {'dependencies': []}
    assert extraction.extract_group_dependencies(TASKS[:1]) == {'dependencies': []}


def test_duplicate_ids_rejected():
    with pytest.raises(ValueError, match='Duplicate'):
        extraction.extract_group_dependencies([TASKS[0], TASKS[0]])


def test_env_is_loaded_from_repo_without_changing_environment(tmp_path, monkeypatch):
    monkeypatch.setattr(extraction, 'ROOT', tmp_path)
    monkeypatch.delenv('OPENAI_API_KEY', raising=False)
    monkeypatch.delenv('OPENAI_MODEL', raising=False)
    (tmp_path / '.env').write_text('OPENAI_API_KEY=local-test-key\nOPENAI_MODEL=test-model\n')
    assert extraction.settings() == ('local-test-key', 'test-model')
    monkeypatch.setenv('OPENAI_API_KEY', 'environment-test-key')
    assert extraction.settings()[0] == 'environment-test-key'


def test_request_uses_strict_schema_no_storage_and_omits_secret_from_input(monkeypatch):
    captured = {}
    class Client:
        def __init__(self, **kwargs):
            assert kwargs['api_key'] == 'private-test-key'
            self.responses = self
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def create(self, **kwargs):
            captured.update(kwargs)
            return SimpleNamespace(status='completed', output_text='{"dependencies": []}')
    monkeypatch.setattr(extraction, 'OpenAI', Client)
    monkeypatch.setattr(extraction, 'settings', lambda: ('private-test-key', 'gpt-4.1'))
    extraction.extract_group_dependencies(TASKS)
    assert captured['store'] is False
    assert captured['text']['format']['strict'] is True
    assert 'private-test-key' not in json.dumps(captured)
    assert len(json.loads(captured['input'])['tasks']) == 2


def test_missing_key_is_actionable(monkeypatch):
    monkeypatch.setattr(extraction, 'settings', lambda: ('', 'gpt-4.1'))
    with pytest.raises(RuntimeError, match='OPENAI_API_KEY'):
        extraction.extract_group_dependencies(TASKS)


def test_html_is_normalized_for_evidence(monkeypatch):
    tasks = [TASKS[0], {**TASKS[1], 'description': '<span>Based on the report make a presentation</span>'}]
    def request(items, schema):
        assert items[1]['description'] == TASKS[1]['description']
        return {'dependencies': [edge()]}
    monkeypatch.setattr(extraction, '_request', request)
    assert extraction.extract_group_dependencies(tasks)['dependencies'][0]['type'] == 'hard'


@pytest.mark.parametrize('status,text', [('incomplete', '{}'), ('completed', ''), ('completed', 'not json')])
def test_incomplete_or_invalid_api_response_reports_failure(monkeypatch, status, text):
    class Client:
        def __init__(self, **kwargs): self.responses = self
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def create(self, **kwargs): return SimpleNamespace(status=status, output_text=text)
    monkeypatch.setattr(extraction, 'OpenAI', Client)
    monkeypatch.setattr(extraction, 'settings', lambda: ('private-test-key', 'gpt-4.1'))
    with pytest.raises(RuntimeError):
        extraction.extract_group_dependencies(TASKS)
