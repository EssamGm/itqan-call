#!/usr/bin/env python3
"""
Transcribe each speaker's track, locally.

Runs faster-whisper on the CPU - no API, no key, no per-minute cost, and no
call audio leaving the machine, which matters when the recording is personal
data under PDPL.

Because each participant is recorded to their own file, who said what is known
exactly rather than inferred. Speaker attribution is normally the hardest part
of captioning a conversation; here it is free.

Results are cached beside the audio, so re-rendering a call - trying a
different look, a different audio variant - never re-transcribes it.
"""

import json
import os
import sys

MODEL_SIZE = os.environ.get("ITQAN_WHISPER_MODEL", "small")

_MODEL = None


def _model():
    global _MODEL
    if _MODEL is None:
        from faster_whisper import WhisperModel
        # int8 on CPU: roughly five times faster than real time on this
        # machine, which has no usable GPU.
        _MODEL = WhisperModel(MODEL_SIZE, device="cpu", compute_type="int8")
    return _MODEL


def transcribe(path, language=None, cache=True):
    """
    Return [{start, end, text}] for one audio file.

    Timings are relative to the start of that file, so any join offset must be
    added by the caller.
    """
    cache_path = os.path.splitext(path)[0] + ".transcript.json"
    if cache and os.path.isfile(cache_path):
        try:
            with open(cache_path, "r", encoding="utf-8") as fh:
                return json.load(fh)
        except (OSError, ValueError):
            pass

    segments, _info = _model().transcribe(
        path,
        beam_size=5,
        language=language,
        # Skip silence rather than hallucinating words into it - these tracks
        # are silent for however long the other person is talking, and that is
        # exactly where a transcriber invents text.
        vad_filter=True,
        vad_parameters={"min_silence_duration_ms": 700},
    )

    out = []
    for s in segments:
        text = (s.text or "").strip()
        if text:
            out.append({"start": float(s.start), "end": float(s.end), "text": text})

    if cache:
        try:
            with open(cache_path, "w", encoding="utf-8") as fh:
                json.dump(out, fh, ensure_ascii=False, indent=1)
        except OSError:
            pass
    return out


def merge(tracks, offsets, roles):
    """
    Interleave both speakers' segments into one chronological caption list.

    Overlaps are left alone rather than resolved: people talk over each other,
    and the later line simply replaces the earlier one on screen, which is what
    a viewer expects.
    """
    merged = []
    for segs, offset, role in zip(tracks, offsets, roles):
        for s in segs:
            merged.append({
                "start": s["start"] + offset,
                "end": s["end"] + offset,
                "text": s["text"],
                "role": role,
            })
    merged.sort(key=lambda s: s["start"])

    # Trim any segment that runs into the next one starting.
    for i in range(len(merged) - 1):
        if merged[i]["end"] > merged[i + 1]["start"]:
            merged[i]["end"] = merged[i + 1]["start"]
    return [s for s in merged if s["end"] - s["start"] > 0.15]


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit("usage: transcribe.py <audio> [audio2]")
    for p in sys.argv[1:]:
        print("=== " + os.path.basename(p) + " ===")
        for s in transcribe(p):
            print("  [%6.2f -> %6.2f] %s" % (s["start"], s["end"], s["text"]))
