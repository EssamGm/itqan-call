# إتقان call recorder and podcast pipeline

A web app for recording 1:1 English-coaching calls, and a pipeline that turns
each call into a square podcast-style video with named speaker bubbles,
Arabic captions, and a YouTube thumbnail.

The call is deliberately ordinary — nothing on screen during it says it will
become content. Everything else happens afterwards, one folder per call, one
file per decision, so no step waits on another that does not need it.

## The shape of it

    C:\Itqan\calls\<YYYY-MM-DD>_<guest>\
      coach.m4a  trainee.m4a  meta.json              fetch      (unattended)
      coach.transcript.json  trainee.transcript.json transcribe (unattended, ~1 h)
      alignment.json  conversation.tsv               align      (unattended, seconds)
      coach.corrections.txt  trainee.corrections.txt CORRECT    (judgment)
      cuts.txt                                       REVIEW     (judgment)
      package.md                                     PACKAGE    (judgment)
      final.mp4  final.m4a  chapters.txt             render     (unattended, ~real time)
      thumb.png                                      thumbnail  (unattended)

The three judgment tasks read `conversation.tsv` — the whole dialogue in
order, on one clock — and can be done in any order, on any day, in Claude
Code or Cowork or by hand. The machine stages start the moment a call ends
and are finished before anyone sits down.

## Start here

- **`docs/PIPELINE.md`** — every stage, exact commands, file formats, runtimes
- **`docs/DECISIONS.md`** — what was tried and rejected, and why
- **`docs/ENVIRONMENT.md`** — tools, versions, where data lives and why
- **`skills/`** — the judgment tasks as skills, and `glossary.md`, the
  transcription-error glossary that grows with every call

## Where things are

| | |
|---|---|
| `web/` | the call app (trainee side `/t/`, coach side `/c/`), deployed by Vercel |
| `api/`, `server/` | stateless session endpoints; no personal data stored server-side |
| `agent/` | `itqan_agent.py` fetch → transcribe → align; `pending_calls.py` the session-start check; `promote.py` episode numbers |
| `render/` | `align.py`, `bubble_render.py`, `thumbnail.py`, `transcribe.py`, `transcript_tool.py`, and `callfolder.py` — the one place that knows the file names |
| `assets/` | brand mark, fonts (OFL), the host photo |
| `C:\Itqan\` | all recordings and outputs — outside OneDrive and git on purpose; see ENVIRONMENT |

## The constraints that shape everything

- **Arabic text is shaped through HarfBuzz to PNG.** ffmpeg's `drawtext` and libass both break Arabic ligatures. There is no subtitle burn-in step.
- **Each speaker is a separate recording.** That is what makes attribution, tone matching and turn re-timing possible.
- **Recordings are personal data.** They stay on this laptop, the cloud copy is deleted on download, and anything about a trainee's private life is a decision for Essam, never for a skill.
