# Decisions, and what was tried and rejected

Consolidated from the git log, which explains each one at the commit. The
point of this file is the second half of each entry: the approaches that
failed, so the next version does not repeat them. Every rejection here was
measured, not assumed.

## Capture

**Two recordings per call, one per participant, `cloud-audio-only`.**
Rejected: Daily's `raw-tracks` (needs an S3 bucket you own) and a single
mixed recording (loses speaker attribution, makes tone matching and turn
alignment impossible). Everything good about the output depends on having
each voice on its own file.

**Wait for Daily's `recording-started` event, not the promise.**
`startRecording()` resolves even when the recording is refused; the error
arrives as a separate event. One whole call recorded nothing, silently. The
"loud on failure" guarantee only holds if you wait for the confirmation.

**Room and client must ask for the same recording type.** Room said `cloud`,
client asked `cloud-audio-only` → "startRecording ignored: not enabled".

**Record 1280×720 and crop, not square.** Asking Daily for a square recording
pads 16:9 inside it. `cropdetect` is the safety net.

**Screen wake lock in the browser.** A phone that locks its screen suspends
the page and microphone capture stops; the server keeps recording and
receives nothing. One call lost 97 seconds this way. The lock is re-acquired
on `visibilitychange` because browsers drop it whenever the page is hidden.

**Not fixed, known:** the app requests `autoGainControl` and
`noiseSuppression`. Both run before any audio reaches this machine. AGC is the
best explanation for the coach's voice sounding intermittently suppressed,
and WebRTC's noise suppression is what produces the digital-silence vacuum
between phrases (raw tracks measured 54.7% exact-zero samples). Turning them
off for the coach only — Rode, controlled room, level normalised downstream —
is the recommended next change; it needs one live call to validate.

## Arabic text

**HarfBuzz → SVG paths → svglib, for every piece of text.** Rejected:
ffmpeg `drawtext` (maps Arabic onto the deprecated Presentation Forms block
and drops letters — Cairo has 89 of 140 forms, Dubai 90) and libass burn-in
(same class of failure). This is the single largest technical constraint in
the project and the reason there is no subtitle "burn-in" step: captions are
shaped to PNG frames and overlaid.

**Apply HarfBuzz's `y_offset`, not only `x_offset`.** Without it a shadda
over ل lands on the ل rather than above it. Found on the thumbnail pitch.

**svglib reads width/height as points and the viewBox as user units** (a
1.333× mismatch) — strip the attributes and pad the viewBox or the logo is
cropped.

**Arabic punctuation only in captions** (`؟ ، ؛`). Whisper writes Latin marks
even for Arabic; next to Arabic script a `?` reads as a typo.

## Transcription

**`large-v3`, int8, CPU.** Rejected: `small` — it produced `فيه معادل` for
`فيه معاهد` and `دصر` for `بس صح`, the difference between nonsense and
usable text. 0.6× real time instead of 3× is worth it because the render
happens unattended anyway.

**Do not filter on `no_speech_prob`.** It is reported per decode window, not
per segment; filtering on it threw away 13 good lines out of 31.

**Word-level starts are identical to segment starts** (measured `+0.000`
across 176 segments), so the caption lag is in the model's alignment and only
a fixed lead (`LEAD_SECONDS = 0.32`) addresses it.

**Backchannel is filtered by an explicit list.** `ايوه` and its spellings got
through and put four consecutive `ايو` captions on screen. The list has to be
extended by hand when a new spelling appears.

**Corrections are made by context, not by a bigger model.** The residual
errors are near-homophones the model substitutes for uncommon words
(`يتقع` for `إتقان`); no acoustic model fixes those. The glossary is the
compounding asset. **Never normalise a trainee's dialect toward the coach's,
or either toward formal Arabic** — one trainee was Levantine, one Egyptian
(and the coach code-switched into Egyptian to meet him), one Hijazi.

**Corrections survive re-transcription only via `reapply`**, which matches by
text rather than line number. Bumping `CACHE_VERSION` otherwise destroys them
along with the machine output.

## Audio

**Master the two outputs to their own targets:** podcast −16 LUFS mono,
video −14 LUFS, both ≤ −1 dBTP. Two-pass `loudnorm`. Fold to mono *before*
normalising — downmixing afterwards sums the channels and pushed the true
peak to +0.6 dBFS.

**A limiter at −2.0 dBFS after `loudnorm`, before the encoder.** `loudnorm`
enforces its ceiling on the PCM it emits; AAC overshoots on top of that, and
one master came out at **+0.09 dBFS** from a mix held at −1.0. A limiter
rather than a lower `loudnorm` ceiling, because the lower ceiling makes
`loudnorm` pull the whole mix down on every call. `alimiter` must carry
`level=disabled` — measured: with it, a full-scale test lands at exactly
−2.000 dBFS; without it, 0.000, because auto-level pushes the signal straight
back up.

**Match the two voices toward each other, not one to the other.** A trainee
on a weak connection was 11.5 dB down above 6 kHz because Opus narrowed the
band. Rejected: ffmpeg `aexciter` (recovered 2 dB of a 12 dB deficit) and a
rectifier exciter (~0 dB) — you cannot synthesise a band that was never
transmitted. What works: move both voices toward a shared target
(`MEET_TOWARD_TRAINEE = 0.3`), cap the boost at +7 dB, lift the trainee 1.5 dB.

**Loudness checks are tolerances, not exact figures.** `loudnorm` lands
about ±0.5 LU of target; a check written as "−1.0 dBTP exactly" fails every
time and trains you to ignore it.

**The voice chain is in broadcast order, with a room-tone bed.** De-esser
*after* compression (before it, the compressor re-amplifies what was
removed), attack 6 → 15 ms so consonant onsets survive, −2 dB at 250 Hz,
+2.5 dB at 3.2 kHz, no gate (measured at 0.0–0.3 dB of effect; the vacuum was
never its doing), and pink noise band-limited 90 Hz–5.5 kHz at −62 dBFS under
the mix so a pause sounds like a room rather than the line dropping. Measured
on a real call: +3.5 dB consonant energy, digital silence 16% → 0%, floor
spread 41 → 29 dB. Shipped on Essam's standing instruction to own audio
quality; the A/B is at `C:\Itqaninal\mic-test\` if it ever needs
revisiting.

**The Rode microphone is worth using.** +13.5 dB SNR, +8.7 dB consonant energy
over the phone, and the advantage *grows* through Opus at lower bitrates
(+8.8 → +10.5 dB) because the codec spends bits on consonant energy that is
actually there. Caveat: this fixes the coach's half only.

**Do not run `voice-audio-master` / `voxpipe.py` on call recordings.** It is
calibrated for the Rode in the coach's dry room; on a phone-through-codec
call it misreads the 9 kHz band-limit as bad mic aim and the WebRTC vacuum as
a −240 dBFS noise floor.

## Conversation timing

**Re-time the turns; do not cut shared silence.** First attempt removed
silence where both tracks were quiet. It could not create overlap but it
also did nothing about the overlap already in the recording, which is what
makes a laggy call hard to listen to. Measured: median overlapping utterance
began 0.08 s after the other person's turn — two people starting at the same
instant, not a listener murmuring mid-sentence. Essam's account of the
mechanism: he pauses for the `ايوه`, the trainee has not heard the pause yet,
he gives up and continues, and the `ايوه` lands on his resumed sentence.

**Late answers are moved in front of the sentence they collided with.** A
short utterance within 0.75 s of the other speaker's turn start is treated as
a reply that arrived late. Only a murmur landing ≥ 1.5 s into a sentence is
left overlapping as genuine backchannel. Rejected: pinning every short
overlap to its host sentence (preserved exactly the artefact being removed).

**No global track offset exists to correct.** Tested: response-time floors
for each direction agree within 20 ms at every percentile. Daily stamps both
streams on one clock; the collisions are real events caused by the delay,
not a timestamping artefact.

**Same-speaker pauses capped at 2.0 s.** One ran to 19.6 s — the coach
waiting in silence for a trainee whose connection had dropped. This is a
judgement Essam can reverse.

## Pipeline structure

**Folder per call, files as the interface.** Rejected: the serial flow where
transcription, correction, cutting and thumbnail each waited on the previous
with Essam present for all of it. Each task now reads and writes plain files
in one folder and can be picked up alone, in any order its inputs allow, in
any tool.

**Judgment works on the aligned clock via `conversation.tsv`.** Rejected:
"the transcript timeline" — there are two per-speaker clocks with different
join offsets and independent index spaces, so a cut spanning an exchange has
no well-defined range on either. `align.py` writes the merged, ordered
conversation once; render reads the saved plan rather than recomputing it,
so the timeline judgment saw is the timeline that gets built.

**Render owns every remap.** Chapters and cuts are written on the aligned
clock; render maps them to the final one with explicit rules (chapter inside
a cut moves to the cut's end; a chapter whose section mostly vanished is
dropped and the previous runs on; first clamped to 0:00; two closer than
10 s → the later dropped, because YouTube rejects the whole list). Every move
is printed. This arithmetic was done by hand three times and the third time
still had a mistake.

**`corrections.txt` carries changed lines only.** Rejected: full-file
rewrite (my own first design) — it made deletion detectable by check; the
delta form makes deletion impossible by construction, and gives a readable
diff. `-` blanks a caption, for garbage only, never to silence real speech.

**`cuts.txt` has three statuses.** `cut` applies, `ask` blocks the render,
`keep` records a decision so it is not re-litigated. Anything about a
trainee's family, money or health is always `ask` — Essam's decision, never
the skill's.

**The episode number is assigned by `promote`, into a ledger at
`C:\Itqan\episodes.tsv`.** Rejected: letting PACKAGE write it (a skill in
isolation cannot know how many episodes exist) and keeping the ledger in the
repo (it is a list of which trainee was on which call — personal data).

**Transcription starts the moment a call ends, unattended.** The hour of
machine time is finished before Essam sits down; nothing waits on him that
does not need him.
