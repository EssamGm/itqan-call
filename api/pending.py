"""Vercel host adapter — GET /api/pending. See api/session.py for the pattern."""

import json
import os
import sys
from http.server import BaseHTTPRequestHandler

sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "server")
)
from session_logic import SessionError, find_pending_call  # noqa: E402


class handler(BaseHTTPRequestHandler):
    def _json(self, status, payload):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        try:
            self._json(200, {"pending": find_pending_call()})
        except SessionError as e:
            self._json(502, {"error": str(e)})
        except Exception:
            self._json(500, {"error": "server error"})
