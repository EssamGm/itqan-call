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

# large-v3, not small. On this project's own Saudi-dialect recording, small
# returned "فيه معادل فيه دورات" and "دصر" where large-v3 returned "في معاهد في
# دورات" and "بس صح" - the difference between nonsense and usable text. It runs
# at about 0.6x real time on this CPU instead of 3x, which costs an hour on a
# long call and is worth it when the render happens overnight anyway.
MODEL_SIZE = os.environ.get("ITQAN_WHISPER_MODEL", "large-v3")

# How far ahead of the voice a caption appears.
#
# Whisper's alignment sits a little behind the sound, and reading along with a
# voice makes that obvious: a late caption reads as a fault, a slightly early
# one does not register at all. Measured against this project's own recordings,
# word-level starts turned out identical to segment starts to the millisecond -
# so the lag is in the model's alignment, not in which field is read, and a
# lead offset is the only thing that actually addresses it.
LEAD_SECONDS = 0.32

# A caption has to be readable at a glance, which bounds how much can sit on
# screen at once and for how long. Whisper will happily return a single segment
# spanning three minutes - on this project's own recordings it returned one of
# 173 seconds - and that is a wall of text, not a caption.
MAX_CAPTION_SECONDS = 4.5
MAX_CAPTION_WORDS = 9

# Version tag for the cache. Bumping it invalidates transcripts made by an
# older version of this file, so a timing change actually takes effect instead
# of being served stale from disk.
#
# Bumping this discards hand corrections along with the machine output, since
# both live in the same file. `transcript_tool.py reapply` exists to carry them
# across: it matches on text rather than line number, so corrections survive a
# re-transcription that adds or drops lines.
CACHE_VERSION = 5

_MODEL = None


def _model():
    global _MODEL
    if _MODEL is None:
        from faster_whisper import WhisperModel
        # int8 on CPU: roughly five times faster than real time on this
        # machine, which has no usable GPU.
        _MODEL = WhisperModel(MODEL_SIZE, device="cpu", compute_type="int8")
    return _MODEL


def _is_hallucination(seg, text):
    """
    Reject text invented out of near-silence.

    Each track is silent for however long the other person is talking, and that
    is exactly where a transcriber starts hearing things - typically a burst of
    repeated syllables over a fraction of a second. Real speech is neither that
    short nor that repetitive.
    """
    duration = float(seg.end) - float(seg.start)
    if duration < 0.4:
        return True

    # Deliberately not filtering on no_speech_prob. It is reported per decode
    # window rather than per segment, so a whole run of clear speech can carry
    # the same high value - filtering on it threw away thirteen good lines out
    # of thirty-one on a real call.
    tokens = [t for t in text.replace(",", " ").split() if t]
    if len(tokens) >= 4:
        distinct = len(set(t.lower().strip(".,!?") for t in tokens))
        # "ei ei ai ai ai ai" and friends: many words, almost no vocabulary.
        if distinct <= max(2, len(tokens) // 4):
            return True
    return False


def _is_filler(text):
    """
    Reject a caption that is nothing but backchannel.

    One person listening while the other explains produces long runs of "ايه,
    ايه, ايه" - real speech, correctly transcribed, and worth nothing on
    screen. Putting it up as a caption reads as a transcription failure.
    """
    tokens = [t.strip(".,!?،؟").lower() for t in text.split()]
    tokens = [t for t in tokens if t]
    if not tokens:
        return True
    distinct = set(tokens)
    if len(tokens) >= 3 and len(distinct) <= 2:
        return True
    # A single grunt on its own carries nothing either. "ايوه" and its spellings
    # belong here for the same reason "نعم" does - on a real call the trainee
    # produced four consecutive captions reading only "ايو" while the coach
    # explained, which looks like the transcriber broke rather than like
    # someone listening.
    FILLER = {"ايه", "اه", "آه", "نعم", "طيب", "اها", "أها",
              "ايو", "ايوه", "أيوه", "ايوا", "أيوا", "هم", "همم",
              "mm", "mhm", "uh", "um", "hmm", "huh", "ah", "oh",
              "yeah", "yep", "ok", "okay", "right"}
    return len(tokens) <= 2 and distinct <= FILLER


def _split_into_captions(words):
    """
    Break one segment into caption-sized pieces on word boundaries.

    Timing comes from the words themselves, so each piece appears with the
    words it contains rather than inheriting the whole segment's start.
    """
    out = []
    chunk = []

    def flush():
        if not chunk:
            return
        text = "".join(w.word for w in chunk).strip()
        if not text:
            chunk.clear()
            return
        start = max(0.0, float(chunk[0].start) - LEAD_SECONDS)
        end = float(chunk[-1].end)
        out.append({"start": start, "end": max(end, start + 0.5), "text": text})
        chunk.clear()

    for w in words:
        if chunk:
            spanned = float(w.end) - float(chunk[0].start)
            # Break on length, or on a real pause, which is usually a clause
            # boundary and so the most natural place to cut.
            gap = float(w.start) - float(chunk[-1].end)
            if (spanned > MAX_CAPTION_SECONDS
                    or len(chunk) >= MAX_CAPTION_WORDS
                    or gap > 0.7):
                flush()
        chunk.append(w)
    flush()
    return out


def transcribe(path, language=None, cache=True):
    """
    Return [{start, end, text}] for one audio file.

    Timings are relative to the start of that file, so any join offset must be
    added by the caller.
    """
    cache_path = "{}.v{}.transcript.json".format(
        os.path.splitext(path)[0], CACHE_VERSION)
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
        vad_parameters={"min_silence_duration_ms": 700, "speech_pad_ms": 120},
        # Needed for honest timing: a segment's own start marks where the model
        # became confident, not where the sound began, and it runs late enough
        # to be visible when you are reading along with the voice.
        word_timestamps=True,
    )

    out = []
    for s in segments:
        text = (s.text or "").strip()
        if not text or _is_hallucination(s, text):
            continue

        # Prefer the first word's onset over the segment's own start.
        words = list(getattr(s, "words", None) or [])
        start = float(words[0].start) if words else float(s.start)
        end = float(words[-1].end) if words else float(s.end)

        if words:
            out.extend(c for c in _split_into_captions(words)
                       if not _is_filler(c["text"]))
        else:
            # Cue a little early: a caption that lands late reads as a mistake,
            # while one a fraction early reads as natural, which is why
            # broadcast subtitling leads the audio rather than chasing it.
            start = max(0.0, start - LEAD_SECONDS)
            out.append({"start": start, "end": max(end, start + 0.4),
                        "text": text})

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
