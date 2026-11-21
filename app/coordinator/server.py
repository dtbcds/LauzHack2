"""HTTP(S) receiver for Calendar event submissions."""

from __future__ import annotations

import argparse
import json
import sqlite3
import ssl
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from app.coordinator.storage import SubmissionStore

MAX_BODY_BYTES = 2_000_000
SUBMISSION_FIELDS = {"project_id", "collection_id", "member_id", "events"}
EVENT_FIELDS = {
    "id", "member_id", "calendar_id", "summary", "description",
    "start", "end", "organizer", "attendees",
}


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

    def __init__(self, address: tuple[str, int], database_path: str | Path = "data/coordinator.sqlite3"):
        self.store = SubmissionStore(database_path)
        super().__init__(address, CoordinatorHandler)


class CoordinatorHandler(BaseHTTPRequestHandler):
    server: CoordinatorServer

    def _send_json(self, status: HTTPStatus, payload: dict[str, Any]) -> None:
        data = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:
        if urlsplit(self.path).path == "/health":
            self._send_json(HTTPStatus.OK, {"status": "ok"})
        else:
            self._send_json(HTTPStatus.NOT_FOUND, {"error": "Unknown route"})

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

        authorization = self.headers.get("Authorization", "")
        scheme, separator, secret = authorization.partition(" ")
        try:
            authorized = (bool(separator) and scheme.lower() == "bearer" and bool(secret)
                          and self.server.store.is_authorized(
                              payload["project_id"], payload["member_id"], secret
                          ))
        except sqlite3.Error:
            self._send_json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": "Could not check member secret"})
            return
        if not authorized:
            self._send_json(HTTPStatus.UNAUTHORIZED, {"error": "Invalid member secret"})
            return

        try:
            self.server.store.save(payload)
        except sqlite3.Error:
            self._send_json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": "Could not save submission"})
            return
        self._send_json(HTTPStatus.OK, {
            "received": True,
            "project_id": payload["project_id"],
            "collection_id": payload["collection_id"],
            "member_id": payload["member_id"],
            "event_count": len(payload["events"]),
        })


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the coordinator JSON receiver")
    parser.add_argument("--host", default="127.0.0.1", help="Address to listen on (default: localhost)")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--database", type=Path, default=Path("data/coordinator.sqlite3"))
    parser.add_argument("--certfile", type=Path, help="TLS certificate (required for remote access)")
    parser.add_argument("--keyfile", type=Path, help="TLS private key (required for remote access)")
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

    with CoordinatorServer((args.host, args.port), args.database) as server:
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
