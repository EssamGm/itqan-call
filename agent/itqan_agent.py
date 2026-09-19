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
sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "render")
)
import callfolder as cf  # noqa: E402

DAILY_API = "https://api.daily.co/v1"
ROOT = os.environ.get("ITQAN_ROOT", r"C:\Itqan")
RAW_DIR = os.path.join(ROOT, "recordings", "raw")
PUB_DIR = os.path.join(ROOT, "recordings", "published")
LOG_DIR = os.path.join(ROOT, "logs")
STATE_FILE = os.path.join(LOG_DIR, "processed.json")

RENDER_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "render")
TRANSCRIBER = os.path.join(RENDER_DIR, "transcribe.py")
ALIGNER = os.path.join(RENDER_DIR, "align.py")

# Must match INSTANCE_IDS in web/provider-daily.js.
INSTANCE_COACH = "5c0ac400-0000-4000-8000-000000000001"
INSTANCE_TRAINEE = "5c0ac400-0000-4000-8000-000000000002"

POLL_SECONDS = 60


# The Windows console defaults to cp1252, which cannot encode Arabic names and
# would abort the run mid-render. Force UTF-8 and never let logging be fatal.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError):
    pass


def log(msg):
    line = "[{}] {}".format(time.strftime("%Y-%m-%d %H:%M:%S"), msg)
    try:
        print(line, flush=True)
    except UnicodeEncodeError:
        print(line.encode("ascii", "replace").decode("ascii"), flush=True)
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


def names_for_room(room):
    """
    Look up who was in this call, so their names can go in the bubbles.

    Tokens carry the role in user_id and the human name in user_name, so a
    rename never breaks role detection. Falls back to the role word if Daily
    has already aged the session out.
    """
    found = {}
    try:
        sessions = api("/meetings?room={}".format(room)).get("data", [])
    except urllib.error.HTTPError:
        return found
    for s in sessions:
        for p in s.get("participants", []):
            role = p.get("user_id") or p.get("userId") or ""
            name = p.get("user_name") or p.get("userName") or ""
            if role in ("coach", "trainee") and name and role not in found:
                found[role] = name
    return found


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
    """
    Bring one call onto the laptop and get it ready for judgment.

    Download both tracks into a folder of their own, write meta.json, run
    transcription and alignment, and stop. Rendering is deliberately NOT here:
    it waits for the corrections, the cuts and the package, which are Essam's
    to make in his own time. Everything this function does is unattended, and
    the slow part - an hour of transcription for a twenty-minute call - is
    finished before he sits down.
    """
    coach_rec, trainee_rec = assign_roles(pair)
    key = "|".join(sorted(r["id"] for r in pair))
    log("fetching room {} ({} recordings)".format(room, len(pair)))

    names = names_for_room(room)
    starts = {"coach": float(coach_rec.get("start_ts") or 0),
              "trainee": float(trainee_rec.get("start_ts") or 0)}
    base = min(starts.values())
    date = time.strftime("%Y-%m-%d", time.localtime(base))
    folder = cf.folder_for(date, names.get("trainee") or room)
    os.makedirs(folder, exist_ok=True)

    for role, rec in (("coach", coach_rec), ("trainee", trainee_rec)):
        dest = cf.path(folder, cf.AUDIO, role)
        if os.path.isfile(dest) and os.path.getsize(dest) > 0:
            log("  {} already downloaded".format(role))
            continue
        link = api("/recordings/{}/access-link".format(rec["id"]))
        url = link.get("download_link") or link.get("link")
        if not url:
            log("  no download link for the {} recording".format(role))
            return False
        size = download(url, dest)
        log("  {} recording: {:.1f} MB".format(role, size / 1e6))

    cf.write_meta(folder, {
        "date": date,
        "host": names.get("coach") or "عصام",
        "guest": names.get("trainee") or "",
        "room": room,
        "coach_id": coach_rec["id"],
        "trainee_id": trainee_rec["id"],
        "coach_offset": round(starts["coach"] - base, 3),
        "trainee_offset": round(starts["trainee"] - base, 3),
        "episode": None,
    })
    log("  folder: {}".format(folder))

    # The archive exists locally; the cloud copy is what matters for PDPL and
    # it can go. Transcription failing later loses nothing.
    for rec in pair:
        try:
            api("/recordings/{}".format(rec["id"]), method="DELETE")
        except urllib.error.HTTPError as e:
            log("  WARNING could not delete cloud copy {} ({})".format(rec["id"], e.code))
    log("  deleted cloud copies")
    done.add(key)
    save_state(done)

    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    log("  transcribing (this is the slow part) ...")
    r = subprocess.run([sys.executable, TRANSCRIBER,
                        cf.path(folder, cf.AUDIO, "coach"), cf.path(folder, cf.AUDIO, "trainee")],
                       capture_output=True, text=True, encoding="utf-8", errors="replace", env=env)
    if r.returncode != 0:
        log("  transcription FAILED - run transcribe.py on the folder by hand\n"
            + (r.stderr or "")[-600:])
        return True
    # transcribe.py caches beside the audio under its own name; the folder's
    # canonical name is what every other stage reads.
    for role in cf.TRACKS:
        src = os.path.join(folder, "{}.v{}.transcript.json".format(role, _cache_version()))
        if os.path.isfile(src):
            cf.write_json(cf.path(folder, cf.TRANSCRIPT, role), cf.read_json(src))
            os.remove(src)
    r = subprocess.run([sys.executable, ALIGNER, folder],
                       capture_output=True, text=True, encoding="utf-8", errors="replace", env=env)
    if r.returncode != 0:
        log("  alignment FAILED\n" + (r.stderr or "")[-600:])
        return True
    log("  ready for judgment: " + (r.stdout or "").strip())
    return True


def _cache_version():
    sys.path.insert(0, RENDER_DIR)
    import transcribe
    return transcribe.CACHE_VERSION


def _has_folder(pair):
    ids = {r["id"] for r in pair}
    for f in cf.list_calls():
        m = cf.read_meta(f)
        if {m.get("coach_id"), m.get("trainee_id")} & ids:
            return True
    return False


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
        if "|".join(sorted(r["id"] for r in pair)) in done or _has_folder(pair):
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
    ap.add_argument("--purge-raw", action="store_true",
                    help="delete kept per-person source files, then exit")
    args = ap.parse_args()

    if args.purge_raw:
        freed = 0
        for name in os.listdir(RAW_DIR) if os.path.isdir(RAW_DIR) else []:
            p = os.path.join(RAW_DIR, name)
            freed += os.path.getsize(p)
            os.remove(p)
        log("purged raw sources, freed {:.1f} MB".format(freed / 1e6))
        return

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
