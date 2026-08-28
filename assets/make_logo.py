#!/usr/bin/env python3
"""
Rasterise the Etqan logo into PNGs the renderer can overlay.

Run once; the PNGs are committed alongside the source SVG. We rasterise rather
than draw text because ffmpeg's drawtext maps Arabic onto the deprecated
Presentation Forms block instead of using a font's GSUB shaping tables, so
letters whose forms the font doesn't duplicate there come out as .notdef boxes.
The official logo already has the wordmark converted to outlines, which
sidesteps shaping entirely.

The output is rendered onto the exact dark surface colour rather than onto
transparency: the renderer only ever places it on that same surface, so it
composites invisibly, and this avoids the alpha fringing renderPM produces.
"""

import os
import sys

from reportlab.graphics import renderPM
from svglib.svglib import svg2rlg

HERE = os.path.dirname(os.path.abspath(__file__))

GOLD_RETIRED = "#B8860B"   # superseded by the v1.0 unified gold
GOLD = "#C9A227"
NAVY = "#14365C"
REVERSED_INK = "#F2F5F8"   # wordmark colour on a dark surface
SURFACE = 0x0B1A2A

SCALE = 8  # 86.36 x 31.80 viewBox -> ~691 x 254 px, ample for a 1080 canvas


def build(svg_text, path, ink):
    """Write a recoloured SVG variant, rasterise it, then drop the temp SVG."""
    variant = svg_text.replace(GOLD_RETIRED, GOLD)
    if ink != NAVY:
        variant = variant.replace(NAVY, ink)

    tmp_svg = path + ".tmp.svg"
    with open(tmp_svg, "w", encoding="utf-8") as fh:
        fh.write(variant)
    try:
        drawing = svg2rlg(tmp_svg)
        if drawing is None:
            sys.exit("error: svglib could not parse " + tmp_svg)
        drawing.scale(SCALE, SCALE)
        drawing.width *= SCALE
        drawing.height *= SCALE
        renderPM.drawToFile(drawing, path, fmt="PNG", bg=SURFACE)
    finally:
        os.remove(tmp_svg)
    print("wrote " + os.path.basename(path))


def main():
    src = os.path.join(HERE, "etqan-logo.svg")
    if not os.path.isfile(src):
        sys.exit("error: missing " + src)
    with open(src, "r", encoding="utf-8") as fh:
        svg_text = fh.read()

    # Reversed variant is what the dark-surface video actually uses.
    build(svg_text, os.path.join(HERE, "logo-reversed.png"), REVERSED_INK)
    build(svg_text, os.path.join(HERE, "logo-navy.png"), NAVY)


if __name__ == "__main__":
    main()
