#!/usr/bin/env python3
"""
Itqan bubble renderer.

Takes the two per-participant tracks recorded during a 1:1 coaching call and
composites them into a square, publish-ready video: each speaker in their own
circular bubble on the Etqan dark surface. Also emits a clean audio-only track
for podcast-style publishing.

Deliberately vendor-agnostic: it only cares that two media files exist. Nothing
here knows or cares whether Daily, LiveKit or Zoom produced them.

Usage:
    python bubble_render.py --a essam.webm --b trainee.webm --out ../out/call-001
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile

# ---------------------------------------------------------------------------
# Brand - Etqan Brand Guidelines v1.0 (Aug 2026), dark mode surface.
# The gold is the unified #C9A227; the older #B8860B is retired.
# ---------------------------------------------------------------------------
SURFACE = "0B1A2A"      # dark navy-black page surface
GOLD = "C9A227"         # accent, coach bubble ring
NAVY_LIGHT = "3E6C99"   # trainee bubble ring

# Square 1:1 canvas geometry.
CANVAS = 1080
DIAMETER = 460
MARGIN = 60
GAP = 40
RING = 7                # bubble ring thickness, px; 4 was invisible on a phone
LOGO_W = 280            # reversed wordmark, centred under the bubbles
LOGO_Y = 880
CENTER_Y = 470          # bubbles sit slightly high, leaving room for labels
TOP_Y = CENTER_Y - DIAMETER // 2
A_X = MARGIN                        # 60
B_X = MARGIN + DIAMETER + GAP       # 560


def run(cmd, **kw):
    """Run a command, raising with ffmpeg's own stderr on failure."""
    p = subprocess.run(cmd, capture_output=True, text=True, **kw)
    if p.returncode != 0:
        tail = "\n".join(p.stderr.strip().splitlines()[-25:])
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


def detect_crop(path, duration):
    """
    Find the real picture area, discarding any letterbox/pillarbox bars.

    Call platforms sometimes pad a widescreen camera into whatever frame size
    was requested. Those black bars are baked into the file, and without this
    they would survive into the circular crop and show as flat black wedges.
    Returns an ffmpeg crop filter string, or None when the frame is already
    all picture.
    """
    start = max(0.0, min(duration * 0.3, max(0.0, duration - 2.0)))
    probe_cmd = [
        "ffmpeg", "-v", "info", "-ss", "{:.2f}".format(start), "-i", path,
        "-vf", "cropdetect=24:2:0", "-frames:v", "60", "-f", "null", "-",
    ]
    p = subprocess.run(probe_cmd, capture_output=True, text=True)
    crops = [ln.split("crop=")[-1].strip()
             for ln in p.stderr.splitlines() if "crop=" in ln]
    if not crops:
        return None
    try:
        w, h, x, y = (int(v) for v in crops[-1].split(":"))
    except ValueError:
        return None
    if w <= 0 or h <= 0:
        return None
    # Ignore a couple of stray pixels; only act on real bars.
    full_w, full_h = source_size(path)
    if full_w and full_h and (full_w - w) < 8 and (full_h - h) < 8:
        return None
    return "crop={}:{}:{}:{}".format(w, h, x, y)


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


def make_circle_mask(path, diameter):
    """One-frame antialiased white circle on black, used as an alpha mask."""
    r = diameter / 2.0
    # clip() across a 1px band gives a soft, non-jagged edge.
    expr = "clip(255*({}-hypot(X-{},Y-{})),0,255)".format(r - 0.5, r, r)
    run([
        "ffmpeg", "-y", "-v", "error",
        "-f", "lavfi", "-i", "color=c=black:s={0}x{0}".format(diameter),
        # Single-quote the expression: ffmpeg's parser strips the quotes, and
        # without them the commas inside hypot() read as filter separators.
        "-vf", "format=gray,geq=lum='" + expr + "'",
        "-frames:v", "1", path,
    ])


def make_ring(path, diameter, thickness, color):
    """One-frame RGBA ring, drawn just outside the bubble edge."""
    d = diameter + thickness * 2
    r = d / 2.0
    inner = r - thickness
    # Antialiased annulus: opaque between `inner` and `r`.
    alpha = "clip(255*min({}-hypot(X-{},Y-{}),hypot(X-{},Y-{})-{}),0,255)".format(
        r - 0.5, r, r, r, r, inner - 0.5
    )
    run([
        "ffmpeg", "-y", "-v", "error",
        "-f", "lavfi", "-i", "color=c=0x{}:s={}x{}".format(color, d, d),
        "-f", "lavfi", "-i", "color=c=black:s={0}x{0}".format(d),
        "-filter_complex",
        "[1:v]format=gray,geq=lum='" + alpha + "'[m];[0:v][m]alphamerge[o]",
        "-map", "[o]", "-frames:v", "1", path,
    ])


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


def logo_path():
    """The reversed wordmark, rendered onto this exact surface colour."""
    p = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                     "assets", "logo-reversed.png")
    return p if os.path.isfile(p) else None


def build_video_filter(a, b, total, fps, logo_idx=None):
    """
    Filter graph: dark canvas, two circular bubbles with rings.

    Inputs are: 0=track A, 1=track B, 2=circle mask, 3=ring A, 4=ring B.
    Missing video (camera off) degrades to a static ring, so an audio-only
    trainee still renders rather than failing the whole job.
    """
    parts = ["color=c=0x{}:s={}x{}:r={}:d={:.3f}[bg]".format(
        SURFACE, CANVAS, CANVAS, fps, total)]
    stage = "bg"

    for idx, (src, x, has_video, ring_in) in enumerate(
        [(0, A_X, a["has_video"], 3), (1, B_X, b["has_video"], 4)]
    ):
        # Ring first, so the bubble sits on top of its inner edge.
        parts.append("[{}][{}:v]overlay={}:{}[r{}]".format(
            stage, ring_in, x - RING, TOP_Y - RING, idx))
        stage = "r{}".format(idx)

        if has_video:
            debar = (a, b)[idx].get("crop")
            parts.append(
                "[{0}:v]{4}scale={1}:{1}:force_original_aspect_ratio=increase,"
                "crop={1}:{1},fps={2},format=rgba[c{3}]".format(
                    src, DIAMETER, fps, idx, (debar + ",") if debar else "")
            )
            parts.append("[c{0}][2:v]alphamerge[m{0}]".format(idx))
            parts.append("[{}][m{}]overlay={}:{}:eof_action=pass[s{}]".format(
                stage, idx, x, TOP_Y, idx))
            stage = "s{}".format(idx)

    if logo_idx is not None:
        # The logo PNG is rendered on the same surface colour as the canvas, so
        # its rectangle disappears into the background with no alpha needed.
        parts.append("[{}:v]scale={}:-1[logo]".format(logo_idx, LOGO_W))
        parts.append("[{}][logo]overlay=(W-w)/2:{}[wm]".format(stage, LOGO_Y))
        stage = "wm"

    parts.append("[{}]format=yuv420p[vout]".format(stage))
    return ";".join(parts)


def main():
    ap = argparse.ArgumentParser(
        description="Render an Itqan call into a square bubble video.")
    ap.add_argument("--a", required=True, help="track A (coach)")
    ap.add_argument("--b", required=True, help="track B (trainee)")
    ap.add_argument("--out", required=True, help="output path without extension")
    ap.add_argument("--a-offset", type=float, default=0.0,
                    help="seconds to delay track A, to sync join times")
    ap.add_argument("--b-offset", type=float, default=0.0,
                    help="seconds to delay track B, to sync join times")
    ap.add_argument("--fps", type=int, default=30)
    ap.add_argument("--encoder", default="auto", help="auto | libx264 | h264_nvenc")
    ap.add_argument("--no-loudnorm", action="store_true",
                    help="skip broadcast loudness normalisation")
    args = ap.parse_args()

    for p in (args.a, args.b):
        if not os.path.isfile(p):
            sys.exit("error: no such file: " + p)
    if not shutil.which("ffmpeg"):
        sys.exit("error: ffmpeg not found on PATH")

    a, b = probe(args.a), probe(args.b)
    if not (a["has_audio"] or b["has_audio"]):
        sys.exit("error: neither track has audio - nothing to publish")

    for track, path in ((a, args.a), (b, args.b)):
        track["crop"] = detect_crop(path, track["duration"]) if track["has_video"] else None
        if track["crop"]:
            sys.stderr.write("removing letterbox from {}: {}\n".format(
                os.path.basename(path), track["crop"]))

    total = max(args.a_offset + a["duration"], args.b_offset + b["duration"])
    if total <= 0:
        sys.exit("error: could not determine a positive duration")

    os.makedirs(os.path.dirname(os.path.abspath(args.out)) or ".", exist_ok=True)
    tmp = tempfile.mkdtemp(prefix="itqan-render-")
    try:
        mask = os.path.join(tmp, "mask.png")
        ring_a = os.path.join(tmp, "ring_a.png")
        ring_b = os.path.join(tmp, "ring_b.png")
        make_circle_mask(mask, DIAMETER)
        make_ring(ring_a, DIAMETER, RING, GOLD)
        make_ring(ring_b, DIAMETER, RING, NAVY_LIGHT)

        # Mix both uplinks. normalize=0 preserves natural levels in a
        # conversation where only one person speaks at a time.
        audio_srcs = [i for i, t in enumerate((a, b)) if t["has_audio"]]
        if len(audio_srcs) == 2:
            amix = "[0:a][1:a]amix=inputs=2:duration=longest:normalize=0[amix]"
        else:
            amix = "[{}:a]anull[amix]".format(audio_srcs[0])
        # asplit because a filter output label may only be consumed once, and
        # the same mixed audio feeds both the video and the audio-only file.
        # loudnorm resamples internally and emits 96kHz; force it back to the
        # 48kHz every platform expects, so files are not needlessly large.
        norm = "anull" if args.no_loudnorm else "loudnorm=I=-16:TP=-1.5:LRA=11"
        chain = "[amix]" + norm + ",aresample=48000,asplit=2[aout_v][aout_a]"
        logo = logo_path()
        filt = (build_video_filter(a, b, total, args.fps, 5 if logo else None)
                + ";" + amix + ";" + chain)

        encoder = pick_encoder(args.encoder)
        quality = (["-cq", "23", "-preset", "p5"] if encoder == "h264_nvenc"
                   else ["-crf", "20", "-preset", "medium"])

        video_out = args.out + ".mp4"
        audio_out = args.out + ".m4a"
        dur = "{:.3f}".format(total)

        cmd = ["ffmpeg", "-y", "-v", "error", "-stats"]
        cmd += ["-itsoffset", str(args.a_offset), "-i", args.a]
        cmd += ["-itsoffset", str(args.b_offset), "-i", args.b]
        cmd += ["-i", mask, "-i", ring_a, "-i", ring_b]
        if logo:
            cmd += ["-i", logo]
        cmd += ["-filter_complex", filt]
        # Two outputs from one decode pass: square video, and clean audio.
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
