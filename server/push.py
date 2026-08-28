"""
Web push — telling the coach's phone that a trainee is calling.

The rest of this service is stateless by design, but a push notification has to
remember where to send itself. That is the only thing stored anywhere: one
subscription object for one person, holding no trainee data.

Storage is Upstash Redis over its REST API (no driver needed, just HTTPS). If
those variables are absent it falls back to a PUSH_SUBSCRIPTION environment
variable, so the whole feature can run with no storage service at all - useful
as an escape hatch, though the subscription must then be re-pasted whenever the
browser rotates it.

Nothing here is allowed to break a call: every failure path returns quietly.
A missed notification is an annoyance; a failed room is a lost session.
"""

import json
import os
import urllib.error
import urllib.request

SUB_KEY = "itqan:coach:subscription"


def _env(name, default=""):
    """
    Read a setting, loading the local secrets file on first miss.

    A managed host supplies these as real environment variables; on the laptop
    they live in C:\\Itqan\\.env, outside the OneDrive-synced project folder.
    """
    val = os.environ.get(name, "")
    if not val:
        try:
            from session_logic import _load_env_file
            _load_env_file()
        except Exception:
            pass
        val = os.environ.get(name, "")
    return val or default

# Contact address required by the push services; not used for anything else.
VAPID_SUBJECT_DEFAULT = "mailto:essamksa16@yahoo.com"


def _upstash(path, body=None):
    url = _env("UPSTASH_REDIS_REST_URL").rstrip("/")
    token = _env("UPSTASH_REDIS_REST_TOKEN")
    if not url or not token:
        return None
    req = urllib.request.Request(
        url + path,
        data=body.encode("utf-8") if body is not None else None,
        headers={"Authorization": "Bearer " + token},
        method="POST" if body is not None else "GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, ValueError, OSError):
        return None


def save_subscription(sub):
    """Remember the coach's push endpoint. Returns True if it was stored."""
    if not isinstance(sub, dict) or not sub.get("endpoint"):
        return False
    return _upstash("/set/" + SUB_KEY, json.dumps(sub)) is not None


def load_subscription():
    got = _upstash("/get/" + SUB_KEY)
    raw = (got or {}).get("result")
    if not raw:
        # Escape hatch when no storage service is configured.
        raw = _env("PUSH_SUBSCRIPTION")
    if not raw:
        return None
    try:
        return json.loads(raw) if isinstance(raw, str) else raw
    except ValueError:
        return None


def public_key():
    return _env("VAPID_PUBLIC_KEY")


def notify(title, body, url="/coach.html"):
    """
    Send one push. Returns True if it was accepted.

    Import is deferred so that a missing dependency degrades to "no
    notification" rather than taking the whole session endpoint down.
    """
    private = _env("VAPID_PRIVATE_KEY")
    sub = load_subscription()
    if not private or not sub:
        return False

    try:
        from pywebpush import WebPushException, webpush
    except ImportError:
        return False

    try:
        webpush(
            subscription_info=sub,
            data=json.dumps({"title": title, "body": body, "url": url}),
            vapid_private_key=private,
            vapid_claims={"sub": _env("VAPID_SUBJECT", VAPID_SUBJECT_DEFAULT)},
            timeout=8,
        )
        return True
    except WebPushException:
        # 404/410 means the browser dropped the subscription; the coach app
        # re-subscribes on next open, so there is nothing useful to do here.
        return False
    except Exception:
        return False
