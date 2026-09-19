# The pipeline, stage by stage

Every stage reads and writes plain files in one folder per call:

    C:\Itqan\calls\<YYYY-MM-DD>_<guest>\

No stage calls another. Each looks at what is in the folder, does its job,
writes its result. That is the whole coordination mechanism, and it is what
lets any task be picked up alone, in any order its inputs allow, from any
tool that can read and write a text file.

All commands are run from the repo root, `itqan-call/`. Prefix Python with
`PYTHONIOENCODING=utf-8` in Git Bash, or the console will choke on Arabic.

---

## Machine stages — unattended

### 0. See what is waiting

Runs by itself when Claude Code opens (a `SessionStart` hook). By hand:

```bash
python agent/pending_calls.py
```

Lists calls still in Daily's cloud that have no folder yet. Says nothing
when there are none, and never errors. For a test call not worth fetching:

```bash
python agent/pending_calls.py --skip <room-id>
```

### 1. Fetch, transcribe, align

```bash
python agent/itqan_agent.py
```

For every finished pair of recordings in the cloud, in one unattended run:

- **fetch** — downloads both tracks to `coach.m4a` and `trainee.m4a`, writes
  `meta.json`, deletes the cloud copies (the archive now exists locally; that
  is what PDPL cares about). Roles are assigned by start order — a heuristic —
  so CORRECT confirms them from content.
- **transcribe** — `faster-whisper large-v3`, int8, CPU, `beam_size=5`,
  `vad_filter=True`, `word_timestamps=True`. Writes `coach.transcript.json`
  and `trainee.transcript.json`: `[{start, end, text}]`, index = array
  position, per-speaker original clock. Arabic punctuation applied. About
  **0.6× real time**: an hour for a 17-minute call. This is why it starts
  the moment the call ends.
- **align** — re-times the turns so the two voices stop colliding, writes
  `alignment.json` (the plan render will consume) and `conversation.tsv`
  (every caption from both speakers, in conversation order, on the aligned
  clock). Seconds.

Either half can be re-run alone:

```bash
python render/transcribe.py C:/Itqan/calls/<folder>/coach.m4a C:/Itqan/calls/<folder>/trainee.m4a
python render/align.py C:/Itqan/calls/<folder>
```

`meta.json` fields: `date`, `host`, `guest`, `room`, `coach_id`,
`trainee_id`, `coach_offset`, `trainee_offset`, `episode` (null until promote).

`conversation.tsv` columns: `aligned_start`, `aligned_end`, `speaker`
(`coach`/`trainee`), `source_index` (position in that speaker's transcript —
the index corrections use; the two speakers are separate index spaces),
`text`. Header lines starting `#` carry the generation time and the source
mtimes, so a skill can detect a stale merge.

---

## Judgment stages — a person, or a skill, in any order

These need only the folder and `skills/glossary.md`. CORRECT has no
precondition beyond the transcripts. REVIEW and PACKAGE work on the raw
transcript and read better on the corrected one.

### CORRECT → `coach.corrections.txt`, `trainee.corrections.txt`

Read `conversation.tsv` (context is where the corrections come from — a
garbled line is often only decodable from the question before it). Write
**changed lines only**, `index<TAB>corrected text`, per speaker, keyed by
`source_index`. Never add, remove or reorder. Never normalise dialect. `-`
blanks a caption (garbage only). Then apply and refresh the merged view:

```bash
python render/transcript_tool.py apply C:/Itqan/calls/<folder>/coach.transcript.json   C:/Itqan/calls/<folder>/coach.corrections.txt
python render/transcript_tool.py apply C:/Itqan/calls/<folder>/trainee.transcript.json C:/Itqan/calls/<folder>/trainee.corrections.txt
python render/align.py C:/Itqan/calls/<folder>
```

`apply` keeps a `.before-correction` copy and refuses an index outside the
transcript. Every new error pattern is appended to `skills/glossary.md`.

### REVIEW → `cuts.txt`

`start<TAB>end<TAB>status<TAB>reason`, aligned seconds (the clock in
`conversation.tsv`). `cut` applies; `ask` blocks the render until Essam
changes it; `keep` records a decision. Reason starts with a category token
(`mic:`, `silence:`, `family:`, `money:` …). **Anything about the trainee's
family, money or health is `ask`, never `cut`.** Never cut English mistakes,
hesitation, accent or thinking pauses — that is the programme. Dead air is
not a category: alignment already caps pauses at 2 s.

### PACKAGE → `package.md`

YAML frontmatter, then the description as the body:

```
---
episode: 1
title: "…"
thumb_line1: "…"
thumb_line2: "…"
chapters:
  - "0:00 …"
  - "1:44 …"
---
description text
```

Chapters on the **aligned** clock, written for the listener, first at 0:00,
one per 90–120 s, never fewer than three. `episode` is copied from
`meta.json`; if none is assigned yet, write `episode: TODO` and say so.

---

## Promote — Essam's decision

```bash
python agent/promote.py <folder>               # next number, status draft
python agent/promote.py <folder> --published   # after it goes out
python agent/promote.py <folder> --test        # a test; no number, never listed
python agent/promote.py --list
```

Writes `C:\Itqan\episodes.tsv` and stamps `episode` into `meta.json`. This is
the only place a number is ever assigned.

---

## Machine stages — unattended, after judgment

### Render → `final.mp4`, `final.m4a`, `chapters.txt`

```bash
python render/bubble_render.py --call C:/Itqan/calls/<folder>
```

Reads everything above. **Refuses, before spending a render, if `cuts.txt`
has any `ask` row**, and prints which. Then, in one encode: applies the
alignment plan (never recomputed), removes the `cut` spans from both tracks
identically, moves captions through the same map, tone-matches the voices,
draws the bubbles and the speaking bloom, overlays the captions and the
`بودكاست إتقان` lockup, masters video to −14 LUFS and podcast audio to −16
LUFS mono with the limiter holding −2.0 dBFS before the encoder, and fades
in 0.4 s / out 0.6 s. About **real time**: a 17-minute call takes about
17 minutes.

Chapters from `package.md` are mapped to the final timeline with these rules,
each move printed: a chapter that starts inside a cut moves to the cut's end;
one whose section mostly vanished is dropped and the previous runs on; the
first is clamped to 0:00; two closer than 10 s → the later is dropped
(YouTube rejects the whole list otherwise). Result: `chapters.txt`, ready to
paste into the description.

Verify before sending: `ffmpeg -i final.m4a -af ebur128=peak=true -f null -`
should show about −16 LUFS and a peak under −1 dBFS; extract a frame and look
at it. Flags: `--no-align`, `--no-match`, `--no-pulse`, `--no-label`,
`--no-cleanup`, `--external-audio`.

### Thumbnail → `thumb.png`

```bash
python render/thumbnail.py --call C:/Itqan/calls/<folder>
```

1280×720. Guest from `meta.json`; the two headline lines and the episode
badge from `package.md` / `meta.json`. Layout: your photo (gold ring) in
front, the guest's name circle (blue ring) behind, overlapping the way
YouTube shows two channels; the episode number where they meet; `المدرب`
with an arrow from the photo; the headline with an arrow from the guest's
circle; `بودكاست إتقان` with an arrow down to the pitch, set as the Snapchat
ad sets it. Any line can be overridden on the command line.

---

## Where old calls are

Calls from before the folder layout live as loose files in
`C:\Itqan\recordings\raw\` and renders in `C:\Itqan\final\`. They can be
re-rendered with the loose flags:

```bash
python render/bubble_render.py --a <coach.m4a> --b <trainee.m4a> --a-name عصام --b-name <guest> --b-offset <s> --captions --out <path-without-extension>
```

The `2026-09-12_أبو_غازي` folder was built from those files by hand as the
first folder-layout call.
