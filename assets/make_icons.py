#!/usr/bin/env python3
"""
Generate the app icons.

Per the brand guidelines the icon is the gold square alone on the dark navy
surface, rounded ~22%. The name never appears in the icon.

Two shapes are produced. The rounded "any" icons are used where the platform
draws the icon as-is; the full-bleed "maskable" ones let Android apply its own
mask without clipping the square, which is why the square sits well inside the
safe area there.
"""

import os

from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(os.path.dirname(HERE), "web", "icons")

SURFACE = (0x0B, 0x1A, 0x2A, 255)
GOLD = (0xC9, 0xA2, 0x27, 255)

ROUND_RATIO = 0.22       # brand: rounded ~22%
SQUARE_RATIO = 0.34      # gold square as a share of the icon edge
MASKABLE_SQUARE = 0.26   # smaller, to survive Android's circular crop

SS = 4  # supersample factor, for clean rounded corners and edges


def icon(size, maskable=False):
    s = size * SS
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    if maskable:
        d.rectangle([0, 0, s, s], fill=SURFACE)
    else:
        d.rounded_rectangle([0, 0, s - 1, s - 1], radius=int(s * ROUND_RATIO),
                            fill=SURFACE)

    q = int(s * (MASKABLE_SQUARE if maskable else SQUARE_RATIO))
    off = (s - q) // 2
    d.rectangle([off, off, off + q, off + q], fill=GOLD)

    return img.resize((size, size), Image.LANCZOS)


def main():
    os.makedirs(OUT, exist_ok=True)
    for size in (32, 180, 192, 512):
        p = os.path.join(OUT, "icon-{}.png".format(size))
        icon(size).save(p)
        print("wrote", os.path.basename(p))
    for size in (192, 512):
        p = os.path.join(OUT, "maskable-{}.png".format(size))
        icon(size, maskable=True).save(p)
        print("wrote", os.path.basename(p))


if __name__ == "__main__":
    main()
