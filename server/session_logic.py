"""
Session minting — the only server-side logic in this project.

Host-agnostic on purpose. This module talks plain HTTP over the standard
library and knows nothing about Vercel, Cloudflare, Fly or any other platform.
Each host gets a thin adapter that calls create_session() and returns JSON, so
moving hosts means rewriting ~20 lines of adapter, never this file.

Privacy note: no trainee name is accepted or stored here. Participants are
labelled by role only ("coach" / "trainee"), which is all the renderer needs to
tell the two tracks apart. The trainee's real name never leaves their phone.
That keeps this service free of personal data entirely, so whoever hosts it has
nothing of consequence to hold.
"""

import json
import os
import time
import urllib.error
import urllib.request

DAILY_API = "https://api.daily.co/v1"

# A generous ceiling, not an expected length. The room self-destructs after
# this so abandoned rooms cannot linger and keep recording.
ROOM_TTL_SECONDS = 4 * 60 * 60

ROLE_COACH = "coach"
ROLE_TRAINEE = "trainee"


class SessionError(Exception):
    """Raised with a message safe to show a caller."""


def _allow_unrecorded():
    """Opt-in escape hatch for trying the call UI before billing is enabled."""
    return os.environ.get("ITQAN_ALLOW_NO_RECORDING", "").strip() in ("1", "true", "yes")


# Kept outside the OneDrive-synced project folder on purpose: the API key must
# not be uploaded to Microsoft's cloud along with the source. A managed host
# supplies the key as a real environment variable instead, and never reads this.
ENV_FILE = os.environ.get("ITQAN_ENV_FILE", r"C:\Itqan\.env")


def _load_env_file():
    """Read KEY=value lines from the local secrets file, if it exists."""
    try:
        with open(ENV_FILE, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                name, _, value = line.partition("=")
                # Real env vars win, so a host's own config is never overridden.
                os.environ.setdefault(name.strip(), value.strip().strip("\"'"))
    except OSError:
        pass


def _api_key():
    key = os.environ.get("DAILY_API_KEY", "").strip()
    if not key:
        _load_env_file()
        key = os.environ.get("DAILY_API_KEY", "").strip()
    if not key:
        raise SessionError(
            "DAILY_API_KEY is not set. Put it in " + ENV_FILE +
            " as DAILY_API_KEY=your_key, or set it as an environment variable."
        )
    return key


def _get(path):
    req = urllib.request.Request(
        DAILY_API + path,
        headers={"Authorization": "Bearer " + _api_key()},
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            body = resp.read()
            return json.loads(body) if body else {}
    except urllib.error.HTTPError as e:
        raise SessionError("Daily API error {}".format(e.code))
    except urllib.error.URLError as e:
        raise SessionError("could not reach the call service: {}".format(e.reason))


def _post(path, payload):
    req = urllib.request.Request(
        DAILY_API + path,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": "Bearer " + _api_key(),
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:300]
        raise SessionError("Daily API error {}: {}".format(e.code, detail))
    except urllib.error.URLError as e:
        raise SessionError("could not reach the call service: {}".format(e.reason))


def find_pending_call():
    """
    Find a room where a trainee is waiting, so the coach can answer it.

    Daily's presence endpoint is the source of truth, which keeps this service
    stateless: there is no "current call" to store, and therefore nothing to
    get out of sync if the process restarts.

    Returns {"sessionId", "roomUrl", "waiting"} or None.
    """
    presence = _get("/presence") or {}
    # Presence is keyed by room name; older shapes nest it under "data".
    rooms = presence.get("data", presence)
    if not isinstance(rooms, dict):
        return None

    for room_name, participants in rooms.items():
        if not isinstance(participants, list) or not participants:
            continue
        names = [(p.get("userName") or p.get("user_name") or "").lower()
                 for p in participants]
        # Only offer rooms the coach has not already joined.
        if any(ROLE_COACH in n for n in names):
            continue
        return {
            "sessionId": room_name,
            "roomUrl": "https://{}.daily.co/{}".format(_domain(), room_name),
            "waiting": len(participants),
        }
    return None


def join_existing(room_name, role=ROLE_COACH):
    """Mint a token for a room that already exists, without creating one."""
    if not room_name or not str(room_name).replace("-", "").replace("_", "").isalnum():
        raise SessionError("invalid room")

    token = _post("/meeting-tokens", {
        "properties": {
            "room_name": room_name,
            "user_name": role,
            "is_owner": role == ROLE_COACH,
            "exp": int(time.time()) + ROOM_TTL_SECONDS,
        },
    })
    return {
        "sessionId": room_name,
        "roomUrl": "https://{}.daily.co/{}".format(_domain(), room_name),
        "token": token["token"],
        "userName": role,
    }


_DOMAIN_CACHE = {}


def _domain():
    if "name" not in _DOMAIN_CACHE:
        _DOMAIN_CACHE["name"] = _get("/").get("domain_name", "")
    return _DOMAIN_CACHE["name"]


def create_session(role=ROLE_TRAINEE):
    """
    Create a 1:1 room recording raw per-participant tracks, and mint a token.

    Recording is configured server-side and auto-started by the token rather
    than triggered from the browser, so a flaky client cannot silently lose the
    recording, and nothing about it is visible during the call.
    """
    if role not in (ROLE_COACH, ROLE_TRAINEE):
        raise SessionError("unknown role")

    expiry = int(time.time()) + ROOM_TTL_SECONDS

    props = {
        # "cloud", not "raw-tracks": raw-tracks refuses to run unless the
        # domain has its own S3 bucket attached, which would mean standing up
        # an AWS account and IAM role. Daily stores cloud recordings itself, so
        # instead the coach app starts two concurrent cloud recordings, each
        # framed on one participant. That yields the same thing the bubble
        # renderer needs - one file per person - with no bucket to configure.
        "enable_recording": "cloud",
        "max_participants": 2,
        "exp": expiry,
        "eject_at_room_exp": True,
        "enable_prejoin_ui": False,
        "enable_screenshare": False,
        "enable_chat": False,
    }

    recording = True
    try:
        room = _post("/rooms", {"privacy": "private", "properties": props})
    except SessionError as e:
        # Recording needs billing enabled on the Daily account. Falling back to
        # an unrecorded room is only for trying out the call experience: a real
        # coaching session must never be silently lost, so the fallback is
        # opt-in and the caller is told recording is off.
        if "enable_recording" not in str(e) or not _allow_unrecorded():
            raise
        props.pop("enable_recording")
        room = _post("/rooms", {"privacy": "private", "properties": props})
        recording = False

    # No start_cloud_recording here: that property only applies to "cloud" and
    # "cloud-audio-only" modes, not raw-tracks. Raw-tracks must be started
    # explicitly by the client, which the coach app does on joining.
    token = _post("/meeting-tokens", {"properties": {
        "room_name": room["name"],
        "user_name": role,
        "is_owner": role == ROLE_COACH,
        "exp": expiry,
    }})

    return {
        "sessionId": room["name"],
        "roomUrl": room["url"],
        "token": token["token"],
        "userName": role,
        "expiresAt": expiry,
        "recording": recording,
    }
