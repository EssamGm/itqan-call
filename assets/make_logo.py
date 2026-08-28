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
import re
import sys

from reportlab.graphics import renderPM
from svglib.svglib import svg2rlg

HERE = os.path.dirname(os.path.abspath(__file__))

GOLD_RETIRED = "#B8860B"   # superseded by the v1.0 unified gold
GOLD = "#C9A227"
NAVY = "#14365C"
REVERSED_INK = "#F2F5F8"   # wordmark colour on a dark surface
SURFACE = 0x0B1A2A

# Scale via DPI rather than transforming the drawing. svglib converts the SVG
# to points (1px = 0.75pt), so scaling the drawing by hand overflows a canvas
# that was sized from the unscaled width and silently crops the wordmark.
DPI = 72 * 12  # ~1036px wide, ample for a 1080 canvas


# The logo's viewBox, plus the clear space the guidelines require on every
# side: one gold-square height (X = 7 units).
VIEWBOX = (86.36, 31.80)
CLEAR = 7.0


def build(svg_text, path, ink):
    """Write a recoloured SVG variant, rasterise it, then drop the temp SVG."""
    variant = svg_text.replace(GOLD_RETIRED, GOLD)
    if ink != NAVY:
        variant = variant.replace(NAVY, ink)

    # Drop width/height and widen the viewBox. svglib reads width/height as
    # points but the viewBox as user units - a 1.333x mismatch that silently
    # crops the wordmark. Leaving only a padded viewBox removes the ambiguity
    # and bakes in the mandated clear space at the same time.
    w, h = VIEWBOX
    variant = re.sub(r'\swidth="[^"]*"', "", variant, count=1)
    variant = re.sub(r'\sheight="[^"]*"', "", variant, count=1)
    variant = variant.replace(
        'viewBox="0 0 86.36 31.80"',
        'viewBox="{} {} {} {}"'.format(
            -CLEAR, -CLEAR, w + CLEAR * 2, h + CLEAR * 2),
        1,
    )

    tmp_svg = path + ".tmp.svg"
    with open(tmp_svg, "w", encoding="utf-8") as fh:
        fh.write(variant)
    try:
        drawing = svg2rlg(tmp_svg)
        if drawing is None:
            sys.exit("error: svglib could not parse " + tmp_svg)
        renderPM.drawToFile(drawing, path, fmt="PNG", bg=SURFACE, dpi=DPI)
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
