#!/usr/bin/env python3
"""
Put the two voices on one clock, and write the conversation down in order.

Each speaker is recorded to their own file on their own clock, and the render
re-times their turns so the voices stop colliding. That re-timing used to
live only inside render's memory - which meant anyone deciding what to cut,
or where a chapter starts, had to reconstruct it by hand. I did, three times.

This step runs once, unattended, after transcription, and writes two files:

    alignment.json      the utterance plan render will consume, so the
                        timeline judgment saw is the timeline render builds
    conversation.tsv    every caption from both speakers, in conversation
                        order, on the aligned clock - the one file REVIEW,
                        PACKAGE and CORRECT read

Re-run it after corrections are applied: text is refreshed, timings do not
move because they come from the audio, so nothing written against the old
tsv is invalidated.

    python align.py <call-folder>
"""

import datetime
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import callfolder as cf  # noqa: E402
import bubble_render as br  # noqa: E402


def align(folder):
    meta = cf.read_meta(folder)
    paths = [cf.path(folder, cf.AUDIO, t) for t in cf.TRACKS]
    offsets = [float(meta.get("coach_offset", 0.0)), float(meta.get("trainee_offset", 0.0))]
    for p in paths:
        if not os.path.isfile(p):
            sys.exit("align: missing " + p)

    total = max(o + br.probe(p)["duration"] for o, p in zip(offsets, paths))
    plan = br.plan_alignment(paths, offsets, total)
    if not plan:
        sys.exit("align: nothing to align (no speech found?)")
    utts, new_total = plan

    cf.write_json(cf.path(folder, cf.ALIGNMENT), {
        "total": total,
        "new_total": new_total,
        "offsets": {"coach": offsets[0], "trainee": offsets[1]},
        "utterances": utts,
    })
    return utts, total, new_total, offsets


def conversation(folder, utts, total, new_total, offsets):
    """conversation.tsv from the transcripts and the plan."""
    import numpy as np
    rows = []
    sources = []
    for ti, track in enumerate(cf.TRACKS):
        tp = cf.path(folder, cf.TRANSCRIPT, track)
        if not os.path.isfile(tp):
            sys.exit("align: missing " + tp + " - run transcribe first")
        sources.append("{}={}".format(os.path.basename(tp), int(os.path.getmtime(tp))))
        old, new = br.alignment_map(utts, ti, total, new_total, np)
        for i, s in enumerate(cf.read_json(tp)):
            a = float(np.interp(s["start"] + offsets[ti], old, new))
            b = float(np.interp(s["end"] + offsets[ti], old, new))
            rows.append((a, b, track, i, s["text"].replace("\t", " ").replace("\n", " ")))
    rows.sort(key=lambda r: (r[0], r[2]))
    cf.write_tsv(
        cf.path(folder, cf.CONVERSATION),
        [("{:.2f}".format(a), "{:.2f}".format(b), t, i, x) for a, b, t, i, x in rows],
        header=["aligned_start", "aligned_end", "speaker", "source_index", "text"],
        comments=[
            "generated " + datetime.datetime.now().isoformat(timespec="seconds"),
            "sources " + " ".join(sources),
            "aligned clock: seconds on the timeline render builds; cuts.txt and "
            "package.md chapters are written on this clock",
            "source_index: position in that speaker's transcript.json - the index "
            "corrections.txt uses; coach and trainee are separate index spaces",
        ],
    )
    return len(rows)


def is_stale(folder):
    """True if the transcripts changed since conversation.tsv was written."""
    p = cf.path(folder, cf.CONVERSATION)
    if not os.path.isfile(p):
        return True
    recorded = {}
    for line in cf.read_text(p).splitlines():
        if line.startswith("# sources "):
            for part in line[len("# sources "):].split():
                name, _, mt = part.partition("=")
                recorded[name] = int(mt)
            break
    for track in cf.TRACKS:
        tp = cf.path(folder, cf.TRANSCRIPT, track)
        if os.path.isfile(tp) and recorded.get(os.path.basename(tp)) != int(os.path.getmtime(tp)):
            return True
    return False


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    folder = os.path.abspath(sys.argv[1])
    utts, total, new_total, offsets = align(folder)
    n = conversation(folder, utts, total, new_total, offsets)
    print("aligned {} utterances, {:.1f}s -> {:.1f}s; conversation.tsv has {} lines".format(
        len(utts), total, new_total, n))


if __name__ == "__main__":
    main()
