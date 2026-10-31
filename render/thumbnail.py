#!/usr/bin/env python3
"""
YouTube thumbnail for an إتقان episode, in one of three formats.

Everything that says "this channel" — palette, type, the gold arrow, the ring
and bloom, the episode badge, the lockup and the pitch block, and the geometry
of the right-hand column — lives in `brand.py` and is identical in all three.
This file owns only the *subject zone* on the left, which is what tells a
viewer what kind of episode they are about to watch.

    interview   two discs: the host's photo, and the guest's name behind it
    qa          one disc: the host's photo, in the interview's exact position;
                no arrow to the headline and no بودكاست on the mark, so the
                whole right side belongs to the question
    idea        one disc: the host's photo, enlarged and centred on the pair

The rule is the same in each case: **the second disc is the other party in the
conversation.** A guest in an interview; nobody, when Essam answers questions
or works an idea out alone. Two discs therefore always means someone else is in
this episode, and a viewer is never misled by it.

The badge is drawn only when --episode is given, so a standalone video simply
omits it and nothing else about the frame changes.

    python thumbnail.py --format interview --guest "أبو غازي" \\
        --line1 "أب لطفلين" --line2 "يتعلم الإنجليزية" \\
        --episode 1 --out C:/Itqan/final/thumb.png

    python thumbnail.py --format qa --line1 "..." --line2 "..." --out ...
    python thumbnail.py --format idea --line1 "..." --line2 "..." --out ...

Everything is drawn through the same HarfBuzz path as the video captions, so
Arabic shapes correctly. ffmpeg's drawtext does not, and never will here.
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import brand as B  # noqa: E402
from bubble_render import GOLD  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

FORMATS = ("interview", "qa", "idea")

# What each format does with the shared furniture. The subject zone is drawn in
# `subject_zone`; these are the two decisions that live outside it.
#
#   headline_arrow  interview and idea point at the episode line from the disc.
#                   qa does not: the whole right side is the question, and an
#                   arrow to it only says "read the biggest thing on the frame".
#   lockup_word     qa is not a podcast episode, so the mark carries no word.
#   programme       "stacked" is the podcast lockup with the pitch beneath it and
#                   an arrow between. "inline" is the bare mark in the corner
#                   with the pitch on one line beside it, as its definition.
SPEC = {
    "interview": {"headline_arrow": True,  "lockup_word": "بودكاست", "programme": "stacked"},
    "qa":        {"headline_arrow": False, "lockup_word": "",        "programme": "inline"},
    "idea":      {"headline_arrow": True,  "lockup_word": "بودكاست", "programme": "stacked"},
}

# Two-disc layouts. The pair spans 153..717; its centre, 435, is where the
# single disc of the `idea` format goes, so the frame's balance does not shift
# between formats.
HOST_CX = 318
SECOND_CX = HOST_CX + B.DIAMETER - B.OVERLAP     # 552
PAIR_CX = (HOST_CX + SECOND_CX) // 2             # 435

# One-disc layout. Larger, because a single 330 disc leaves the left third
# looking empty next to a two-disc frame.
SOLO_D = 400
SOLO_CX = PAIR_CX


def _paste(img, layer, cx, cy):
    img.alpha_composite(layer, (cx - layer.width // 2, cy - layer.height // 2))


def subject_zone(img, a, tmp):
    """
    Draw the left-hand subject zone for this format.

    Returns (host_cx, host_d, right_cx, right_d, badge_centre) — what the brand
    layer needs to aim the host label, the headline arrow and the badge.
    """
    import math

    if a.format == "idea":
        d = SOLO_D
        g = B.bloom(GOLD, d // 2 + 40, 70)
        _paste(img, g, SOLO_CX, B.CY)
        _paste(img, B.photo_disc(a.photo, d), SOLO_CX, B.CY)
        # The badge rides the ring at its lower right, where it meets nothing.
        r = d / 2 + B.RING
        badge = (int(SOLO_CX + r * math.cos(math.pi / 4)),
                 int(B.CY + r * math.sin(math.pi / 4)) - 6)
        return SOLO_CX, d, SOLO_CX, d, badge

    d = B.DIAMETER
    g = B.bloom(GOLD, d // 2 + 40, 70)
    _paste(img, g, HOST_CX, B.CY)

    if a.format == "qa":
        # Nobody behind him: a question has no second face. The disc keeps the
        # interview's exact position and size, so on the channel page the two
        # formats read as the same frame with one element removed.
        _paste(img, B.photo_disc(a.photo, d), HOST_CX, B.CY)
        return HOST_CX, d, HOST_CX, d, (PAIR_CX, B.CY + d // 2 - 6)

    if not a.guest:
        sys.exit("thumbnail: --format interview needs --guest")
    second = B.second_disc(B.text_layer(a.guest, B.NAME, 150, "#F2F5F8", tmp, "guest"), d)
    # Guest behind, host in front: the host owns the frame.
    _paste(img, second, SECOND_CX, B.CY)
    _paste(img, B.photo_disc(a.photo, d), HOST_CX, B.CY)
    return HOST_CX, d, SECOND_CX, d, (PAIR_CX, B.CY + d // 2 - 6)


def build(a):
    import tempfile
    tmp = tempfile.mkdtemp(prefix="itqan-thumb-")

    img = B.frame()
    host_cx, host_d, right_cx, right_d, badge_c = subject_zone(img, a, tmp)

    if a.episode:
        ep = B.episode_badge(a.episode, tmp)
        _paste(img, ep, badge_c[0], badge_c[1])

    # Three things on the frame, each with a gold arrow to what it is: the
    # host, the episode line, the programme. A reader who has never heard of
    # any of them gets all three from one glance. Each annotation owns its own
    # region, so nothing has to be read around anything else.
    spec = SPEC[a.format]
    if a.questions:
        # The questions ARE the headline; there is no separate title line.
        B.draw_questions(img, a.questions, tmp, a.highlight)
    else:
        anchor = B.draw_headline(img, a.line1, a.line2, tmp)
        if spec["headline_arrow"]:
            B.point_at_headline(img, anchor, right_cx, right_d)
    if spec["programme"] == "inline":
        B.draw_programme_inline(img, tmp)
    else:
        B.draw_programme(img, tmp, spec["lockup_word"])
    B.draw_host_label(img, a.host_label, tmp, host_cx, host_d)

    img.convert("RGB").save(a.out, quality=95)
    print("wrote {}  ({}x{}, {})".format(a.out, B.W, B.H, a.format))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--format", default="", choices=("",) + FORMATS,
                    help="interview | qa | idea; from meta.json with --call, else interview")
    ap.add_argument("--call", default="",
                    help="a call folder: guest and format from meta.json, lines and "
                         "episode from package.md, output thumb.png beside them")
    ap.add_argument("--photo", default=os.path.join(ROOT, "assets", "essam.jpg"))
    ap.add_argument("--guest", default="", help="name in the second disc; interview only")
    ap.add_argument("--highlight", type=int, default=0,
                    help="1-based: that question stays white, the rest go muted. "
                         "The in-video card. 0 (default) keeps them all white.")
    ap.add_argument("--question", action="append", default=[], dest="questions",
                    help="a question line; repeat. Replaces --line1/--line2 entirely.")
    ap.add_argument("--line1", default="")
    ap.add_argument("--line2", default="")
    ap.add_argument("--episode", type=int, default=0, help="number in the badge; 0 for none")
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
        # Older folders predate the format field and are all interviews.
        a.format = a.format or meta.get("format") or "interview"
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
    else:
        a.format = a.format or "interview"
        if not ((a.line1 or a.questions) and a.out):
            sys.exit("thumbnail: give --call <folder>, or --line1 and --out")

    a.highlight = (a.highlight - 1) if a.highlight else None
    if a.highlight is not None and not (0 <= a.highlight < len(a.questions)):
        sys.exit("thumbnail: --highlight must be between 1 and %d" % len(a.questions))
    if a.format not in FORMATS:
        sys.exit("thumbnail: unknown format {!r}; one of {}".format(a.format, ", ".join(FORMATS)))
    build(a)


if __name__ == "__main__":
    main()
