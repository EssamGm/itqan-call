#!/usr/bin/env python3
"""
Itqan laptop agent.

Watches Daily for finished recordings, downloads the pair belonging to each
call, renders the square bubble video plus a clean audio track, then deletes
the cloud copies.

Each call produces two concurrent single-participant cloud recordings - one
framed on the coach, one on the trainee - because raw-tracks would require
attaching a private S3 bucket to the Daily domain. Pairing them here gives the
renderer the same thing: one file per person.

Only outbound connections are made, so nothing needs to reach this machine:
no port forwarding, no tunnel, no static IP. Run it whenever convenient - if
the laptop was off when a call ended, the recording simply waits.

    python agent/itqan_agent.py            # process anything waiting, then exit
    python agent/itqan_agent.py --watch    # keep polling

Recordings land in C:\\Itqan\\ , deliberately outside OneDrive so trainee audio
and video are never synced to a cloud outside the Kingdom.
"""

import argparse
import collections
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request

sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "server")
)
from session_logic import _load_env_file  # noqa: E402

DAILY_API = "https://api.daily.co/v1"
ROOT = os.environ.get("ITQAN_ROOT", r"C:\Itqan")
RAW_DIR = os.path.join(ROOT, "recordings", "raw")
PUB_DIR = os.path.join(ROOT, "recordings", "published")
LOG_DIR = os.path.join(ROOT, "logs")
STATE_FILE = os.path.join(LOG_DIR, "processed.json")

RENDERER = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "render", "bubble_render.py"
)

# Must match INSTANCE_IDS in web/provider-daily.js.
INSTANCE_COACH = "5c0ac400-0000-4000-8000-000000000001"
INSTANCE_TRAINEE = "5c0ac400-0000-4000-8000-000000000002"

POLL_SECONDS = 60


def log(msg):
    line = "[{}] {}".format(time.strftime("%Y-%m-%d %H:%M:%S"), msg)
    print(line, flush=True)
    os.makedirs(LOG_DIR, exist_ok=True)
    with open(os.path.join(LOG_DIR, "agent.log"), "a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def api(path, method="GET"):
    key = os.environ.get("DAILY_API_KEY", "").strip()
    if not key:
        raise SystemExit("DAILY_API_KEY not set (expected in %s\\.env)" % ROOT)
    req = urllib.request.Request(
        DAILY_API + path, method=method, headers={"Authorization": "Bearer " + key}
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        body = resp.read()
        return json.loads(body) if body else {}


def load_state():
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as fh:
            return set(json.load(fh))
    except (OSError, ValueError):
        return set()


def save_state(done):
    os.makedirs(LOG_DIR, exist_ok=True)
    with open(STATE_FILE, "w", encoding="utf-8") as fh:
        json.dump(sorted(done), fh, indent=1)


def download(url, dest):
    with urllib.request.urlopen(url, timeout=600) as resp, open(dest, "wb") as fh:
        while True:
            chunk = resp.read(1 << 20)
            if not chunk:
                break
            fh.write(chunk)
    return os.path.getsize(dest)


def role_of(rec):
    """
    Which participant this recording was framed on.

    Daily has not settled on one field name for the instance id across API
    versions, so check the plausible ones before falling back to start order.
    """
    for key in ("instance_id", "instanceId", "recording_instance_id"):
        val = rec.get(key)
        if val == INSTANCE_COACH:
            return "coach"
        if val == INSTANCE_TRAINEE:
            return "trainee"
    return None


def assign_roles(pair):
    """Return (coach_rec, trainee_rec), guessing by start order if needed."""
    tagged = {role_of(r): r for r in pair if role_of(r)}
    if "coach" in tagged and "trainee" in tagged:
        return tagged["coach"], tagged["trainee"]
    # Fall back to the order the coach app started them in.
    ordered = sorted(pair, key=lambda r: r.get("start_ts") or 0)
    log("  note: instance id not exposed - assigning roles by start order")
    return ordered[0], ordered[1]


def process_pair(room, pair, done):
    """Download both recordings for one call, render, then delete the cloud copies."""
    coach_rec, trainee_rec = assign_roles(pair)
    key = "|".join(sorted(r["id"] for r in pair))
    log("processing room {} ({} recordings)".format(room, len(pair)))

    os.makedirs(RAW_DIR, exist_ok=True)
    os.makedirs(PUB_DIR, exist_ok=True)

    local = {}
    starts = {}
    for role, rec in (("coach", coach_rec), ("trainee", trainee_rec)):
        link = api("/recordings/{}/access-link".format(rec["id"]))
        url = link.get("download_link") or link.get("link")
        if not url:
            log("  no download link for the {} recording".format(role))
            return False
        dest = os.path.join(RAW_DIR, "{}_{}.mp4".format(rec["id"], role))
        size = download(url, dest)
        local[role] = dest
        starts[role] = float(rec.get("start_ts") or 0)
        log("  {} recording: {:.1f} MB".format(role, size / 1e6))

    # The two recordings start a moment apart; align them on the earlier one.
    base = min(starts.values())
    out_base = os.path.join(PUB_DIR, time.strftime("%Y-%m-%d_") + room)

    cmd = [
        sys.executable, RENDERER,
        "--a", local["coach"], "--b", local["trainee"],
        "--a-offset", "{:.3f}".format(starts["coach"] - base),
        "--b-offset", "{:.3f}".format(starts["trainee"] - base),
        "--out", out_base,
    ]
    log("  rendering ...")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        log("  render FAILED - raw files kept for retry\n" + (result.stderr or "")[-800:])
        return False
    log("  rendered {}.mp4 + .m4a".format(os.path.basename(out_base)))

    # Only now is it safe to remove the cloud copies: the archive exists locally.
    for rec in pair:
        try:
            api("/recordings/{}".format(rec["id"]), method="DELETE")
        except urllib.error.HTTPError as e:
            log("  WARNING could not delete cloud copy {} ({})".format(rec["id"], e.code))
    log("  deleted cloud copies")

    for path in local.values():
        try:
            os.remove(path)
        except OSError:
            pass

    done.add(key)
    save_state(done)
    return True


def sweep():
    done = load_state()
    try:
        recordings = api("/recordings").get("data", [])
    except urllib.error.HTTPError as e:
        log("could not list recordings: HTTP {}".format(e.code))
        return 0

    by_room = collections.defaultdict(list)
    for r in recordings:
        if r.get("status") == "finished":
            by_room[r.get("room_name")].append(r)

    count = 0
    for room, pair in by_room.items():
        if len(pair) < 2:
            log("room {} has only 1 recording - waiting for its pair".format(room))
            continue
        pair = sorted(pair, key=lambda r: r.get("start_ts") or 0)[:2]
        if "|".join(sorted(r["id"] for r in pair)) in done:
            continue
        try:
            if process_pair(room, pair, done):
                count += 1
        except Exception as e:  # keep going; retry on the next sweep
            log("  error on room {}: {}".format(room, e))
    return count


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--watch", action="store_true", help="keep polling")
    ap.add_argument("--interval", type=int, default=POLL_SECONDS)
    args = ap.parse_args()

    _load_env_file()
    log("agent started - archive at " + ROOT)

    if not args.watch:
        log("done ({} processed)".format(sweep()))
        return

    while True:
        try:
            sweep()
        except KeyboardInterrupt:
            log("stopped")
            return
        except Exception as e:
            log("sweep error: {}".format(e))
        time.sleep(args.interval)


if __name__ == "__main__":
    main()
