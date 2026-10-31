#!/usr/bin/env python3
"""
YouTube thumbnail for a podcast episode.

Two overlapping circles - the host's photo and the guest's name - the way
YouTube shows two channels on a shared video, so the frame says "a
conversation" before anyone reads a word. Then the episode line, large enough
to survive being shrunk to a phone's width, and the brand lockup.

    python thumbnail.py --guest "أبو غازي" \\
        --line1 "أب لطفلين" --line2 "يتعلم الإنجليزية" \\
        --tag "تدريب.. مو تعليم" --out C:/Itqan/final/thumb.png

Everything is drawn through the same HarfBuzz path as the video captions, so
Arabic shapes correctly. ffmpeg's drawtext does not, and never will here.
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from arabic_text import render_text_png  # noqa: E402
from bubble_render import SURFACE, GOLD, NAVY_LIGHT, TEXT, logo_path  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FONTS = os.path.join(ROOT, "assets", "fonts")
DISPLAY = os.path.join(FONTS, "Cairo-Black.ttf")       # headline: has to hit at 200 px wide
SUB = os.path.join(FONTS, "Cairo-Bold.ttf")
NAME = os.path.join(FONTS, "IBMPlexSansArabic-SemiBold.ttf")  # matches the video's bubbles

W, H = 1280, 720
DIAMETER = 330
RING = 9
OVERLAP = 96
HOST_CX, CY = 318, 372
GUEST_CX = HOST_CX + DIAMETER - OVERLAP
RIGHT_EDGE = 1212           # Arabic text is right-aligned to this
DISC_FILL = "#122943"


def _rgb(hexstr):
    h = hexstr.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def text_layer(text, font, size, colour, tmp, tag):
    """Shape text, read it back as a mask, paint the colour through. Cropped to ink."""
    from PIL import Image
    p = os.path.join(tmp, "t_{}.png".format(tag))
    render_text_png(text, p, font_path=font, size=size, color="#FFFFFF", bg=0x000000)
    with Image.open(p) as raw:
        alpha = raw.convert("L")
    alpha = alpha.crop(alpha.getbbox())
    layer = Image.new("RGBA", alpha.size, _rgb(colour) + (255,))
    layer.putalpha(alpha)
    return layer


def circle_mask(d, feather=1.2):
    from PIL import Image, ImageDraw, ImageFilter
    s = 4
    m = Image.new("L", (d * s, d * s), 0)
    ImageDraw.Draw(m).ellipse((0, 0, d * s - 1, d * s - 1), fill=255)
    return m.resize((d, d), Image.LANCZOS).filter(ImageFilter.GaussianBlur(feather))


def ringed(disc, ring_colour):
    """A disc with its ring, on a transparent square."""
    from PIL import Image, ImageDraw
    d = DIAMETER + 2 * RING
    s = 4
    ring = Image.new("RGBA", (d * s, d * s), (0, 0, 0, 0))
    ImageDraw.Draw(ring).ellipse((0, 0, d * s - 1, d * s - 1), fill=_rgb(ring_colour) + (255,))
    ring = ring.resize((d, d), Image.LANCZOS)
    ring.paste(disc, (RING, RING), disc)
    return ring


def photo_disc(path):
    from PIL import Image, ImageOps
    with Image.open(path) as im:
        im = ImageOps.exif_transpose(im).convert("RGB")
    im = ImageOps.fit(im, (DIAMETER, DIAMETER), Image.LANCZOS, centering=(0.5, 0.42))
    disc = im.convert("RGBA")
    disc.putalpha(circle_mask(DIAMETER))
    return ringed(disc, GOLD)


def name_disc(label, tmp):
    from PIL import Image
    disc = Image.new("RGBA", (DIAMETER, DIAMETER), _rgb(DISC_FILL) + (255,))
    disc.putalpha(circle_mask(DIAMETER))
    t = text_layer(label, NAME, 150, TEXT, tmp, "guest")
    # The host's photo sits in front and covers this disc's left edge by
    # OVERLAP, so the name is centred on the part that stays visible - not on
    # the disc - or its first letters vanish under the photo.
    visible_w = DIAMETER - OVERLAP
    max_w = int(visible_w * 0.80)
    if t.width > max_w:
        t = t.resize((max_w, int(t.height * max_w / t.width)), Image.LANCZOS)
    x = OVERLAP + (visible_w - t.width) // 2
    disc.paste(t, (x, (DIAMETER - t.height) // 2), t)
    return ringed(disc, NAVY_LIGHT)


def bloom(colour, radius, sigma):
    """The same soft halo the video uses behind a speaking bubble."""
    from PIL import Image, ImageDraw, ImageFilter
    size = int(radius * 2 + sigma * 6)
    m = Image.new("L", (size, size), 0)
    c = size // 2
    ImageDraw.Draw(m).ellipse((c - radius, c - radius, c + radius, c + radius), fill=255)
    m = m.filter(ImageFilter.GaussianBlur(sigma))
    layer = Image.new("RGBA", (size, size), _rgb(colour) + (255,))
    layer.putalpha(m.point(lambda v: int(v * 0.55)))
    return layer


MUTED = "#B9C1CC"        # the ad's grey, lifted for a dark ground


def pitch_block(tmp):
    """
    The pitch exactly as the Snapchat ad sets it, in the ad's own proportions:

        تدريب تعلّم اللغة
        مو تعليم، تدريب        <- last word heavier, double gold rule under it

    Rendered as three pieces so the emphasised word can carry its own weight,
    size and underline while the rest stays muted.
    """
    from PIL import Image, ImageDraw
    l1 = text_layer("تدريب تعلّم اللغة", NAME, 100, MUTED, tmp, "p1")
    l2a = text_layer("مو تعليم،", NAME, 100, MUTED, tmp, "p2a")
    l2b = text_layer("تدريب", NAME, 116, "#FFFFFF", tmp, "p2b")      # 31/27 of the ad
    # scale the ad's 27px line to the thumbnail: about 1.35x
    def at(layer, h):
        return layer.resize((int(layer.width * h / layer.height), h), Image.LANCZOS)
    l1 = at(l1, 50); l2a = at(l2a, 44); l2b = at(l2b, 60)

    gap_w = 16
    rule_gap, rule_w = 6, 4
    w = max(l1.width, l2a.width + gap_w + l2b.width)
    h = l1.height + 16 + max(l2a.height, l2b.height) + 6 + rule_w * 2 + rule_gap
    out = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    # line 1, right-aligned
    out.alpha_composite(l1, (w - l1.width, 0))
    # line 2: "مو تعليم،" first (so on the right), then "تدريب" to its left
    y2 = l1.height + 16
    base = y2 + max(l2a.height, l2b.height)
    out.alpha_composite(l2a, (w - l2a.width, base - l2a.height))
    xb = w - l2a.width - gap_w - l2b.width
    out.alpha_composite(l2b, (xb, base - l2b.height))
    # the double rule under that word only
    d = ImageDraw.Draw(out)
    gold = _rgb(GOLD) + (255,)
    y = base + 6
    d.rectangle((xb, y, xb + l2b.width, y + rule_w - 1), fill=gold)
    d.rectangle((xb, y + rule_w + rule_gap, xb + l2b.width, y + rule_w * 2 + rule_gap - 1), fill=gold)
    return out


def episode_badge(number, tmp, d=96):
    """The episode number in a small disc where the two circles meet."""
    from PIL import Image, ImageDraw
    s = 4
    S = d * s
    im = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    dr = ImageDraw.Draw(im)
    dr.ellipse((0, 0, S - 1, S - 1), fill=_rgb(GOLD) + (255,))
    r = 4 * s
    dr.ellipse((r, r, S - 1 - r, S - 1 - r), fill=_rgb(DISC_FILL) + (255,))
    im = im.resize((d, d), Image.LANCZOS)
    t = text_layer(str(number), DISPLAY, 150, GOLD, tmp, "ep")
    th = int(d * 0.50)
    t = t.resize((max(1, int(t.width * th / t.height)), th), Image.LANCZOS)
    im.alpha_composite(t, ((d - t.width) // 2, (d - t.height) // 2))
    return im


def arrow(p0, p2, ctrl, width=7, head=32):
    """
    A curved annotation arrow, gold, on a transparent full-frame layer.

    The body stops at the base of the head rather than running to the tip: a
    thick line has a rounded end, and drawn all the way it pokes through the
    point of the triangle and blunts it. So the curve is cut `head` back from
    the tip along its own tangent, and the head is drawn from that base.
    """
    from PIL import Image, ImageDraw
    import math
    s = 4
    im = Image.new("RGBA", (W * s, H * s), (0, 0, 0, 0))
    dr = ImageDraw.Draw(im)
    gold = _rgb(GOLD) + (255,)
    pts = []
    for i in range(61):
        t = i / 60
        x = (1 - t) ** 2 * p0[0] + 2 * (1 - t) * t * ctrl[0] + t ** 2 * p2[0]
        y = (1 - t) ** 2 * p0[1] + 2 * (1 - t) * t * ctrl[1] + t ** 2 * p2[1]
        pts.append((x * s, y * s))
    tip = pts[-1]
    (x1, y1) = pts[-4]
    ang = math.atan2(tip[1] - y1, tip[0] - x1)
    hl = head * s
    base = (tip[0] - hl * math.cos(ang), tip[1] - hl * math.sin(ang))
    # The body runs a third of the way into the head, so the head's fill
    # covers the join - a bending curve meets a straight head at a slight
    # angle, and left exposed that reads as a kink.
    inset = (tip[0] - hl * 0.66 * math.cos(ang), tip[1] - hl * 0.66 * math.sin(ang))
    body = [q for q in pts if math.hypot(q[0] - tip[0], q[1] - tip[1]) > hl] + [base, inset]
    if len(body) >= 2:
        dr.line(body, fill=gold, width=width * s, joint="curve")
    wing = hl * 0.58
    left = (base[0] - wing * math.sin(ang), base[1] + wing * math.cos(ang))
    right = (base[0] + wing * math.sin(ang), base[1] - wing * math.cos(ang))
    dr.polygon([tip, left, right], fill=gold)
    return im.resize((W, H), Image.LANCZOS)


def lockup(tmp):
    """'بودكاست إتقان' - the video's own lockup, built the same way."""
    from PIL import Image
    with Image.open(logo_path()) as lg:
        mark = lg.convert("RGBA")
    l, t, r, b = mark.getchannel("A").getbbox()
    ink_h = b - t
    word = text_layer("بودكاست", NAME, 300, "#FFFFFF", tmp, "lockup")
    th = int(ink_h * 1.00)
    word = word.resize((int(word.width * th / word.height), th), Image.LANCZOS)
    gap = int(ink_h * 0.30)
    canvas = Image.new("RGBA", (r + gap + word.width + l, mark.height), (0, 0, 0, 0))
    canvas.paste(mark, (0, 0), mark)
    canvas.paste(word, (r + gap, t + (ink_h - word.height) // 2), word)
    return canvas.crop(canvas.getchannel("A").getbbox())


def build(a):
    import tempfile
    from PIL import Image
    tmp = tempfile.mkdtemp(prefix="itqan-thumb-")

    img = Image.new("RGBA", (W, H), _rgb(SURFACE) + (255,))

    # Glow behind the host, as if mid-sentence.
    g = bloom(GOLD, DIAMETER // 2 + 40, 70)
    img.alpha_composite(g, (HOST_CX - g.width // 2, CY - g.height // 2))

    # Guest behind, host in front - the host owns the frame.
    guest = name_disc(a.guest, tmp)
    host = photo_disc(a.photo)
    img.alpha_composite(guest, (GUEST_CX - guest.width // 2, CY - guest.height // 2))
    img.alpha_composite(host, (HOST_CX - host.width // 2, CY - host.height // 2))

    # The episode number where the two circles meet.
    if a.episode:
        ep = episode_badge(a.episode, tmp)
        seam_x = (HOST_CX + GUEST_CX) // 2
        img.alpha_composite(ep, (seam_x - ep.width // 2, CY + DIAMETER // 2 - ep.height // 2 - 6))

    # Three things on the frame, each with a gold arrow to what it is: the
    # host, the guest, the programme. A reader who has never heard of any of
    # them gets all three from one glance. Each annotation owns its own region
    # - guest top right, programme bottom right, host top left - so nothing
    # has to be read around anything else.
    col_left = GUEST_CX + DIAMETER // 2 + 60
    text_w = RIGHT_EDGE - col_left

    # 1. The guest: the big line, top right, arrow from the circle's shoulder
    #    up to its left end.
    y = 58
    layers = []
    for i, line in enumerate((a.line1, a.line2)):
        if not line:
            continue
        t = text_layer(line, DISPLAY, 150, "#FFFFFF", tmp, "l{}".format(i))
        if t.width > text_w:
            t = t.resize((text_w, int(t.height * text_w / t.width)), Image.LANCZOS)
        layers.append((t, RIGHT_EDGE - t.width, y))
        y += t.height + 16
    for t, x, yy in layers:
        img.alpha_composite(t, (x, yy))
    if layers:
        left_x = min(x for _, x, _ in layers)
        mid_y = (layers[0][2] + layers[-1][2] + layers[-1][0].height) // 2
        p0 = (GUEST_CX + int(DIAMETER * 0.36), CY - int(DIAMETER * 0.36))
        p2 = (left_x - 22, mid_y + 10)
        img.alpha_composite(arrow(p0, p2, (p0[0] + 24, p2[1] + 46)))

    # 2. The programme: brand, then the pitch under it as its explanation,
    #    set the way the ad sets it, large enough to actually be read.
    pb = pitch_block(tmp)
    lk = lockup(tmp)
    lk = lk.resize((int(lk.width * 66 / lk.height), 66), Image.LANCZOS)
    pb_y = H - 44 - pb.height
    lk_y = pb_y - 104 - lk.height
    lk_x, pb_x = RIGHT_EDGE - lk.width, RIGHT_EDGE - pb.width
    img.alpha_composite(lk, (lk_x, lk_y))
    img.alpha_composite(pb, (pb_x, pb_y))
    mark_cx = lk_x + int(lk.width * 0.27)        # the wordmark is the lockup's left part
    p0 = (mark_cx - 10, lk_y + lk.height + 8)
    p2 = (pb_x + int(pb.width * 0.30), pb_y - 12)
    img.alpha_composite(arrow(p0, p2, (p0[0] - 40, (p0[1] + p2[1]) // 2 + 14)))

    # 3. The host: the word above the photo, arrow straight down onto it.
    if a.host_label:
        hl = text_layer(a.host_label, SUB, 150, GOLD, tmp, "host")
        hl = hl.resize((int(hl.width * 60 / hl.height), 60), Image.LANCZOS)
        hx = HOST_CX - DIAMETER // 2 - 70
        hy = 50
        img.alpha_composite(hl, (hx, hy))
        p0 = (HOST_CX - int(DIAMETER * 0.18), CY - int(DIAMETER * 0.47))
        p2 = (hx + hl.width // 2 + 10, hy + hl.height + 14)
        img.alpha_composite(arrow(p0, p2, (p0[0] + 10, p2[1] + 40)))

    out = a.out
    img.convert("RGB").save(out, quality=95)
    print("wrote {}  ({}x{})".format(out, W, H))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--call", default="",
                    help="a call folder: guest from meta.json, lines and episode from "
                         "package.md, output thumb.png beside them")
    ap.add_argument("--photo", default=os.path.join(ROOT, "assets", "essam.jpg"))
    ap.add_argument("--guest", default="", help="name shown in the second circle")
    ap.add_argument("--line1", default="")
    ap.add_argument("--line2", default="")
    ap.add_argument("--tag", default="", help="gold line under the headline")
    ap.add_argument("--episode", type=int, default=0, help="episode number in the badge; 0 for none")
    ap.add_argument("--host-label", default="المدرب", help="word above the host photo; empty to omit")
    ap.add_argument("--out", default="")
    a = ap.parse_args()

    if a.call:
        import callfolder as cf
        folder = os.path.abspath(a.call)
        meta = cf.read_meta(folder)
        pkg = cf.read_package(folder)
        if pkg is None:
            sys.exit("thumbnail: no package.md in the folder - run PACKAGE first")
        a.guest = a.guest or meta.get("guest", "")
        a.line1 = a.line1 or pkg.get("thumb_line1", "")
        a.line2 = a.line2 or pkg.get("thumb_line2", "")
        # The number comes from the ledger via meta.json; package.md only
        # copies it, and may honestly say TODO if nothing was assigned yet.
        ep = meta.get("episode") or pkg.get("episode")
        a.episode = a.episode or (int(ep) if str(ep).isdigit() else 0)
        a.out = a.out or cf.path(folder, cf.THUMB)
        if not a.line1:
            sys.exit("thumbnail: package.md has no thumb_line1")
    elif not (a.guest and a.line1 and a.out):
        sys.exit("thumbnail: give --call <folder>, or --guest, --line1 and --out")
    build(a)


if __name__ == "__main__":
    main()
