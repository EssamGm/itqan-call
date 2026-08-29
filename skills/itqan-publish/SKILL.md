---
name: itqan-publish
description: Turn a finished إتقان coaching call into a publish-ready square video and podcast audio - fetch the recording from Daily, transcribe both speakers, correct the transcript against Itqan context, and render. Use this whenever Essam mentions processing, rendering, or publishing a call, asks for "the video" from a call, says a call is finished or that he just spoke with a trainee, asks to check for new recordings, or wants captions fixed on an existing call. Trigger on Arabic phrasings too - "سويت مكالمة", "خلصت المكالمة", "اطلع الفيديو", "جهز الفيديو". Also use when only part of the pipeline is wanted, such as re-rendering an existing call with better captions.
---

# Publishing an Itqan call

A finished call becomes two files: a square 1080×1080 video with named speaker
bubbles and captions, and a clean mono audio track for podcast apps. Both land
in `C:\Itqan\recordings\published\`.

Almost all of this is already automated. The one part that needs judgement —
and the reason this skill exists — is **correcting the transcript**. The speech
model transcribes sound with no idea what the conversation is about; you know
it is an إتقان coaching call between عصام and a trainee, which lets you fix
errors no larger acoustic model can.

## The pipeline

Working directory is `C:\Users\enges\OneDrive\Desktop\Claude WorkSpace\itqan-call`.

### 1. Fetch the recording

```bash
python agent/itqan_agent.py
```

This downloads both per-speaker tracks from Daily into
`C:\Itqan\recordings\raw\`, renders a first pass, and deletes the cloud copies.
It is safe to run repeatedly — already-processed calls are skipped.

If it reports "only 1 recording - waiting for its pair", the second recording
has not finished uploading. Wait a minute and run it again.

### 2. Transcribe

Transcription happens inside the render, but running it separately first lets
you correct the text before any video is made:

```bash
cd /c/Itqan/recordings/raw
PYTHONIOENCODING=utf-8 python <repo>/render/transcribe.py <coach-file>.m4a
PYTHONIOENCODING=utf-8 python <repo>/render/transcribe.py <trainee-file>.m4a
```

Files are named `<id>_coach.m4a` and `<id>_trainee.m4a`. This uses `large-v3`
and runs at roughly 0.6× real time, so a 30-minute call takes about 50 minutes
per track. Results cache to `<id>_<role>.v4.transcript.json` — re-rendering
never re-transcribes.

### 3. Correct the transcript — the part that needs you

Read `references/glossary.md` first. It holds the names, programme vocabulary,
and the specific errors this model has made before.

For each transcript:

```bash
python skills/itqan-publish/scripts/transcript_tool.py dump <transcript.json> > /tmp/lines.txt
```

That gives you `index<TAB>text`, one caption per line. Work through it and
write a corrected file in the same shape, then:

```bash
python skills/itqan-publish/scripts/transcript_tool.py apply <transcript.json> /tmp/corrected.txt
python skills/itqan-publish/scripts/transcript_tool.py check <transcript.json>
```

`apply` refuses to write if lines were added, removed or reordered, because the
timings belong to the original lines and silently shifting them produces
captions that drift out of sync — a failure that looks fine until someone
watches the video.

If a call has to be re-transcribed after it was corrected — a settings change,
a better model — the corrections are recoverable rather than lost:

```bash
python skills/itqan-publish/scripts/transcript_tool.py reapply <new.json> <old.json>
```

It diffs the old transcript against its own backup to work out what was
changed, then matches those onto the new one by text rather than line number,
and tells you which ones no longer have anywhere to go.

**What to fix.** Lines that read as nonsense are almost always a near-homophone:
the model substituted a common word for an uncommon one. "فيه معادل" for "فيه
معاهد". Read for meaning, and when a line does not mean anything, find the
word that sounds close and does.

Fix names every time. إتقان, عصام, and the trainee's name recur in every call
and are the words a viewer is most likely to notice getting wrong.

**What to leave alone.** Saudi dialect is not broken formal Arabic. كده, ايش,
عشان, حقتي, بس are all correct as spoken. English words mid-sentence are normal
in these calls. Rewriting any of it into Modern Standard Arabic turns the
captions into a translation of the conversation instead of a record of it, and
loses the voice that makes the content worth publishing.

**When you cannot tell**, leave the line as it is. A slightly wrong caption is
ordinary; an invented one that reads confidently is worse, because a viewer who
speaks Arabic will trust it.

Add anything new you had to work out to `references/glossary.md`. That file is
the part of this pipeline that compounds.

### 4. Render

```bash
cd /c/Itqan/recordings/raw
PYTHONIOENCODING=utf-8 python <repo>/render/bubble_render.py \
  --a <id>_coach.m4a --b <id>_trainee.m4a \
  --a-name "عصام" --b-name "<trainee>" \
  --captions --out /c/Itqan/recordings/published/<date>_<name>
```

Roughly real time, so run it in the background and check back.

The trainee's name comes from the call itself — the agent logs it, or query
Daily's `/meetings` endpoint. Use the name they typed, not a transliteration.

### 5. Check before handing it over

Look at the result rather than assuming it worked:

```bash
ffmpeg -y -v error -ss 120 -i <out>.mp4 -frames:v 1 /tmp/frame.png
```

Read that frame. Confirm the caption is inside its panel, the names are right,
and the logo is clear. Then check the audio landed on target — video near
−14 LUFS, audio near −16, true peak around −1 dBTP:

```bash
ffmpeg -hide_banner -nostats -i <out>.mp4 -af ebur128=peak=true -f null - 2>&1 | tail -18
```

`loudnorm` lands close to a target rather than exactly on it, so expect around
half a LU either side — a real call came out at −14.6 and −16.7 against −14 and
−16. The true-peak ceiling is usually what holds integrated loudness a little
low, which is the right way round: better slightly quiet than clipped. Worry
when a figure is a couple of LU out, not a fraction, and worry about true peak
only if it climbs toward 0.

A 5-minute call renders to about 30 MB. Anything over 30 MB will not send to a
phone, so make a lighter copy alongside the original:

```bash
ffmpeg -y -v error -i <out>.mp4 -c:v libx264 -crf 27 -preset slow \
  -c:a copy -movflags +faststart <out>-small.mp4
```

## Useful flags

| Flag | Why |
|---|---|
| `--captions` | Transcribe and burn in captions. Without it, no text. |
| `--external-audio <file>` | Use someone else's processed mix (Cleanvoice, say) while the bloom and captions still come from the separate tracks. Lets two versions be compared with identical visuals. |
| `--no-match` | Skip tone matching between the two voices. |
| `--no-pulse` | Static bubbles. |
| `--a-offset` / `--b-offset` | Only if the two tracks did not start together. |

## Things that will come up

**The trainee barely speaks.** Normal — the coach explains for most of a call.
On one real call it was 230 seconds against 47. Do not treat a lopsided
transcript as a fault.

**Backchannel is filtered.** Long runs of "ايه, ايه, ايه" are real speech,
correctly transcribed, and worth nothing on screen; the transcriber drops them
already. If a caption is nothing but a listening noise, the filter has a gap —
check `_is_filler` in `render/transcribe.py`. It matches an explicit list, so
each new spelling has to be added; "ايو" got through that way and put four
identical captions on screen.

**A voice sounds muffled.** Usually a weak connection, which narrows the codec's
band so the top octave was never transmitted. It cannot be restored — excitation
recovers about 2 dB of a 12 dB deficit. The renderer moves both voices toward
each other instead, which fixes the *step* between speakers even though it
cannot fix the absolute tone. Worth telling Essam to ask trainees for good
WiFi; that helps more than anything downstream.

**Transcription is cached by version.** Changing settings in `transcribe.py`
means bumping `CACHE_VERSION`, or old transcripts are served from disk and the
change appears to do nothing. Bumping it also discards any hand corrections on
already-processed calls, so run `reapply` afterwards to carry them across.
