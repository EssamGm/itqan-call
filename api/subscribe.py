"""
Vercel host adapter — POST /api/subscribe, GET for the public key.

The coach app posts its push subscription here once, and reads the VAPID public
key it needs in order to create one.
"""

import json
import os
import sys
from http.server import BaseHTTPRequestHandler

sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "server")
)
from push import public_key, save_subscription  # noqa: E402


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
        self._json(200, {"publicKey": public_key()})

    def do_POST(self):
        try:
            length = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(length) if length else b"{}")
            ok = save_subscription(body.get("subscription") or body)
            self._json(200 if ok else 503,
                       {"stored": ok,
                        "error": None if ok else "no storage configured"})
        except Exception:
            self._json(400, {"error": "bad request"})
