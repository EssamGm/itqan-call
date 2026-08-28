#!/usr/bin/env python3
"""
Draw the caption panel.

Both speakers' words appear in the same place, told apart by colour rather than
position. Captions that alternate left and right make the eye jump across the
frame every time the speaker changes, which is tiring over half an hour; one
fixed panel lets you read without moving.

Text is shaped through the same HarfBuzz path as the bubble names. Subtitle
renderers were tried first and dropped the lam-alef ligature in both brand
fonts, which is the sort of error that only shows up in the finished file.
"""

import os

from PIL import Image, ImageDraw

from arabic_text import render_text_png

PANEL_W = 820
PANEL_H = 132
RADIUS = 16

# White panel. Being opaque is the point as much as the colour: it blocks the
# speaking bloom, so the words stay readable however loud the moment gets.
PANEL_FILL = (255, 255, 255, 250)
PANEL_EDGE = (226, 230, 236, 255)

# Speaker colours, measured against white rather than chosen by eye. The brand
# gold reaches only 2.4:1 on white, which is unreadable; these clear the 4.5:1
# floor for body text while still reading as gold and blue.
COACH_INK = (0x8F, 0x6A, 0x08)      # 5.0:1
TRAINEE_INK = (0x1F, 0x4E, 0x79)    # 8.7:1

FONT_SIZE = 34
LINE_GAP = 8
MAX_LINES = 2


def _text_image(text, size, colour, tmp_dir, tag):
    """Shaped text as an RGBA image, painted in `colour` through its own alpha."""
    png = os.path.join(tmp_dir, "cap_text_{}.png".format(tag))
    render_text_png(text, png, size=size, color="#FFFFFF", bg=0x000000)
    with Image.open(png) as raw:
        alpha = raw.convert("L")
    ink = Image.new("RGBA", alpha.size, colour + (255,))
    ink.putalpha(alpha)
    return ink


def _wrap(text, max_chars):
    """Split into at most MAX_LINES, breaking on words."""
    words = text.split()
    if not words:
        return []
    lines, cur = [], ""
    for w in words:
        trial = (cur + " " + w).strip()
        if len(trial) <= max_chars or not cur:
            cur = trial
        else:
            lines.append(cur)
            cur = w
            if len(lines) == MAX_LINES:
                break
    if cur and len(lines) < MAX_LINES:
        lines.append(cur)
    # Anything that would not fit is dropped rather than shrunk to nothing;
    # these are captions for atmosphere, not a transcript of record.
    return lines[:MAX_LINES]


def render_caption(text, colour, out_path, tmp_dir, tag):
    """Draw one caption panel to `out_path`. Returns True if anything was drawn."""
    panel = Image.new("RGBA", (PANEL_W, PANEL_H), (0, 0, 0, 0))
    d = ImageDraw.Draw(panel)
    d.rounded_rectangle([0, 0, PANEL_W - 1, PANEL_H - 1], radius=RADIUS,
                        fill=PANEL_FILL, outline=PANEL_EDGE, width=2)

    lines = _wrap(text, 52)
    if not lines:
        return False

    imgs = []
    for i, line in enumerate(lines):
        img = _text_image(line, FONT_SIZE, colour, tmp_dir, "{}_{}".format(tag, i))
        # Shrink a line that still overruns rather than letting it clip.
        if img.width > PANEL_W - 48:
            scale = (PANEL_W - 48) / img.width
            img = img.resize((int(img.width * scale), max(1, int(img.height * scale))),
                             Image.LANCZOS)
        imgs.append(img)

    total_h = sum(i.height for i in imgs) + LINE_GAP * (len(imgs) - 1)
    y = (PANEL_H - total_h) // 2
    for img in imgs:
        panel.alpha_composite(img, ((PANEL_W - img.width) // 2, y))
        y += img.height + LINE_GAP

    panel.save(out_path)
    return True


def blank_panel(out_path):
    """A fully transparent frame, so the panel disappears between lines."""
    Image.new("RGBA", (PANEL_W, PANEL_H), (0, 0, 0, 0)).save(out_path)


def build_caption_track(segments, colours, tmp_dir, total, fps):
    """
    Turn caption segments into one video that can be overlaid in a single pass.

    A separate overlay per line would mean hundreds of filters in one graph;
    assembling them into a track first keeps the render to one overlay however
    long the conversation runs.
    """
    blank = os.path.join(tmp_dir, "cap_blank.png")
    blank_panel(blank)

    entries = []   # (image path, duration seconds)
    cursor = 0.0
    for n, seg in enumerate(segments):
        if seg["start"] > cursor + 0.04:
            entries.append((blank, seg["start"] - cursor))
        png = os.path.join(tmp_dir, "cap_{:05d}.png".format(n))
        if render_caption(seg["text"], colours[seg["role"]], png, tmp_dir, n):
            entries.append((png, max(0.2, seg["end"] - seg["start"])))
        else:
            entries.append((blank, max(0.2, seg["end"] - seg["start"])))
        cursor = seg["end"]

    if cursor < total:
        entries.append((blank, total - cursor))

    list_path = os.path.join(tmp_dir, "captions.txt")
    with open(list_path, "w", encoding="utf-8") as fh:
        for path, dur in entries:
            fh.write("file '{}'\n".format(path.replace("\\", "/")))
            fh.write("duration {:.3f}\n".format(dur))
        # concat needs the final image repeated for its duration to register.
        if entries:
            fh.write("file '{}'\n".format(entries[-1][0].replace("\\", "/")))
    return list_path
