"""Focused live regression checks for direction and real circular dependencies."""
import os

import pytest

from dependency_extraction import extract_group_dependencies


def task(key, title, description):
    return {'id': key, 'title': title, 'description': description, 'owner': key}


@pytest.mark.skipif(os.getenv('RUN_LIVE_OPENAI') != '1', reason='set RUN_LIVE_OPENAI=1')
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
    ([task('A', 'Report', 'Make the report'),
      task('B', 'presentation', 'Based on the report make a presentation'),
      task('C', 'grade the presentation', 'Rate the presentation')],
     {('A', 'B'), ('B', 'C')}),
    ([task('A', 'Buy paper', 'Buy A4 paper. No prerequisites.'),
      task('B', 'Design poster', 'Design a digital poster. No prerequisites.')], set()),
], ids=['paper-chain', 'survey-chain', 'genuine-cycle', 'implicit-grading-chain', 'independent'])
def test_model_dependency_direction(tasks, expected):
    result = extract_group_dependencies(tasks)
    print(result, flush=True)
    actual = {(item['prerequisite_task_id'], item['dependent_task_id']) for item in result['dependencies']}
    assert actual == expected
