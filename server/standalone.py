#!/usr/bin/env python3
"""
Standalone host adapter — runs the whole app from one process.

Serves the static call app and the /api/session endpoint together. Use it to
develop and test locally, and as the fallback host: this same file runs
unchanged on a VPS, so it is the escape hatch if a managed host is ever
unwanted. Nothing here is platform-specific.

    python server/standalone.py --port 8000

For a real deployment put it behind a TLS terminator (Caddy, nginx); browsers
refuse camera and microphone access on plain http from anything but localhost.
"""

import argparse
import json
import os
import sys
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from session_logic import (  # noqa: E402
    SessionError, create_session, find_pending_call, join_existing,
)
from push import public_key, save_subscription  # noqa: E402

WEB_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "web")


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=WEB_DIR, **kw)

    def _json(self, status, payload):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = self.path.rstrip("/")
        # The coach app polls this to see whether a trainee is waiting.
        if path == "/api/pending":
            try:
                return self._json(200, {"pending": find_pending_call()})
            except SessionError as e:
                return self._json(502, {"error": str(e)})
        if path == "/api/subscribe":
            return self._json(200, {"publicKey": public_key()})
        return super().do_GET()

    def do_POST(self):
        path = self.path.rstrip("/")
        try:
            # Bodies carry no personal data; role and room name are all we accept.
            length = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(length) if length else b"{}")
        except Exception:
            return self._json(400, {"error": "bad request"})

        try:
            if path == "/api/session":
                return self._json(200, create_session(
                    body.get("role") or "trainee", body.get("name") or ""))
            if path == "/api/answer":
                return self._json(200, join_existing(
                    body.get("sessionId"), "coach", body.get("name") or ""))
            if path == "/api/subscribe":
                ok = save_subscription(body.get("subscription") or body)
                return self._json(200 if ok else 503, {"stored": ok})
            return self._json(404, {"error": "not found"})
        except SessionError as e:
            self._json(502, {"error": str(e)})

    def log_message(self, fmt, *args):
        sys.stderr.write("%s %s\n" % (self.address_string(), fmt % args))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--host", default="127.0.0.1")
    args = ap.parse_args()

    if not os.environ.get("DAILY_API_KEY"):
        sys.stderr.write("warning: DAILY_API_KEY not set - calls will fail\n")

    srv = ThreadingHTTPServer((args.host, args.port), Handler)
    sys.stderr.write("itqan on http://{}:{}\n".format(args.host, args.port))
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        srv.shutdown()


if __name__ == "__main__":
    main()
