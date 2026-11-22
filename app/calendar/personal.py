"""Fetch and analyse one person's Calendar locally, without an HTTP coordinator."""

from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.calendar.google_calendar import connect_calendar, fetch_events, prepare_event, token_path_for_member
from app.coordinator.analysis import analyze_submissions, event_to_task
from app.coordinator.storage import SubmissionStore
from graph_construction import build_graph, graph_to_ui_data


class PersonalCalendar:
    def __init__(self, member_id: str, database: Path, *, credentials='credentials.json',
                 calendar_id='primary', days_ahead=14, service=None, analyzer=analyze_submissions):
        if not member_id.strip():
            raise ValueError('A member ID is required for personal mode')
        self.member_id = member_id
        self.project_id = f'personal:{member_id}'
        self.collection_id = 'calendar'
        self.store = SubmissionStore(database)
        self.credentials = credentials
        self.calendar_id = calendar_id
        self.days_ahead = days_ahead
        self.service = service
        self.analyzer = analyzer

    def sync(self):
        if self.service is None:
            self.service = connect_calendar(self.credentials, token_path_for_member(self.member_id))
        now = datetime.now(timezone.utc)
        events = fetch_events(self.service, calendar_id=self.calendar_id,
                              time_min=now, time_max=now + timedelta(days=self.days_ahead))
        payload = {
            'project_id': self.project_id, 'collection_id': self.collection_id,
            'member_id': self.member_id,
            'events': [prepare_event(event, member_id=self.member_id, calendar_id=self.calendar_id)
                       for event in events],
        }
        revision = self.store.save(payload)
        self.store.mark_analysis_processing(self.project_id, self.collection_id, revision)
        try:
            result = self.analyzer([payload])
            self.store.finish_analysis(self.project_id, self.collection_id, revision, result=result)
        except Exception as error:
            self.store.finish_analysis(self.project_id, self.collection_id, revision, error=str(error))

    def view(self):
        state = self.store.get_analysis(self.project_id, self.collection_id)
        if state is None or state['status'] == 'ready':
            return state
        # Show the latest Calendar items while dependencies are unavailable.
        tasks = [event_to_task(event, item['member_id'])
                 for item in self.store.list_for_collection(self.project_id, self.collection_id)
                 for event in item['events']]
        return {**state, 'result': graph_to_ui_data(build_graph(tasks, []), now=state['updated_at'])}
