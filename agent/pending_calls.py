#!/usr/bin/env python3
"""
List calls that have been recorded but not yet turned into anything.

Run as a SessionStart hook so opening Claude Code surfaces the question
"there is a call waiting - do you want a video of it?" without Essam having to
remember to ask. He decides afterwards rather than at hang-up, because plenty
of calls are tests and the app should stay as plain as it is.

Silence is the whole design here. A hook that prints on every session start
becomes noise you stop reading, and then it fails at the one moment it matters.
So: nothing to say when nothing is pending, and nothing to say when the network
or the API key is unavailable - a session should never open with an error about
a background convenience.

    pending_calls.py                 # list what is waiting
    pending_calls.py --skip <room>   # a test call: never mention it again
"""

import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

ROOT = os.environ.get("ITQAN_ROOT", r"C:\Itqan")
SKIP_FILE = os.path.join(ROOT, "logs", "skipped.json")


def _load(path, default):
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return default


def _skipped():
    return set(_load(SKIP_FILE, []))


def skip(room):
    rooms = _skipped()
    rooms.add(room)
    os.makedirs(os.path.dirname(SKIP_FILE), exist_ok=True)
    with open(SKIP_FILE, "w", encoding="utf-8") as fh:
        json.dump(sorted(rooms), fh, indent=1)
    print("{} will not be listed again".format(room))


def pending():
    """Rooms with a finished recording pair that has not been dealt with."""
    import itqan_agent as agent
    agent._load_env_file()

    recs = agent.api("/recordings").get("data", [])
    done = agent.load_state()
    skipped = _skipped()

    rooms = {}
    for r in recs:
        if r.get("status") != "finished":
            continue
        rooms.setdefault(r.get("room_name"), []).append(r)

    out = []
    for room, pair in rooms.items():
        if room in skipped or len(pair) < 2:
            continue
        # The agent keys its own state on the recording ids, so ask it rather
        # than guessing - a call processed by the agent must not resurface.
        if "|".join(sorted(x["id"] for x in pair)) in done:
            continue
        out.append({
            "room": room,
            "start": min(float(x.get("start_ts") or 0) for x in pair),
            "seconds": max(int(x.get("duration") or 0) for x in pair),
        })
    return sorted(out, key=lambda c: c["start"])


def main():
    if len(sys.argv) > 2 and sys.argv[1] == "--skip":
        return skip(sys.argv[2])

    try:
        calls = pending()
    except (Exception, SystemExit):
        # Offline, no key, Daily down - all fine. Say nothing.
        #
        # SystemExit is named explicitly because it is not an Exception: the
        # agent calls sys.exit() when DAILY_API_KEY is missing, so catching
        # only Exception would let a moved .env file put an error at the top of
        # every session - the exact noise this is meant to avoid.
        return

    if not calls:
        return

    print("Unprocessed Itqan calls (recorded, no video made yet):")
    for c in calls:
        when = time.strftime("%a %d %b %H:%M", time.localtime(c["start"]))
        mins, secs = divmod(c["seconds"], 60)
        print("  {}  {}:{:02d}  room {}".format(when, mins, secs, c["room"]))
    print("")
    print("Ask which of these he wants a video of - some are test calls. To "
          "process one, follow the itqan-publish skill. For a test call, run "
          "agent/pending_calls.py --skip <room> so it stops being listed.")


if __name__ == "__main__":
    main()
