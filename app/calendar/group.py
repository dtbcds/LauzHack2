"""Upload a member's Calendar, download group snapshots, and analyse locally."""

import json
import ssl
import time
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from app.calendar.send_to_coordinator import CalendarSnapshotSync
from app.coordinator.analysis import analyze_submissions, event_to_task
from app.coordinator.storage import SubmissionStore
from graph_construction import build_graph, graph_to_ui_data


class GroupConnection:
    def __init__(self, project_id, collection_id, member_id, *, url=None, secret=None,
                 ca_cert=None, host_store=None):
        from app.calendar.send_to_coordinator import submission_endpoint
        self.project_id, self.collection_id, self.member_id = project_id, collection_id, member_id
        self.host_store = host_store
        self.url = url
        self.secret = secret
        self.ca_cert = ca_cert
        if host_store is None:
            submission_endpoint(url or '')
            if not secret:
                raise ValueError('A member secret is required for group mode')

    def _request(self, path, *, data=None):
        identity = dict(project_id=self.project_id, collection_id=self.collection_id, member_id=self.member_id)
        request = Request(
            self.url.rstrip('/') + path + ('?' + urlencode(identity) if data is None else ''),
            data=json.dumps(identity).encode() if data is not None else None,
            headers={'Authorization': f'Bearer {self.secret}', 'Content-Type': 'application/json'},
        )
        context = ssl.create_default_context(cafile=str(self.ca_cert) if self.ca_cert else None)
        with urlopen(request, context=context, timeout=20) as response:
            return json.load(response)

    def snapshot(self):
        if self.host_store:
            return self.host_store.collection_snapshot(self.project_id, self.collection_id)
        result = self._request('/collection-snapshot')
        if (result.get('project_id') != self.project_id or result.get('collection_id') != self.collection_id
                or not isinstance(result.get('submissions'), list)):
            raise ValueError('Coordinator returned the wrong group snapshot')
        return result

    def request_refresh(self):
        if self.host_store:
            return self.host_store.request_refresh(self.project_id, self.collection_id)
        return self._request('/refresh', data=True)['revision']


class GroupCalendar:
    def __init__(self, connection, database, *, credentials='credentials.json', analyzer=analyze_submissions):
        self.connection = connection
        self.store = SubmissionStore(database)
        self.project_id, self.collection_id = connection.project_id, connection.collection_id
        self.credentials = credentials
        self.analyzer = analyzer
        self.sync = None
        self._last_upload = 0
        self._acked = 0
        self._attempted = None
        self._force = False
        self._fingerprint = self._hash(self.store.list_for_collection(self.project_id, self.collection_id))
        self.message = 'Connecting to group…'

    @staticmethod
    def _hash(submissions):
        # Ignore member/event ordering when deciding whether model work is needed.
        canonical = [{**item, 'events': sorted(item['events'], key=lambda event: event['id'])}
                     for item in sorted(submissions, key=lambda item: item['member_id'])]
        return json.dumps(canonical, sort_keys=True, ensure_ascii=False)

    def refresh(self):
        self.connection.request_refresh()
        self._force = True
        self._attempted = None
        self.message = 'Group refresh requested.'

    def _receive(self, snapshot):
        submissions = snapshot['submissions']
        fingerprint = self._hash(submissions)
        if (fingerprint != self._fingerprint
                or self.store.get_analysis(self.project_id, self.collection_id) is None):
            self.store.replace_collection(self.project_id, self.collection_id, submissions)
            self._fingerprint = fingerprint
        count = sum(len(item['events']) for item in submissions)
        self.message = f'Group synced: {len(submissions)} members, {count} Calendar items.'

    def poll(self):
        snapshot = self.connection.snapshot()
        self._receive(snapshot)
        revision = snapshot['refresh_revision']
        if self._force or revision > self._acked or time.monotonic() - self._last_upload >= 30:
            if self.sync is None:
                self.sync = CalendarSnapshotSync(
                    project_id=self.project_id, collection_id=self.collection_id,
                    member_id=self.connection.member_id,
                    coordinator_url=self.connection.url or 'http://127.0.0.1:8000',
                    secret=self.connection.secret or 'local', ca_cert=self.connection.ca_cert,
                    credentials_path=self.credentials,
                    uploader=self._host_upload if self.connection.host_store else None,
                )
            self.sync.sync_once(refresh_revision=revision if revision > self._acked else None)
            self._acked = revision
            self._last_upload = time.monotonic()
            self._force = False
            self._receive(self.connection.snapshot())

    def _host_upload(self, payload, *, refresh_revision=None):
        revision = self.connection.host_store.save(payload, refresh_revision=refresh_revision)
        return {'received': True, 'member_id': self.connection.member_id,
                'event_count': len(payload['events']), 'analysis_revision': revision}

    def analyze_pending(self):
        state = self.store.get_analysis(self.project_id, self.collection_id)
        if state is None or state['revision'] == self._attempted or state['status'] == 'ready':
            return
        revision = state['revision']
        self._attempted = revision
        if not self.store.mark_analysis_processing(self.project_id, self.collection_id, revision):
            return
        submissions = self.store.list_for_collection(self.project_id, self.collection_id)
        try:
            if self.analyzer is analyze_submissions:
                def publish(result, completed, total):
                    if not self.store.save_analysis_progress(
                        self.project_id, self.collection_id, revision, result, completed, total,
                    ):
                        raise RuntimeError('Group changed during analysis')
                result = self.analyzer(submissions, on_progress=publish)
            else:
                result = self.analyzer(submissions)
            self.store.finish_analysis(self.project_id, self.collection_id, revision, result=result)
        except Exception as error:
            self.store.finish_analysis(self.project_id, self.collection_id, revision, error=str(error))

    def view(self):
        state = self.store.get_analysis(self.project_id, self.collection_id)
        if state is None or state['result'] is not None:
            return state
        tasks = [event_to_task(event, item['member_id'])
                 for item in self.store.list_for_collection(self.project_id, self.collection_id)
                 for event in item['events']]
        preview = graph_to_ui_data(build_graph(tasks, []), now=state['updated_at'])
        preview['analysis_progress'] = {'completed': 0, 'total': len(tasks)}
        return {**state, 'result': preview}
