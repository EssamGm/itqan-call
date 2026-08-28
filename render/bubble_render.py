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
TARGET_LUFS = -16.0   # broadcast/podcast norm; both speakers are matched to it

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
    ap.add_argument("--no-loudnorm", action="store_true")
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

        logo = logo_path()

        # Build the input list and record where each asset landed.
        cmd = ["ffmpeg", "-y", "-v", "error", "-stats"]
        cmd += ["-itsoffset", str(args.a_offset), "-i", args.a]
        cmd += ["-itsoffset", str(args.b_offset), "-i", args.b]
        nxt = 2
        idx = {"mask": None, "disc": [], "logo": None}
        cmd += ["-i", mask]; idx["mask"] = nxt; nxt += 1
        for d in (disc_a, disc_b):
            cmd += ["-i", d]; idx["disc"].append(nxt); nxt += 1
        if logo:
            cmd += ["-i", logo]; idx["logo"] = nxt; nxt += 1

        # Match the two speakers to each other before mixing.
        #
        # Different devices and distances put the two voices at different
        # levels - a phone held close against a laptop across a desk can differ
        # by several LU, which in a published recording means one person is
        # persistently quieter. Normalising the finished mix cannot fix that;
        # it lifts both together and preserves the imbalance.
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
            g = gains.get(i)
            return "[{0}:a]volume={1:.2f}dB[g{0}]".format(i, g) if g else \
                   "[{0}:a]anull[g{0}]".format(i)

        pre = ";".join(leg(i) for i in srcs)
        if len(srcs) == 2:
            amix = pre + ";[g0][g1]amix=inputs=2:duration=longest:normalize=0[amix]"
        else:
            amix = pre + ";[g{}]anull[amix]".format(srcs[0])
        # loudnorm resamples internally and emits 96kHz; force 48kHz back.
        norm = "anull" if args.no_loudnorm else "loudnorm=I=-16:TP=-1.5:LRA=11"
        chain = "[amix]" + norm + ",aresample=48000,asplit=2[aout_v][aout_a]"

        filt = build_filter(tracks, total, args.fps, idx) + ";" + amix + ";" + chain

        encoder = pick_encoder(args.encoder)
        quality = (["-cq", "23", "-preset", "p5"] if encoder == "h264_nvenc"
                   else ["-crf", "20", "-preset", "medium"])

        video_out = args.out + ".mp4"
        audio_out = args.out + ".m4a"
        dur = "{:.3f}".format(total)

        cmd += ["-filter_complex", filt]
        cmd += ["-map", "[vout]", "-map", "[aout_v]", "-c:v", encoder] + quality
        cmd += ["-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart",
                "-t", dur, video_out]
        cmd += ["-map", "[aout_a]", "-c:a", "aac", "-b:a", "192k", "-t", dur, audio_out]

        sys.stderr.write("rendering {:.1f}s via {} ...\n".format(total, encoder))
        run(cmd)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print("video: " + video_out)
    print("audio: " + audio_out)


if __name__ == "__main__":
    main()
