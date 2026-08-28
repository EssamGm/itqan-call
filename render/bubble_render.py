#!/usr/bin/env python3
"""
Itqan bubble renderer.

Takes the two per-participant recordings from a 1:1 coaching call and
composites them into a square, publish-ready video: each speaker in their own
circular bubble on the Etqan dark surface, with their name inside it. Also
emits a clean audio-only track for podcast-style publishing.

The calls are voice only, so a bubble normally holds a name rather than video.
If a track does carry video (older recordings do), it fills the circle and the
name sits underneath instead.

Deliberately vendor-agnostic: it only cares that two media files exist. Nothing
here knows or cares whether Daily, LiveKit or Zoom produced them.

Usage:
    python bubble_render.py --a coach.m4a --b trainee.m4a \\
        --a-name عصام --b-name راكان --out ../out/call-001
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from arabic_text import render_text_png  # noqa: E402

# ---------------------------------------------------------------------------
# Brand - Etqan Brand Guidelines v1.1, dark mode surface.
# ---------------------------------------------------------------------------
SURFACE = "0B1A2A"      # dark navy-black page surface
GOLD = "C9A227"         # accent, coach bubble ring
NAVY_LIGHT = "3E6C99"   # trainee bubble ring
TEXT = "#F2F5F8"

# Square 1:1 canvas geometry.
CANVAS = 1080
DIAMETER = 460
MARGIN = 60
GAP = 40
RING = 7
CENTER_Y = 470
TOP_Y = CENTER_Y - DIAMETER // 2
A_X = MARGIN                        # 60
B_X = MARGIN + DIAMETER + GAP       # 560

NAME_MAX_W = int(DIAMETER * 0.72)   # keep names clear of the circle's edge
NAME_MAX_H = int(DIAMETER * 0.30)
# Delivery targets. The two files go to different places and the industry
# targets differ, so they are mastered differently rather than identically:
#
#   Audio  - podcast apps. Apple Podcasts asks for -16 LUFS / -1 dBTP, and the
#            AES streaming recommendation puts talk content in the -20..-16
#            band. Mono, because spoken word carries no stereo information and
#            a listener with one earbud must not lose a speaker.
#   Video  - YouTube, Instagram, TikTok all normalise to about -14 LUFS.
#
PODCAST_LUFS = -16.0
VIDEO_LUFS = -14.0
TRUE_PEAK = -1.0        # dBTP; the ceiling every platform asks for
TARGET_LRA = 7.0        # spoken word sits tight so quiet moments stay audible

# Per-voice cleanup before mixing. No denoiser: the call platform's own noise
# suppression already leaves a digitally silent floor, so denoising here would
# only add artefacts to audio that is already clean.
VOICE_CLEANUP = (
    "highpass=f=80,"                                   # room rumble, handling
    "deesser=i=0.3,"                                   # sibilance
    "agate=threshold=0.004:ratio=3:attack=10:release=250,"  # keep pauses silent
    "acompressor=threshold=-22dB:ratio=3:attack=6:release=180:makeup=3,"
    "alimiter=limit=0.95"
)

TARGET_LUFS = PODCAST_LUFS   # what the per-speaker balance aims each voice at

GLOW_SIZE = DIAMETER + 120      # room for the halo to bloom outside the ring
GLOW_MID = DIAMETER / 2.0 + 14  # sits just outside the bubble edge
GLOW_SIGMA = 22.0               # falloff; wider reads as a softer breath
GLOW_GAIN = 1.7                 # ordinary speech should glow clearly,
                                # not only shouting

LOGO_W = 280
LOGO_Y = 880


def run(cmd, **kw):
    """Run a command, raising with ffmpeg's own stderr on failure."""
    p = subprocess.run(cmd, capture_output=True, text=True, **kw)
    if p.returncode != 0:
        tail = "\n".join((p.stderr or "").strip().splitlines()[-25:])
        raise RuntimeError("command failed: " + " ".join(cmd[:3]) + "...\n" + tail)
    return p.stdout


def probe(path):
    """Return {duration, has_video, has_audio} for a media file."""
    out = run([
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration:stream=codec_type",
        "-of", "json", path,
    ])
    data = json.loads(out)
    kinds = {s.get("codec_type") for s in data.get("streams", [])}
    try:
        dur = float(data["format"]["duration"])
    except (KeyError, TypeError, ValueError):
        dur = 0.0
    return {"duration": dur, "has_video": "video" in kinds, "has_audio": "audio" in kinds}


def measure_loudness(path):
    """Integrated loudness in LUFS, or None if it cannot be measured."""
    p = subprocess.run(
        ["ffmpeg", "-hide_banner", "-nostats", "-i", path, "-af", "ebur128", "-f", "null", "-"],
        capture_output=True, text=True)
    val = None
    for line in (p.stderr or "").splitlines():
        s = line.strip()
        if s.startswith("I:") and "LUFS" in s:
            try:
                val = float(s.split()[1])
            except (IndexError, ValueError):
                pass
    return val


def measure_loudnorm(path):
    """
    First pass of a two-pass loudness normalisation.

    Single-pass loudnorm guesses as it goes and lands a decibel or two off
    target. Measuring the finished mix first, then normalising with those
    numbers, actually hits the figure the platforms expect.
    """
    p = subprocess.run([
        "ffmpeg", "-hide_banner", "-nostats", "-i", path,
        "-af", "loudnorm=I={}:TP={}:LRA={}:print_format=json".format(
            PODCAST_LUFS, TRUE_PEAK, TARGET_LRA),
        "-f", "null", "-",
    ], capture_output=True, text=True)
    text = p.stderr or ""
    start = text.rfind("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end < start:
        return None
    try:
        data = json.loads(text[start:end + 1])
    except ValueError:
        return None
    needed = ("input_i", "input_lra", "input_tp", "input_thresh")
    if not all(k in data for k in needed):
        return None
    return data


def loudnorm_filter(target, measured):
    """A loudnorm filter string, two-pass when a measurement is available."""
    base = "loudnorm=I={}:TP={}:LRA={}".format(target, TRUE_PEAK, TARGET_LRA)
    if not measured:
        return base
    return base + ":measured_I={}:measured_LRA={}:measured_TP={}:measured_thresh={}".format(
        measured["input_i"], measured["input_lra"],
        measured["input_tp"], measured["input_thresh"])


def source_size(path):
    try:
        out = run([
            "ffprobe", "-v", "error", "-select_streams", "v:0",
            "-show_entries", "stream=width,height", "-of", "csv=p=0:s=x", path,
        ]).strip()
        w, h = out.split("x")[:2]
        return int(w), int(h)
    except (RuntimeError, ValueError):
        return None, None


def detect_crop(path, duration):
    """
    Find the real picture area, discarding any letterbox/pillarbox bars.

    Call platforms sometimes pad a widescreen camera into whatever frame size
    was requested. Those bars are baked in, and without this they survive into
    the circular crop as flat black wedges.
    """
    start = max(0.0, min(duration * 0.3, max(0.0, duration - 2.0)))
    p = subprocess.run([
        "ffmpeg", "-v", "info", "-ss", "{:.2f}".format(start), "-i", path,
        "-vf", "cropdetect=24:2:0", "-frames:v", "60", "-f", "null", "-",
    ], capture_output=True, text=True)
    crops = [ln.split("crop=")[-1].strip()
             for ln in (p.stderr or "").splitlines() if "crop=" in ln]
    if not crops:
        return None
    try:
        w, h, x, y = (int(v) for v in crops[-1].split(":"))
    except ValueError:
        return None
    if w <= 0 or h <= 0:
        return None
    full_w, full_h = source_size(path)
    if full_w and full_h and (full_w - w) < 8 and (full_h - h) < 8:
        return None
    return "crop={}:{}:{}:{}".format(w, h, x, y)


def make_circle_mask(path, diameter):
    """One-frame antialiased white circle on black, used as an alpha mask."""
    r = diameter / 2.0
    expr = "clip(255*({}-hypot(X-{},Y-{})),0,255)".format(r - 0.5, r, r)
    run([
        "ffmpeg", "-y", "-v", "error",
        "-f", "lavfi", "-i", "color=c=black:s={0}x{0}".format(diameter),
        # Single-quote: ffmpeg's parser strips them, and without them the
        # commas inside hypot() read as filter separators.
        "-vf", "format=gray,geq=lum='" + expr + "'",
        "-frames:v", "1", path,
    ])


def make_disc(path, diameter, fill, ring_color, thickness):
    """A filled disc with a ring, so an empty bubble still reads as a bubble."""
    d = diameter + thickness * 2
    r = d / 2.0
    inner = r - thickness
    ring_alpha = ("clip(255*min({}-hypot(X-{},Y-{}),hypot(X-{},Y-{})-{}),0,255)"
                  .format(r - 0.5, r, r, r, r, inner - 0.5))
    disc_alpha = "clip(255*({}-hypot(X-{},Y-{})),0,255)".format(inner - 0.5, r, r)
    run([
        "ffmpeg", "-y", "-v", "error",
        "-f", "lavfi", "-i", "color=c=0x{}:s={}x{}".format(fill, d, d),
        "-f", "lavfi", "-i", "color=c=black:s={0}x{0}".format(d),
        "-f", "lavfi", "-i", "color=c=0x{}:s={}x{}".format(ring_color, d, d),
        "-f", "lavfi", "-i", "color=c=black:s={0}x{0}".format(d),
        "-filter_complex",
        "[1:v]format=gray,geq=lum='" + disc_alpha + "'[dm];"
        "[0:v][dm]alphamerge[disc];"
        "[3:v]format=gray,geq=lum='" + ring_alpha + "'[rm];"
        "[2:v][rm]alphamerge[ring];"
        "[disc][ring]overlay=0:0[o]",
        "-map", "[o]", "-frames:v", "1", path,
    ])


def make_glow(path, size, mid_radius, sigma, color):
    """
    A soft coloured halo, used as the speaking indicator.

    Drawn once as a still. Its opacity is driven per-frame from that speaker's
    own audio, so the bubble breathes with their voice without anything having
    to be generated frame by frame - which would be hopeless over a call
    lasting half an hour.
    """
    r = size / 2.0
    # Gaussian ring: brightest along mid_radius, fading smoothly both ways.
    alpha = "clip(255*exp(-pow(hypot(X-{r},Y-{r})-{m},2)/{d}),0,255)".format(
        r=r, m=mid_radius, d=2.0 * sigma * sigma)
    run([
        "ffmpeg", "-y", "-v", "error",
        "-f", "lavfi", "-i", "color=c=0x{}:s={}x{}".format(color, size, size),
        "-f", "lavfi", "-i", "color=c=black:s={0}x{0}".format(size),
        "-filter_complex",
        "[1:v]format=gray,geq=lum='" + alpha + "'[m];[0:v][m]alphamerge[o]",
        "-map", "[o]", "-frames:v", "1", path,
    ])


def level_graph(src, size, label):
    """
    Turn one speaker's audio into a per-frame brightness value.

    showvolume draws a meter whose length follows the signal; averaging that
    whole bar down to a single pixel turns it into one number per frame, which
    can then be blown up into a uniform field and used as an opacity mask.
    Native ffmpeg throughout, so it costs almost nothing.
    """
    return (
        "[{}:a]showvolume=r=25:b=0:w=400:h=20:f=0.9:dm=0:o=h,"
        "crop=400:1:0:10,scale=1:1,"
        # Lift the curve so conversational level reads as a clear glow rather
        # than a hint; without it only the loudest moments show. No clip():
        # lutyuv clamps by itself, and the commas inside clip() would be read
        # as filter separators.
        "lutyuv=y=val*{g},"
        "scale={s}:{s}:flags=neighbor,"
        "format=gray,setpts=PTS-STARTPTS[{l}]".format(src, g=GLOW_GAIN, s=size, l=label)
    )


def add_name_to_disc(disc_path, label, tmp_dir, tag):
    """
    Paint a name into the middle of a bubble.

    Done here rather than as a separate ffmpeg overlay because the text is
    rasterised onto a solid background, and overlaying that leaves a faintly
    visible rectangle. Reading it back as an alpha mask and painting the brand
    ink through it composites cleanly, with the antialiasing intact.
    """
    from PIL import Image

    if not label:
        return
    text_png = os.path.join(tmp_dir, "text_{}.png".format(tag))
    render_text_png(label, text_png, size=96, color="#FFFFFF", bg=0x000000)

    with Image.open(text_png) as raw:
        alpha = raw.convert("L")
    if alpha.width > NAME_MAX_W or alpha.height > NAME_MAX_H:
        scale = min(NAME_MAX_W / alpha.width, NAME_MAX_H / alpha.height)
        alpha = alpha.resize(
            (max(1, int(alpha.width * scale)), max(1, int(alpha.height * scale))),
            Image.LANCZOS,
        )

    ink = Image.new("RGBA", alpha.size, tuple(int(TEXT[i:i + 2], 16)
                                              for i in (1, 3, 5)) + (255,))
    ink.putalpha(alpha)

    with Image.open(disc_path) as d:
        disc = d.convert("RGBA")
    disc.alpha_composite(
        ink,
        ((disc.width - ink.width) // 2, (disc.height - ink.height) // 2),
    )
    disc.save(disc_path)


def pick_encoder(requested):
    """
    Prefer NVENC, falling back to libx264.

    Being listed by `ffmpeg -encoders` only means NVENC was compiled in, not
    that it can run - without an NVIDIA driver it fails at nvcuda.dll load
    time. So actually attempt a one-frame encode and believe the result.
    """
    if requested != "auto":
        return requested
    probe_cmd = [
        "ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=c=black:s=64x64",
        "-frames:v", "1", "-c:v", "h264_nvenc", "-f", "null", "-",
    ]
    if subprocess.run(probe_cmd, capture_output=True).returncode == 0:
        return "h264_nvenc"
    return "libx264"


def build_filter(tracks, total, fps, idx):
    """
    Compose the canvas.

    `idx` maps each overlay asset to its ffmpeg input index, so inputs can be
    added or omitted (no logo, no name) without renumbering by hand.
    """
    parts = ["color=c=0x{}:s={}x{}:r={}:d={:.3f}[bg]".format(
        SURFACE, CANVAS, CANVAS, fps, total)]
    stage = "bg"

    for i, t in enumerate(tracks):
        x = A_X if i == 0 else B_X
        disc = idx["disc"][i]

        # Halo first, so the bubble sits cleanly on top of it and the glow
        # reads as light spilling outwards rather than a ring drawn over.
        if idx["glow"][i] is not None and t["has_audio"]:
            gx = x + DIAMETER // 2 - GLOW_SIZE // 2
            gy = TOP_Y + DIAMETER // 2 - GLOW_SIZE // 2
            parts.append(level_graph(i, GLOW_SIZE, "lvl{}".format(i)))
            parts.append("[{}:v]split=2[gc{}][gs{}]".format(idx["glow"][i], i, i))
            parts.append("[gs{0}]alphaextract[ga{0}]".format(i))
            # Shape x loudness = how much of the halo shows this frame.
            parts.append("[ga{0}][lvl{0}]blend=all_mode=multiply[gm{0}]".format(i))
            parts.append("[gc{0}][gm{0}]alphamerge[glow{0}]".format(i))
            parts.append("[{}][glow{}]overlay={}:{}:eof_action=pass[gw{}]".format(
                stage, i, gx, gy, i))
            stage = "gw{}".format(i)

        # The disc carries both the fill and the ring, so an audio-only bubble
        # is never an empty hole in the canvas.
        parts.append("[{}][{}:v]overlay={}:{}[d{}]".format(
            stage, disc, x - RING, TOP_Y - RING, i))
        stage = "d{}".format(i)

        if t["has_video"]:
            debar = (t.get("crop") + ",") if t.get("crop") else ""
            parts.append(
                "[{0}:v]{1}scale={2}:{2}:force_original_aspect_ratio=increase,"
                "crop={2}:{2},fps={3},format=rgba[c{4}]".format(
                    i, debar, DIAMETER, fps, i))
            parts.append("[c{0}][{1}:v]alphamerge[m{0}]".format(i, idx["mask"]))
            parts.append("[{}][m{}]overlay={}:{}:eof_action=pass[v{}]".format(
                stage, i, x, TOP_Y, i))
            stage = "v{}".format(i)

    if idx["logo"] is not None:
        # The logo PNG is rendered on the same surface colour as the canvas, so
        # its rectangle disappears into the background with no alpha needed.
        parts.append("[{}:v]scale={}:-1[logo]".format(idx["logo"], LOGO_W))
        parts.append("[{}][logo]overlay=(W-w)/2:{}[wm]".format(stage, LOGO_Y))
        stage = "wm"

    parts.append("[{}]format=yuv420p[vout]".format(stage))
    return ";".join(parts)


def logo_path():
    p = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                     "assets", "logo-reversed.png")
    return p if os.path.isfile(p) else None


def main():
    ap = argparse.ArgumentParser(
        description="Render an Itqan call into a square bubble video.")
    ap.add_argument("--a", required=True, help="track A (coach)")
    ap.add_argument("--b", required=True, help="track B (trainee)")
    ap.add_argument("--out", required=True, help="output path without extension")
    ap.add_argument("--a-name", default="", help="name shown in bubble A")
    ap.add_argument("--b-name", default="", help="name shown in bubble B")
    ap.add_argument("--a-offset", type=float, default=0.0)
    ap.add_argument("--b-offset", type=float, default=0.0)
    ap.add_argument("--fps", type=int, default=25)
    ap.add_argument("--encoder", default="auto", help="auto | libx264 | h264_nvenc")
    ap.add_argument("--external-audio", default="",
                    help="use this audio instead of mixing the two tracks; for "
                         "comparing an outside enhancer against our own")
    ap.add_argument("--no-pulse", action="store_true",
                    help="static bubbles; no speaking halo")
    ap.add_argument("--no-cleanup", action="store_true",
                    help="skip per-voice EQ, de-essing and compression")
    args = ap.parse_args()

    for p in (args.a, args.b):
        if not os.path.isfile(p):
            sys.exit("error: no such file: " + p)
    if not shutil.which("ffmpeg"):
        sys.exit("error: ffmpeg not found on PATH")

    tracks = [probe(args.a), probe(args.b)]
    if not any(t["has_audio"] for t in tracks):
        sys.exit("error: neither track has audio - nothing to publish")

    for t, path in zip(tracks, (args.a, args.b)):
        t["crop"] = detect_crop(path, t["duration"]) if t["has_video"] else None
        if t["crop"]:
            sys.stderr.write("removing letterbox from {}: {}\n".format(
                os.path.basename(path), t["crop"]))

    total = max(args.a_offset + tracks[0]["duration"],
                args.b_offset + tracks[1]["duration"])
    if total <= 0:
        sys.exit("error: could not determine a positive duration")

    os.makedirs(os.path.dirname(os.path.abspath(args.out)) or ".", exist_ok=True)
    tmp = tempfile.mkdtemp(prefix="itqan-render-")
    try:
        mask = os.path.join(tmp, "mask.png")
        disc_a = os.path.join(tmp, "disc_a.png")
        disc_b = os.path.join(tmp, "disc_b.png")
        make_circle_mask(mask, DIAMETER)
        make_disc(disc_a, DIAMETER, "122943", GOLD, RING)
        make_disc(disc_b, DIAMETER, "122943", NAVY_LIGHT, RING)

        # Shaped via HarfBuzz, not ffmpeg drawtext: drawtext maps Arabic onto
        # the deprecated Presentation Forms block and drops letters.
        for disc, label, tag in ((disc_a, args.a_name, "a"),
                                 (disc_b, args.b_name, "b")):
            add_name_to_disc(disc, (label or "").strip(), tmp, tag)

        glow_a = os.path.join(tmp, "glow_a.png")
        glow_b = os.path.join(tmp, "glow_b.png")
        if not args.no_pulse:
            make_glow(glow_a, GLOW_SIZE, GLOW_MID, GLOW_SIGMA, GOLD)
            make_glow(glow_b, GLOW_SIZE, GLOW_MID, GLOW_SIGMA, NAVY_LIGHT)

        logo = logo_path()

        # Build the input list and record where each asset landed.
        cmd = ["ffmpeg", "-y", "-v", "error", "-stats"]
        cmd += ["-itsoffset", str(args.a_offset), "-i", args.a]
        cmd += ["-itsoffset", str(args.b_offset), "-i", args.b]
        nxt = 2
        idx = {"mask": None, "disc": [], "glow": [], "logo": None}
        cmd += ["-i", mask]; idx["mask"] = nxt; nxt += 1
        for d in (disc_a, disc_b):
            cmd += ["-i", d]; idx["disc"].append(nxt); nxt += 1
        for g in (glow_a, glow_b):
            if args.no_pulse:
                idx["glow"].append(None)
            else:
                cmd += ["-i", g]; idx["glow"].append(nxt); nxt += 1
        if logo:
            cmd += ["-i", logo]; idx["logo"] = nxt; nxt += 1

        # Match the two speakers to each other before mixing.
        #
        # Different devices and distances put the two voices at different
        # levels - a phone held close against a laptop across a desk measured
        # 3.7 LU apart. In a published recording that means one person is
        # persistently quieter, and normalising the finished mix cannot fix it:
        # it lifts both together and preserves the gap.
        #
        # A measured fixed gain per track rather than per-track loudnorm: these
        # recordings are mostly silence while the other person talks, and
        # dynamic normalisation would pump that silence up between phrases.
        srcs = [i for i, t in enumerate(tracks) if t["has_audio"]]
        gains = {}
        for i in srcs:
            measured = measure_loudness((args.a, args.b)[i])
            if measured is not None and measured > -70:
                gains[i] = max(-12.0, min(12.0, TARGET_LUFS - measured))
                sys.stderr.write("track {}: {:.1f} LUFS -> {:+.1f} dB\n".format(
                    i, measured, gains[i]))

        def leg(i):
            g = gains.get(i, 0.0)
            clean = VOICE_CLEANUP if not args.no_cleanup else "anull"
            return "[{0}:a]{1},volume={2:.2f}dB[g{0}]".format(i, clean, g)

        pre = ";".join(leg(i) for i in srcs)
        if len(srcs) == 2:
            mix_graph = pre + ";[g0][g1]amix=inputs=2:duration=longest:normalize=0[m]"
        else:
            mix_graph = pre + ";[g{}]anull[m]".format(srcs[0])

        # Render the mix losslessly first, so it can be measured and then
        # mastered twice without stacking two lossy encodes on top of it.
        mix_wav = os.path.join(tmp, "mix.wav")
        if args.external_audio:
            # An outside enhancer supplies the mix; the per-speaker tracks are
            # still read, because the speaking halo is driven from them.
            if not os.path.isfile(args.external_audio):
                sys.exit("error: no such file: " + args.external_audio)
            sys.stderr.write("using external audio: {}\n".format(
                os.path.basename(args.external_audio)))
            run(["ffmpeg", "-y", "-v", "error", "-i", args.external_audio,
                 "-c:a", "pcm_s24le", "-ar", "48000", mix_wav])
        else:
            run(["ffmpeg", "-y", "-v", "error",
                 "-itsoffset", str(args.a_offset), "-i", args.a,
                 "-itsoffset", str(args.b_offset), "-i", args.b,
                 "-filter_complex", mix_graph, "-map", "[m]",
                 "-c:a", "pcm_s24le", "-ar", "48000", "-t", "{:.3f}".format(total),
                 mix_wav])

        measured_mix = measure_loudnorm(mix_wav)

        # The mono fold changes the measurement, so the podcast master needs
        # its own pass rather than reusing the stereo numbers.
        mono_wav = os.path.join(tmp, "mix_mono.wav")
        run(["ffmpeg", "-y", "-v", "error", "-i", mix_wav,
             "-af", "aformat=channel_layouts=mono",
             "-c:a", "pcm_s24le", "-ar", "48000", mono_wav])
        measured_mono = measure_loudnorm(mono_wav)

        if measured_mix:
            sys.stderr.write("mix: stereo {} LUFS, mono {} LUFS\n".format(
                measured_mix["input_i"],
                measured_mono["input_i"] if measured_mono else "?"))

        # Feed the measured mix back in, so each output is mastered from the
        # same lossless source rather than re-encoding an already-lossy file.
        cmd += ["-i", mix_wav]
        mix_idx = nxt
        nxt += 1

        filt = build_filter(tracks, total, args.fps, idx)
        # An input pad can only be consumed once, hence the split.
        filt += ";[{}:a]asplit=2[mv][ma]".format(mix_idx)
        filt += ";[mv]{},aresample=48000[aout_v]".format(
            loudnorm_filter(VIDEO_LUFS, measured_mix))
        # Fold to mono BEFORE normalising. Downmixing afterwards sums the
        # channels and pushes the true peak back above the ceiling loudnorm
        # had just enforced - measured at +0.6 dBFS doing it the other way.
        filt += ";[ma]aformat=channel_layouts=mono,{},aresample=48000[aout_a]".format(
            loudnorm_filter(PODCAST_LUFS, measured_mono))

        encoder = pick_encoder(args.encoder)
        quality = (["-cq", "23", "-preset", "p5"] if encoder == "h264_nvenc"
                   else ["-crf", "20", "-preset", "medium"])

        video_out = args.out + ".mp4"
        audio_out = args.out + ".m4a"
        dur = "{:.3f}".format(total)

        cmd += ["-filter_complex", filt]
        # Video: stereo, louder, for platforms that normalise near -14 LUFS.
        cmd += ["-map", "[vout]", "-map", "[aout_v]", "-c:v", encoder] + quality
        cmd += ["-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart",
                "-t", dur, video_out]
        # Audio: mono for podcast apps. Spoken word carries no stereo
        # information, and a listener with one earbud must not lose a speaker.
        cmd += ["-map", "[aout_a]", "-c:a", "aac", "-b:a", "128k",
                "-t", dur, audio_out]

        sys.stderr.write("rendering {:.1f}s via {} ...\n".format(total, encoder))
        run(cmd)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print("video: " + video_out)
    print("audio: " + audio_out)


if __name__ == "__main__":
    main()
