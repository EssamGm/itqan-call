#!/usr/bin/env python3
"""
Say what a call is: a numbered episode, or a test.

    python promote.py <call-folder>              next number, status draft
    python promote.py <call-folder> --published  mark it published
    python promote.py <call-folder> --test       a test; no number, never listed
    python promote.py --list                     the ledger

The number is assigned here and only here, into C:\\Itqan\\episodes.tsv and
the folder's meta.json. Nothing else in the pipeline invents one: a skill
reading a folder in isolation cannot know how many episodes exist, and a
guessed number eventually publishes episode 4 twice. PACKAGE copies the
number from meta.json, or writes `episode: TODO` and says so.

The ledger lives beside the calls, not in the repo, because a list of which
trainee was on which call is personal data and stays on this laptop.
"""

import argparse
import os
import sys

sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "render")
)
import callfolder as cf  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("folder", nargs="?", help="a call folder, or its name under C:\\Itqan\\calls")
    ap.add_argument("--test", action="store_true")
    ap.add_argument("--published", action="store_true")
    ap.add_argument("--list", action="store_true")
    a = ap.parse_args()

    if a.list or not a.folder:
        rows = cf.read_ledger()
        if not rows:
            print("no episodes yet")
            return
        for r in rows:
            print("  {:>3}  {}  {:<10}  {}".format(r["episode"] or "-", r["date"],
                                                r["status"], r["guest"]))
        return

    folder = a.folder
    if not os.path.isdir(folder):
        folder = os.path.join(cf.CALLS_DIR, a.folder)
    if not os.path.isfile(os.path.join(folder, cf.META)):
        sys.exit("promote: no meta.json in " + folder)

    if a.test:
        cf.promote(folder, test=True)
        print("marked as a test: " + os.path.basename(folder))
    else:
        n = cf.promote(folder, status="published" if a.published else "draft")
        print("episode {} ({}): {}".format(
            n, "published" if a.published else "draft", os.path.basename(folder)))


if __name__ == "__main__":
    main()
