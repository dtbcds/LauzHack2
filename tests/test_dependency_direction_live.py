"""Focused live regression checks for direction and real circular dependencies."""
import os

import pytest

from dependency_extraction import extract_dependencies


def task(key, title, description):
    return {'id': key, 'title': title, 'description': description, 'owner': key}


@pytest.mark.skipif(os.getenv('RUN_LIVE_DIRECTION') != '1', reason='set RUN_LIVE_DIRECTION=1')
@pytest.mark.parametrize(('tasks', 'expected'), [
    ([task('A', 'Buy printer paper', 'Buy a pack of A4 paper. This task has no prerequisites.'),
      task('B', 'Print event posters', 'Wait for Nil to finish "Buy printer paper". Use that paper to print ten posters.')],
     {('A', 'B')}),
    ([task('A', 'Send survey', 'Send the customer survey and export the collected responses to a spreadsheet.'),
      task('B', 'Analyse survey responses', 'Cannot start until "Send survey" is complete. Use its response spreadsheet to calculate the results.'),
      task('C', 'Create presentation', 'Cannot start until "Analyse survey responses" is complete. Turn its calculated results into presentation slides.')],
     {('A', 'B'), ('B', 'C')}),
    ([task('A', 'Approve design', 'Cannot start until "Approve budget" is complete.'),
      task('B', 'Approve budget', 'Cannot start until "Approve design" is complete.')],
     {('A', 'B'), ('B', 'A')}),
], ids=['paper-chain', 'survey-chain', 'genuine-cycle'])
def test_model_dependency_direction(tasks, expected):
    actual = set()
    for target in tasks:
        result = extract_dependencies(target, [item for item in tasks if item['id'] != target['id']])
        print(target['title'], result, flush=True)
        actual.update((item['prerequisite_task_id'], item['dependent_task_id'])
                      for item in result['dependencies'])
    assert actual == expected
