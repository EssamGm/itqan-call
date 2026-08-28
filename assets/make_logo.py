#!/usr/bin/env python3
"""
Rasterise the Etqan logo into PNGs the renderer can overlay.

Run once; the PNGs are committed alongside the source SVG. We rasterise rather
than draw text because ffmpeg's drawtext maps Arabic onto the deprecated
Presentation Forms block instead of using a font's GSUB shaping tables, so
letters whose forms the font doesn't duplicate there come out as .notdef boxes.
The official logo already has the wordmark converted to outlines, which
sidesteps shaping entirely.

The output is transparent. An earlier version baked in the dark surface colour,
which was invisible on a plain background but showed as a dark rectangle the
moment anything bright passed behind it - which is exactly what the speaking
bloom does. renderPM will not write alpha directly, so each element is rendered
white-on-black, read back as a mask, and painted through.
"""

import os
import re
import sys

from PIL import Image
from reportlab.graphics import renderPM
from svglib.svglib import svg2rlg

HERE = os.path.dirname(os.path.abspath(__file__))

GOLD_RETIRED = "#B8860B"   # superseded by the v1.0 unified gold
GOLD = (0xC9, 0xA2, 0x27)
NAVY = (0x14, 0x36, 0x5C)
REVERSED_INK = (0xF2, 0xF5, 0xF8)   # wordmark colour on a dark surface

# Scale via DPI rather than transforming the drawing. svglib converts the SVG
# to points (1px = 0.75pt), so scaling the drawing by hand overflows a canvas
# that was sized from the unscaled width and silently crops the wordmark.
DPI = 72 * 12

# The logo's viewBox, plus the clear space the guidelines require on every
# side: one gold-square height (X = 7 units).
VIEWBOX = (86.36, 31.80)
CLEAR = 7.0


def _prepare(svg_text, keep):
    """Recolour to white and keep only one element, so it can be read as a mask."""
    out = svg_text.replace(GOLD_RETIRED, "#FFFFFF").replace("#14365C", "#FFFFFF")

    if keep == "wordmark":
        out = re.sub(r'<rect id="etqan-accent"[^>]*/>', "", out)
    else:
        out = re.sub(r'<g id="etqan-wordmark".*?</g>', "", out, flags=re.S)

    w, h = VIEWBOX
    out = re.sub(r'\swidth="[^"]*"', "", out, count=1)
    out = re.sub(r'\sheight="[^"]*"', "", out, count=1)
    return out.replace(
        'viewBox="0 0 86.36 31.80"',
        'viewBox="{} {} {} {}"'.format(-CLEAR, -CLEAR, w + CLEAR * 2, h + CLEAR * 2),
        1,
    )


def _mask(svg_text, keep, tmp_path):
    """Render one element white-on-black and return it as a greyscale mask."""
    with open(tmp_path, "w", encoding="utf-8") as fh:
        fh.write(_prepare(svg_text, keep))
    try:
        drawing = svg2rlg(tmp_path)
        if drawing is None:
            sys.exit("error: svglib could not parse " + tmp_path)
        png = tmp_path + ".png"
        renderPM.drawToFile(drawing, png, fmt="PNG", bg=0x000000, dpi=DPI)
        with Image.open(png) as im:
            mask = im.convert("L")
        os.remove(png)
        return mask
    finally:
        os.remove(tmp_path)


def build(svg_text, path, ink):
    """Compose a transparent logo: wordmark in `ink`, accent square in gold."""
    word = _mask(svg_text, "wordmark", path + ".w.svg")
    square = _mask(svg_text, "accent", path + ".a.svg")

    out = Image.new("RGBA", word.size, (0, 0, 0, 0))
    for mask, colour in ((word, ink), (square, GOLD)):
        if mask.size != out.size:
            mask = mask.resize(out.size, Image.LANCZOS)
        layer = Image.new("RGBA", out.size, colour + (255,))
        layer.putalpha(mask)
        out.alpha_composite(layer)

    out.save(path)
    print("wrote " + os.path.basename(path))


def main():
    src = os.path.join(HERE, "etqan-logo.svg")
    if not os.path.isfile(src):
        sys.exit("error: missing " + src)
    with open(src, "r", encoding="utf-8") as fh:
        svg_text = fh.read()

    build(svg_text, os.path.join(HERE, "logo-reversed.png"), REVERSED_INK)
    build(svg_text, os.path.join(HERE, "logo-navy.png"), NAVY)


if __name__ == "__main__":
    main()
