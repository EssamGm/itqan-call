#!/usr/bin/env python3
"""
Read and write caption transcripts safely.

The correction step rewrites words, never timings. Editing the JSON freehand
makes it far too easy to drop a line, shift a timestamp, or break the ordering
- and the failure is silent: the render succeeds and the captions drift. This
tool makes the text easy to work with and refuses to write back anything whose
structure changed.

    transcript_tool.py dump <transcript.json>
    transcript_tool.py apply <transcript.json> <corrected.txt>
    transcript_tool.py check <transcript.json>
"""

import json
import os
import sys


def load(path):
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def dump(path):
    """Print one numbered line per caption, for correction."""
    segs = load(path)
    for i, s in enumerate(segs):
        print("{}\t{}".format(i, s["text"].replace("\t", " ").replace("\n", " ")))


def apply(path, corrected_path):
    """
    Write corrected text back, keeping every timing exactly as it was.

    The corrected file is `index<TAB>text` per line - the same shape `dump`
    produces. Lines may be edited or left alone; they may not be added,
    removed, or reordered, because the timings belong to the originals.
    """
    segs = load(path)
    updates = {}
    with open(corrected_path, "r", encoding="utf-8") as fh:
        for raw in fh:
            raw = raw.rstrip("\n")
            if not raw.strip():
                continue
            if "\t" not in raw:
                sys.exit("error: expected 'index<TAB>text', got: " + raw[:60])
            idx, text = raw.split("\t", 1)
            try:
                updates[int(idx)] = text.strip()
            except ValueError:
                sys.exit("error: bad index: " + idx[:20])

    missing = set(range(len(segs))) - set(updates)
    extra = set(updates) - set(range(len(segs)))
    if missing or extra:
        sys.exit("error: corrected file must cover exactly lines 0..{}; "
                 "missing {}, unexpected {}".format(
                     len(segs) - 1, sorted(missing)[:5], sorted(extra)[:5]))

    changed = 0
    for i, s in enumerate(segs):
        new = updates[i]
        if new and new != s["text"]:
            s["text"] = new
            changed += 1

    backup = path + ".before-correction"
    if not os.path.exists(backup):
        os.replace(path, backup)
    else:
        os.remove(path)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(segs, fh, ensure_ascii=False, indent=1)

    print("corrected {} of {} lines".format(changed, len(segs)))
    print("original kept at " + os.path.basename(backup))


def check(path):
    """Sanity-check a transcript before it is rendered."""
    segs = load(path)
    problems = []
    for i, s in enumerate(segs):
        if s["end"] <= s["start"]:
            problems.append("line {}: end before start".format(i))
        if i and s["start"] < segs[i - 1]["start"]:
            problems.append("line {}: out of order".format(i))
        if not s["text"].strip():
            problems.append("line {}: empty".format(i))
        if s["end"] - s["start"] > 8:
            problems.append("line {}: {:.0f}s is too long to read".format(
                i, s["end"] - s["start"]))
    print("{} captions, {:.0f}s covered".format(
        len(segs), segs[-1]["end"] - segs[0]["start"] if segs else 0))
    for p in problems[:12]:
        print("  " + p)
    print("  no problems" if not problems else "  {} problems".format(len(problems)))
    return 1 if problems else 0


if __name__ == "__main__":
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    cmd, target = sys.argv[1], sys.argv[2]
    if cmd == "dump":
        dump(target)
    elif cmd == "apply":
        if len(sys.argv) < 4:
            sys.exit("usage: transcript_tool.py apply <transcript.json> <corrected.txt>")
        apply(target, sys.argv[3])
    elif cmd == "check":
        sys.exit(check(target))
    else:
        sys.exit(__doc__)
