#!/usr/bin/env python3
"""
Render Arabic (or Latin) text to a PNG, correctly shaped.

Why this exists: ffmpeg's drawtext maps Arabic onto the deprecated Unicode
Presentation Forms block, and modern fonts only partly populate it - Cairo
carries 89 of ~140 forms, so names come out with .notdef boxes. Pillow can't
help either; its shaping needs libraqm, which the Windows wheels omit.

So we do it properly: HarfBuzz shapes the string against the real font (using
its GSUB tables, the way a browser does), we pull each glyph's outline as an
SVG path, and rasterise the result through the same svglib path the logo uses.
That keeps brand-correct Cairo 900 with no presentation-forms dependency.
"""

import os

import uharfbuzz as hb
from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.ttLib import TTFont
from reportlab.graphics import renderPM
from svglib.svglib import svg2rlg

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_FONT = os.path.join(os.path.dirname(HERE), "assets", "fonts", "Cairo-Black.ttf")

_CACHE = {}


def _font_pair(font_path):
    """HarfBuzz font for shaping, fontTools font for outlines. Cached."""
    if font_path not in _CACHE:
        with open(font_path, "rb") as fh:
            data = fh.read()
        face = hb.Face(data)
        hb_font = hb.Font(face)
        tt = TTFont(font_path)
        _CACHE[font_path] = (hb_font, tt, face.upem)
    return _CACHE[font_path]


def text_to_svg(text, font_path=DEFAULT_FONT, size=100, color="#F2F5F8", pad=0.15):
    """Shape `text` and return a standalone SVG string, sized in px."""
    hb_font, tt, upem = _font_pair(font_path)
    glyphset = tt.getGlyphSet()
    order = tt.getGlyphOrder()

    buf = hb.Buffer()
    buf.add_str(text)
    buf.guess_segment_properties()   # picks RTL + Arabic script automatically
    hb.shape(hb_font, buf)

    scale = size / float(upem)
    paths = []
    x = 0.0
    for info, pos in zip(buf.glyph_infos, buf.glyph_positions):
        name = order[info.codepoint]
        pen = SVGPathPen(glyphset)
        glyphset[name].draw(pen)
        d = pen.getCommands()
        if d:
            # Flip Y: font space is y-up, SVG is y-down.
            paths.append(
                '<path d="{}" transform="translate({:.2f},{:.2f}) scale({:.5f},{:.5f})"/>'
                .format(d, (x + pos.x_offset) * scale, size, scale, -scale)
            )
        x += pos.x_advance

    width = max(1.0, x * scale)
    padding = size * pad
    # Generous vertical box: Arabic ascenders and the hamza descender both
    # sit outside the nominal em, and clipping them looks broken.
    top, bottom = size * 0.42, size * 0.34
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" '
        'viewBox="{:.2f} {:.2f} {:.2f} {:.2f}">'
        '<g fill="{}">{}</g></svg>'
    ).format(
        -padding, -top, width + padding * 2, size + top + bottom,
        color, "".join(paths),
    )


def render_text_png(text, out_path, font_path=DEFAULT_FONT, size=100,
                    color="#F2F5F8", bg=0x0B1A2A, dpi_scale=3):
    """Shape and rasterise `text` onto a solid background. Returns (w, h)."""
    svg = text_to_svg(text, font_path=font_path, size=size, color=color)
    tmp = out_path + ".tmp.svg"
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(svg)
    try:
        drawing = svg2rlg(tmp)
        if drawing is None:
            raise RuntimeError("could not rasterise text")
        renderPM.drawToFile(drawing, out_path, fmt="PNG", bg=bg, dpi=72 * dpi_scale)
    finally:
        os.remove(tmp)

    from PIL import Image
    with Image.open(out_path) as im:
        return im.size
