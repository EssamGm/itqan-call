"""
Vercel host adapter.

Deliberately thin: all real logic lives in server/session_logic.py, which knows
nothing about Vercel. Moving to Cloudflare, Fly, Netlify or a plain VPS means
writing a sibling of this file (or just running server/standalone.py) and
changing API_BASE in web/config.js. Nothing else moves.
"""

import json
import os
import sys
from http.server import BaseHTTPRequestHandler

sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "server")
)
from session_logic import SessionError, create_session  # noqa: E402


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
            raw = self.rfile.read(length) if length else b"{}"
            body = json.loads(raw or b"{}")
            self._json(200, create_session(
                body.get("role") or "trainee", body.get("name") or ""))
        except SessionError as e:
            self._json(502, {"error": str(e)})
        except Exception:
            self._json(400, {"error": "bad request"})
