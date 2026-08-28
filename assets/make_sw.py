#!/usr/bin/env python3
"""
Copy the shared service worker into each app scope.

A service worker can only control pages at or below its own path, so the two
apps need a worker each. They are generated from one source rather than loaded
via importScripts, which failed to register: keeping the whole worker in one
file removes a fetch that has to succeed before the app can install at all.

Run after editing web/sw-core.js.
"""

import os

HERE = os.path.dirname(os.path.abspath(__file__))
WEB = os.path.join(os.path.dirname(HERE), "web")

HEADER = "// GENERATED from sw-core.js by assets/make_sw.py - do not edit here.\n\n"


def main():
    with open(os.path.join(WEB, "sw-core.js"), encoding="utf-8") as fh:
        body = fh.read()
    for scope in ("t", "c"):
        out = os.path.join(WEB, scope, "sw.js")
        with open(out, "w", encoding="utf-8") as fh:
            fh.write(HEADER + body)
        print("wrote", os.path.relpath(out, WEB))


if __name__ == "__main__":
    main()
