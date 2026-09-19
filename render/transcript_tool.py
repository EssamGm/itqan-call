#!/usr/bin/env python3
"""
Read and write caption transcripts safely.

The correction step rewrites words, never timings. Editing the JSON freehand
makes it far too easy to drop a line, shift a timestamp, or break the ordering
- and the failure is silent: the render succeeds and the captions drift. This
tool makes the text easy to work with and refuses to write back anything whose
structure changed.

    transcript_tool.py dump <transcript.json>
    transcript_tool.py apply <transcript.json> <corrections.txt>
    transcript_tool.py reapply <new.json> <old-corrected.json>
    transcript_tool.py check <transcript.json>

corrections.txt carries CHANGED LINES ONLY - `index<TAB>corrected text`, one
per line. Indices not listed pass through untouched, which makes deleting or
reordering a caption impossible by construction rather than by instruction,
and makes the file a readable diff of what was actually changed. A text of
exactly `-` blanks the caption: the timing stays, nothing is shown. That is
for garbage - hallucinated text, dropout artefacts - never for silencing
something a person actually said; that decision belongs to REVIEW.
"""

import io
import json
import os
import sys


def load(path):
    with io.open(path, "r", encoding="utf-8-sig") as fh:
        return json.load(fh)


def save(path, segs):
    """UTF-8, no BOM, LF - the convention every file in a call folder follows."""
    with io.open(path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(segs, fh, ensure_ascii=False, indent=1)
        fh.write("\n")


def dump(path):
    """Print one numbered line per caption, for correction. LF, even on Windows."""
    try:
        sys.stdout.reconfigure(newline="\n", encoding="utf-8")
    except AttributeError:
        pass
    segs = load(path)
    for i, s in enumerate(segs):
        print("{}\t{}".format(i, s["text"].replace("\t", " ").replace("\n", " ")))


def apply(path, corrected_path):
    """
    Write corrected text back, keeping every timing exactly as it was.

    Only the lines listed are touched. An index outside the transcript is an
    error rather than ignored, because it almost always means the file was
    written against a different transcript.
    """
    segs = load(path)
    updates = {}
    for raw in io.open(corrected_path, "r", encoding="utf-8-sig").read().splitlines():
        if not raw.strip() or raw.startswith("#"):
            continue
        if "	" not in raw:
            sys.exit("error: expected 'index<TAB>text', got: " + raw[:60])
        idx, text = raw.split("	", 1)
        try:
            i = int(idx.strip())
        except ValueError:
            sys.exit("error: bad index: " + idx[:20])
        if not 0 <= i < len(segs):
            sys.exit("error: index {} is outside this transcript (0..{})".format(
                i, len(segs) - 1))
        updates[i] = text.strip()

    changed = blanked = 0
    for i, new in updates.items():
        s = segs[i]
        if new == "-":
            if s["text"] != "":
                s["text"] = ""
                blanked += 1
        elif new and new != s["text"]:
            s["text"] = new
            changed += 1

    backup = path + ".before-correction"
    if not os.path.exists(backup):
        os.replace(path, backup)
    else:
        os.remove(path)
    save(path, segs)

    print("corrected {} of {} lines{}".format(
        changed, len(segs), ", blanked {}".format(blanked) if blanked else ""))
    print("original kept at " + os.path.basename(backup))


def reapply(new_path, old_path):
    """
    Carry corrections from an earlier transcript onto a freshly made one.

    Re-transcribing throws away hand corrections, because the machine output
    and the corrections live in the same file. Changing the model, the caption
    length, or the filler filter all force that - and redoing the same
    corrections by hand each time is exactly the sort of work that stops
    getting done.

    The corrections are recovered by diffing the old transcript against its own
    `.before-correction` backup, then matched onto the new one by text rather
    than by line number, because a re-transcription rarely produces the same
    number of lines in the same order. Anything whose original text no longer
    appears is reported instead of being forced somewhere it does not belong.
    """
    backup_path = old_path + ".before-correction"
    if not os.path.exists(backup_path):
        sys.exit("error: no {} - nothing to recover corrections from".format(
            os.path.basename(backup_path)))

    old, before = load(old_path), load(backup_path)
    if len(old) != len(before):
        sys.exit("error: {} and its backup disagree on length ({} vs {})".format(
            os.path.basename(old_path), len(old), len(before)))

    fixes = {b["text"]: o["text"]
             for o, b in zip(old, before) if o["text"] != b["text"]}
    if not fixes:
        print("no corrections in " + os.path.basename(old_path))
        return 0

    segs = load(new_path)
    applied, used = 0, set()
    for s in segs:
        if s["text"] in fixes:
            used.add(s["text"])
            s["text"] = fixes[s["text"]]
            applied += 1

    backup = new_path + ".before-correction"
    if not os.path.exists(backup):
        os.replace(new_path, backup)
    else:
        os.remove(new_path)
    save(new_path, segs)

    print("carried over {} of {} corrections".format(applied, len(fixes)))
    stranded = [t for t in fixes if t not in used]
    for t in stranded[:8]:
        print("  no longer present: " + t[:60])
    if stranded:
        print("  {} correction(s) need redoing by hand".format(len(stranded)))
    return 0


def check(path):
    """Sanity-check a transcript before it is rendered."""
    segs = load(path)
    problems = []
    for i, s in enumerate(segs):
        if s["end"] <= s["start"]:
            problems.append("line {}: end before start".format(i))
        if i and s["start"] < segs[i - 1]["start"]:
            problems.append("line {}: out of order".format(i))
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
    elif cmd == "reapply":
        if len(sys.argv) < 4:
            sys.exit("usage: transcript_tool.py reapply <new.json> <old-corrected.json>")
        sys.exit(reapply(target, sys.argv[3]))
    elif cmd == "check":
        sys.exit(check(target))
    else:
        sys.exit(__doc__)
