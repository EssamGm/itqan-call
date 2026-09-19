# Environment

What the pipeline runs on, with the versions it was built and verified
against. Every value here was read from the machine on 2026-09-19, not
recalled.

## Machine

| | |
|---|---|
| OS | Windows 11 Home, build 10.0.26200 |
| Shell used for the scripts | Git Bash (POSIX paths like `/c/Itqan`); PowerShell also works |
| GPU | none usable — `h264_nvenc` is listed by ffmpeg but has no driver, so the renderer test-encodes one frame and falls back to `libx264` |
| CPU transcription speed | about 0.6× real time with `large-v3` int8 — a 17-minute call takes roughly an hour per two tracks |

## Data locations

| Path | What | Why there |
|---|---|---|
| `C:\Itqan\` | every recording, transcript, render and the episode ledger | deliberately **outside OneDrive and outside git** — the recordings are personal data under Saudi PDPL and must not sync to a cloud or be pushed |
| `C:\Itqan\.env` | secrets, referenced by name only: `DAILY_API_KEY`, `VAPID_PRIVATE_KEY`, `VAPID_PUBLIC_KEY` | same reason; never printed, never committed |
| `C:\Itqan\calls\<YYYY-MM-DD>_<guest>\` | one folder per call — the pipeline's interface | see README |
| `C:\Itqan\episodes.tsv` | the episode ledger | data, not code |
| `C:\Itqan\recordings\raw\` | legacy: per-recording files from before the folder layout | kept so old calls can be re-rendered; nothing new lands here |
| the repo `itqan-call/` | code, skills, docs, brand assets, fonts | pushed to a private GitHub repo; contains no recordings |

The one exception to "no personal data in the repo" is the glossary,
which records names as they were mis-transcribed (`يا صدق` → `يا صلاح`). That
is a knowing trade: the glossary is the asset that compounds and it has to be
version-controlled.

## Tools

| Tool | Version | Install |
|---|---|---|
| ffmpeg / ffprobe | 7.1.1 essentials build (gyan.dev) | `winget install Gyan.FFmpeg`, or the gyan.dev zip on PATH |
| Python | 3.10.11 | python.org installer; `python` on PATH (not `python3` on this machine) |
| Node | not installed | the web app is static files deployed by Vercel; nothing local needs Node |

## Python packages

```
pip install faster-whisper==1.2.1 numpy==2.2.6 pillow==11.3.0 uharfbuzz==0.56.0 fonttools==4.63.0 svglib==2.2.0 reportlab==5.0.1
```

| Package | Version | Used for |
|---|---|---|
| faster-whisper | 1.2.1 | transcription, model `large-v3`, `device="cpu"`, `compute_type="int8"`, `beam_size=5`, `vad_filter=True`, `word_timestamps=True` |
| ctranslate2 | 4.8.1 | pulled in by faster-whisper |
| numpy | 2.2.6 | turn alignment, audio measurement |
| Pillow | 11.3.0 | discs, glow layers, caption panels, lockup, thumbnail |
| uharfbuzz | 0.56.0 | Arabic shaping — the only correct way to draw Arabic in this pipeline |
| fonttools | 4.63.0 | glyph outlines for the shaped text |
| svglib + reportlab | 2.2.0 / 5.0.1 | rasterising the shaped SVG to PNG |

## Models

`faster-whisper` downloads on first use into `~/.cache/huggingface/hub/`.
Present on this machine: `models--Systran--faster-whisper-large-v3` (the one
in use) and `models--Systran--faster-whisper-small` (rejected — see
DECISIONS). No API key, no network after the first download, no audio leaves
the machine.

## Fonts

In `assets/fonts/`, all under the OFL:

| File | Where it is used |
|---|---|
| `IBMPlexSansArabic-SemiBold.ttf` | captions, bubble names, the `بودكاست` label, thumbnail guest name and pitch |
| `Cairo-Black.ttf` | thumbnail headline |
| `Cairo-Bold.ttf` | thumbnail `المدرب` label |
| `Cairo-VF.ttf` | not currently used |

## External services

By name only; no credentials here.

| Service | Role |
|---|---|
| Daily.co | call transport and per-participant cloud recording (`cloud-audio-only`, one recording per participant). Recordings are deleted from Daily as soon as they are downloaded. |
| Vercel | hosts the call web app at `itqan-call.vercel.app`; auto-deploys from the repo's `main` |
| Upstash Redis | stores web-push subscriptions for the "someone is calling" notification |
| GitHub | private repo for the code |

## Claude Code

The pipeline's trigger is a `SessionStart` hook in the workspace's
`.claude/settings.json` that runs `agent/pending_calls.py`. It lists calls
still in the cloud, silently says nothing when there are none, and never
errors — a moved `.env` must not put a message at the top of every session.
