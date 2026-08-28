"""Vercel host adapter — POST /api/answer. See api/session.py for the pattern."""

import json
import os
import sys
from http.server import BaseHTTPRequestHandler

sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "server")
)
from session_logic import SessionError, join_existing  # noqa: E402


class handler(BaseHTTPRequestHandler):
    def _json(self, status, payload):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        try:
            length = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(length) if length else b"{}")
            self._json(200, join_existing(body.get("sessionId"), "coach"))
        except SessionError as e:
            self._json(502, {"error": str(e)})
        except Exception:
            self._json(400, {"error": "bad request"})
