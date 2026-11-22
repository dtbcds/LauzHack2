"""HTTP(S) receiver for Calendar event submissions."""

from __future__ import annotations

import argparse
import json
import queue
import sqlite3
import ssl
import sys
import threading
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qs, urlsplit

from app.coordinator.analysis import analyze_submissions
from app.coordinator.storage import SubmissionStore

MAX_BODY_BYTES = 2_000_000
SUBMISSION_FIELDS = {"project_id", "collection_id", "member_id", "events"}
EVENT_FIELDS = {
    "id", "member_id", "calendar_id", "summary", "description",
    "start", "end", "organizer", "attendees",
}


class SupersededAnalysis(Exception):
    """A newer upload replaced the revision being analysed."""


def validate_submission(payload: Any) -> dict[str, Any]:
    """Check the employee-to-coordinator JSON contract."""
    if not isinstance(payload, dict):
        raise ValueError("Submission must be a JSON object")
    if extra := set(payload) - SUBMISSION_FIELDS:
        raise ValueError(f"Unknown submission fields: {', '.join(sorted(extra))}")
    for field in ("project_id", "collection_id", "member_id"):
        if not isinstance(payload.get(field), str) or not payload[field].strip():
            raise ValueError(f"{field} must be a non-empty string")
    events = payload.get("events")
    if not isinstance(events, list):
        raise ValueError("events must be an array")
    for index, event in enumerate(events):
        if not isinstance(event, dict) or not isinstance(event.get("id"), str) or not event["id"]:
            raise ValueError(f"events[{index}] must have an id")
        if extra := set(event) - EVENT_FIELDS:
            raise ValueError(f"events[{index}] has unknown fields: {', '.join(sorted(extra))}")
        if event.get("member_id") not in (None, payload["member_id"]):
            raise ValueError(f"events[{index}] has a different member_id")
    return payload


class CoordinatorServer(ThreadingHTTPServer):
    """Receive submissions and persist them in a local SQLite database."""

    daemon_threads = True

    def __init__(
        self, address: tuple[str, int], database_path: str | Path = "data/coordinator.sqlite3",
        analyzer: Callable[[list[dict[str, Any]]], dict[str, Any]] | None = analyze_submissions,
    ):
        self.store = SubmissionStore(database_path)
        self.analyzer = analyzer
        self.analysis_queue: queue.Queue[tuple[str, str, int] | None] = queue.Queue()
        self.analysis_worker: threading.Thread | None = None
        super().__init__(address, CoordinatorHandler)
        if analyzer is not None:
            self.analysis_worker = threading.Thread(target=self._run_analysis, daemon=True)
            self.analysis_worker.start()
            for job in self.store.pending_analyses():
                self.analysis_queue.put(job)

    def _run_analysis(self) -> None:
        while (job := self.analysis_queue.get()) is not None:
            project_id, collection_id, revision = job
            try:
                if not self.store.mark_analysis_processing(project_id, collection_id, revision):
                    continue
                started = time.monotonic()
                submissions = self.store.list_for_collection(project_id, collection_id)
                if self.analyzer is analyze_submissions:
                    def publish(result: dict[str, Any], completed: int, total: int) -> None:
                        if not self.store.save_analysis_progress(
                            project_id, collection_id, revision, result, completed, total,
                        ):
                            raise SupersededAnalysis()

                    result = self.analyzer(submissions, on_progress=publish)
                else:
                    result = self.analyzer(submissions)
                if self.store.finish_analysis(project_id, collection_id, revision, result=result):
                    print(
                        f"Analysis ready for {project_id}/{collection_id} revision {revision} "
                        f"({time.monotonic() - started:.1f}s)",
                        flush=True,
                    )
            except SupersededAnalysis:
                pass
            except Exception as exc:
                if self.store.finish_analysis(project_id, collection_id, revision, error=str(exc)):
                    print(
                        f"Analysis failed for {project_id}/{collection_id} revision {revision}: {exc}",
                        file=sys.stderr, flush=True,
                    )
            finally:
                self.analysis_queue.task_done()
        self.analysis_queue.task_done()

    def server_close(self) -> None:
        worker = getattr(self, "analysis_worker", None)
        if worker is not None:
            self.analysis_queue.put(None)
        super().server_close()
        if worker is not None and worker.is_alive():
            worker.join(timeout=2)


class CoordinatorHandler(BaseHTTPRequestHandler):
    server: CoordinatorServer

    def _is_authorized(self, project_id: str, member_id: str) -> bool:
        authorization = self.headers.get("Authorization", "")
        scheme, separator, secret = authorization.partition(" ")
        return (bool(separator) and scheme.lower() == "bearer" and bool(secret)
                and self.server.store.is_authorized(project_id, member_id, secret))

    def _send_json(self, status: HTTPStatus, payload: dict[str, Any]) -> None:
        data = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:
        parts = urlsplit(self.path)
        if parts.path == "/health":
            self._send_json(HTTPStatus.OK, {"status": "ok"})
            return
        if parts.path != "/refresh-requests":
            self._send_json(HTTPStatus.NOT_FOUND, {"error": "Unknown route"})
            return
        try:
            query = parse_qs(parts.query, strict_parsing=True)
            if (set(query) != {"project_id", "collection_id", "member_id", "after"}
                    or any(len(values) != 1 for values in query.values())):
                raise ValueError("Expected project_id, collection_id, member_id, and after")
            project_id, collection_id, member_id = (
                query[key][0] for key in ("project_id", "collection_id", "member_id")
            )
            if not all(value.strip() for value in (project_id, collection_id, member_id)):
                raise ValueError("IDs must be non-empty")
            after = int(query["after"][0])
            if after < 0:
                raise ValueError("after must be non-negative")
        except (ValueError, KeyError, IndexError):
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": "Invalid refresh request query"})
            return
        try:
            if not self._is_authorized(project_id, member_id):
                self._send_json(HTTPStatus.UNAUTHORIZED, {"error": "Invalid member secret"})
                return
            deadline = time.monotonic() + 20
            while True:
                revision = self.server.store.get_refresh_revision(project_id, collection_id)
                if revision > after or time.monotonic() >= deadline:
                    break
                time.sleep(0.25)
        except sqlite3.Error:
            self._send_json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": "Could not read refresh request"})
            return
        self._send_json(HTTPStatus.OK, {"revision": revision})

    def do_POST(self) -> None:
        if urlsplit(self.path).path != "/submissions":
            self._send_json(HTTPStatus.NOT_FOUND, {"error": "Unknown route"})
            return
        if self.headers.get_content_type() != "application/json":
            self._send_json(HTTPStatus.UNSUPPORTED_MEDIA_TYPE, {"error": "Send application/json"})
            return
        try:
            length = int(self.headers.get("Content-Length", ""))
        except ValueError:
            length = 0
        if length < 1:
            self._send_json(HTTPStatus.LENGTH_REQUIRED, {"error": "Content-Length is required"})
            return
        if length > MAX_BODY_BYTES:
            self._send_json(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, {"error": "JSON body is too large"})
            return
        try:
            payload = validate_submission(json.loads(self.rfile.read(length)))
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
            return

        try:
            authorized = self._is_authorized(payload["project_id"], payload["member_id"])
        except sqlite3.Error:
            self._send_json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": "Could not check member secret"})
            return
        if not authorized:
            self._send_json(HTTPStatus.UNAUTHORIZED, {"error": "Invalid member secret"})
            return

        try:
            refresh_header = self.headers.get("X-Refresh-Revision")
            refresh_revision = int(refresh_header) if refresh_header is not None else None
            revision = self.server.store.save(payload, refresh_revision=refresh_revision)
            if self.server.analysis_worker is not None:
                self.server.analysis_queue.put((payload["project_id"], payload["collection_id"], revision))
        except ValueError as exc:
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
            return
        except sqlite3.Error:
            self._send_json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": "Could not save submission"})
            return
        self._send_json(HTTPStatus.OK, {
            "received": True,
            "project_id": payload["project_id"],
            "collection_id": payload["collection_id"],
            "member_id": payload["member_id"],
            "event_count": len(payload["events"]),
            "analysis_revision": revision,
            "analysis_status": "pending",
        })


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the coordinator JSON receiver")
    parser.add_argument("--host", default="127.0.0.1", help="Address to listen on (default: localhost)")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--database", type=Path, default=Path("data/coordinator.sqlite3"))
    parser.add_argument("--certfile", type=Path, help="TLS certificate (required for remote access)")
    parser.add_argument("--keyfile", type=Path, help="TLS private key (required for remote access)")
    parser.add_argument("--no-analysis", action="store_true", help="Save uploads without running Ollama")
    args = parser.parse_args()
    if bool(args.certfile) != bool(args.keyfile):
        parser.error("--certfile and --keyfile must be provided together")
    if args.host not in ("127.0.0.1", "localhost") and not args.certfile:
        parser.error("remote listening requires --certfile and --keyfile")

    tls_context = None
    if args.certfile:
        tls_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        tls_context.minimum_version = ssl.TLSVersion.TLSv1_2
        tls_context.load_cert_chain(args.certfile, args.keyfile)

    with CoordinatorServer(
        (args.host, args.port), args.database,
        analyzer=None if args.no_analysis else analyze_submissions,
    ) as server:
        if tls_context:
            server.socket = tls_context.wrap_socket(server.socket, server_side=True)
        scheme = "https" if tls_context else "http"
        print(f"Receiving at {scheme}://{args.host}:{server.server_port}/submissions")
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            print("\nStopped.")


if __name__ == "__main__":
    main()
