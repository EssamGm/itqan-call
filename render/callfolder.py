#!/usr/bin/env python3
"""
One folder per call, files as the interface.

Every stage of the pipeline - fetch, transcribe, align, the three judgment
tasks, render, thumbnail - reads and writes plain files in one folder:

    C:\\Itqan\\calls\\<YYYY-MM-DD>_<guest>\\

That is the whole coordination mechanism. No stage calls another; each one
looks at what is in the folder, does its job, and writes its result. So any
task can be picked up alone, in any order its inputs allow, from any tool
that can read and write a text file.

This module is the only place that knows the file names, so a rename is one
edit rather than a hunt.

    coach.m4a, trainee.m4a              fetch
    meta.json                           fetch; promote adds `episode`
    coach.transcript.json, trainee.…    transcribe (index = array position,
                                        per-speaker original clock)
    alignment.json, conversation.tsv    align (the aligned clock; judgment
                                        reads the tsv, render reads the json)
    coach.corrections.txt, trainee.…    CORRECT (changed lines only)
    cuts.txt                            REVIEW (aligned seconds; cut/ask/keep)
    package.md                          PACKAGE (frontmatter + description)
    final.mp4, final.m4a, chapters.txt  render
    thumb.png                           thumbnail

Everything is UTF-8 without BOM, written with LF. Readers accept CRLF too,
because Windows tools will produce it and Arabic text must not break on a
line ending.
"""

import datetime
import json
import os
import re

ROOT = os.environ.get("ITQAN_ROOT", r"C:\Itqan")
CALLS_DIR = os.path.join(ROOT, "calls")
LEDGER = os.path.join(ROOT, "episodes.tsv")

TRACKS = ("coach", "trainee")

# File names, in one place.
AUDIO = "{}.m4a"
TRANSCRIPT = "{}.transcript.json"
CORRECTIONS = "{}.corrections.txt"
META = "meta.json"
ALIGNMENT = "alignment.json"
CONVERSATION = "conversation.tsv"
CUTS = "cuts.txt"
PACKAGE = "package.md"
CHAPTERS = "chapters.txt"
FINAL = "final"          # final.mp4, final.m4a
THUMB = "thumb.png"


# ---------------------------------------------------------------- io helpers

def read_text(path):
    with open(path, "r", encoding="utf-8-sig") as fh:   # -sig strips a BOM if present
        return fh.read()


def write_text(path, text):
    """UTF-8, no BOM, LF. Always."""
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)


def read_json(path):
    return json.loads(read_text(path))


def write_json(path, data):
    write_text(path, json.dumps(data, ensure_ascii=False, indent=1) + "\n")


def read_tsv(path, skip_comments=True):
    """Rows as lists of strings. Lines starting with # are metadata, not data."""
    rows = []
    for line in read_text(path).splitlines():
        if not line.strip():
            continue
        if skip_comments and line.startswith("#"):
            continue
        rows.append(line.split("\t"))
    return rows


def write_tsv(path, rows, header=None, comments=()):
    lines = ["# " + c for c in comments]
    if header:
        lines.append("\t".join(header))
    lines += ["\t".join(str(c) for c in r) for r in rows]
    write_text(path, "\n".join(lines) + "\n")


# ---------------------------------------------------------------- the folder

def safe_name(s):
    """A guest name as a folder name: keep letters (any script), digits, space -> _."""
    s = re.sub(r"[\\/:*?\"<>|]+", "", s or "").strip()
    return re.sub(r"\s+", "_", s) or "unknown"


def folder_for(date, guest):
    """date: 'YYYY-MM-DD' or a datetime."""
    if isinstance(date, (datetime.date, datetime.datetime)):
        date = date.strftime("%Y-%m-%d")
    return os.path.join(CALLS_DIR, "{}_{}".format(date, safe_name(guest)))


def path(folder, name, track=None):
    return os.path.join(folder, name.format(track) if track else name)


def exists(folder, name, track=None):
    return os.path.isfile(path(folder, name, track))


def list_calls():
    """Every call folder that has a meta.json, oldest first."""
    if not os.path.isdir(CALLS_DIR):
        return []
    out = []
    for d in sorted(os.listdir(CALLS_DIR)):
        f = os.path.join(CALLS_DIR, d)
        if os.path.isfile(os.path.join(f, META)):
            out.append(f)
    return out


# ---------------------------------------------------------------- meta

def read_meta(folder):
    return read_json(path(folder, META))


def write_meta(folder, meta):
    write_json(path(folder, META), meta)


# ---------------------------------------------------------------- ledger

LEDGER_HEADER = ["episode", "date", "guest", "folder", "status"]
STATUSES = ("test", "draft", "published")


def read_ledger():
    if not os.path.isfile(LEDGER):
        return []
    rows = read_tsv(LEDGER)
    if rows and rows[0] == LEDGER_HEADER:
        rows = rows[1:]
    return [dict(zip(LEDGER_HEADER, r)) for r in rows if len(r) == len(LEDGER_HEADER)]


def write_ledger(rows):
    write_tsv(LEDGER, [[r[k] for k in LEDGER_HEADER] for r in rows], header=LEDGER_HEADER,
              comments=["one row per call that has been looked at; test rows carry no number"])


def next_episode():
    nums = [int(r["episode"]) for r in read_ledger() if r["episode"].isdigit()]
    return (max(nums) + 1) if nums else 1


def promote(folder, test=False, status="draft"):
    """
    Record what this call is: a numbered episode, or a test.

    The number is assigned here and nowhere else, because a skill working
    from a fresh session with only the folder in front of it cannot know how
    many episodes exist, and a guessed number publishes episode 4 twice.
    """
    meta = read_meta(folder)
    rows = read_ledger()
    name = os.path.basename(folder)
    rows = [r for r in rows if r["folder"] != name]      # re-promote replaces the row
    if test:
        meta["episode"] = None
        rows.append({"episode": "", "date": meta["date"], "guest": meta["guest"],
                     "folder": name, "status": "test"})
    else:
        n = meta.get("episode") or next_episode()
        meta["episode"] = n
        rows.append({"episode": str(n), "date": meta["date"], "guest": meta["guest"],
                     "folder": name, "status": status})
    rows.sort(key=lambda r: (r["date"], r["folder"]))
    write_ledger(rows)
    write_meta(folder, meta)
    return meta.get("episode")


def ledger_status(folder):
    name = os.path.basename(folder)
    for r in read_ledger():
        if r["folder"] == name:
            return r["status"]
    return None


# ---------------------------------------------------------------- cuts

CUT_STATUSES = ("cut", "ask", "keep")


def read_cuts(folder):
    """
    [{start, end, status, reason}], aligned seconds.

    Tolerant of a missing file (no cuts) and of a header row. Strict about
    status, because a typo there must not silently become "not cut".
    """
    p = path(folder, CUTS)
    if not os.path.isfile(p):
        return []
    out = []
    for r in read_tsv(p):
        if r[0].strip().lower() in ("start", "aligned_start"):
            continue
        if len(r) < 3:
            raise ValueError("cuts.txt: expected start<TAB>end<TAB>status<TAB>reason, got: " + "\t".join(r))
        status = r[2].strip().lower()
        if status not in CUT_STATUSES:
            raise ValueError("cuts.txt: status must be one of {}, got {!r}".format(CUT_STATUSES, r[2]))
        out.append({"start": float(r[0]), "end": float(r[1]), "status": status,
                    "reason": r[3].strip() if len(r) > 3 else ""})
    out.sort(key=lambda c: c["start"])
    return out


# ---------------------------------------------------------------- package

def read_package(folder):
    """
    package.md: YAML-ish frontmatter between --- lines, then the description.

    Deliberately not a YAML library: the fields are flat scalars and one list
    of strings, and a dependency for that is one more thing to break on a
    fresh machine. Handles quoted and unquoted values, and a list as either
    indented "- item" lines or a bracketed inline list.
    """
    p = path(folder, PACKAGE)
    if not os.path.isfile(p):
        return None
    text = read_text(p)
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n?(.*)$", text, re.S)
    if not m:
        raise ValueError("package.md: expected frontmatter between --- lines")
    front, body = m.group(1), m.group(2)
    fields = {}
    key = None
    for line in front.splitlines():
        if not line.strip():
            continue
        if line.startswith((" ", "\t")) and key and line.strip().startswith("-"):
            fields.setdefault(key, [])
            if not isinstance(fields[key], list):
                fields[key] = []
            fields[key].append(_unquote(line.strip()[1:].strip()))
            continue
        km = re.match(r"^([A-Za-z_][\w-]*)\s*:\s*(.*)$", line)
        if not km:
            continue
        key, val = km.group(1), km.group(2).strip()
        if val.startswith("[") and val.endswith("]"):
            fields[key] = [_unquote(v.strip()) for v in val[1:-1].split(",") if v.strip()]
        elif val == "":
            fields[key] = []          # a list follows, or genuinely empty
        else:
            fields[key] = _unquote(val)
    fields["description"] = body.strip()
    return fields


def _unquote(v):
    if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
        return v[1:-1]
    return v


def parse_chapter(line):
    """'m:ss title' or 'h:mm:ss title' -> (seconds, title)."""
    m = re.match(r"^\s*(?:(\d+):)?(\d{1,2}):(\d{2})\s+(.+?)\s*$", line)
    if not m:
        raise ValueError("chapter must look like 'm:ss title', got: " + line)
    h, mm, ss, title = m.groups()
    return (int(h or 0) * 3600 + int(mm) * 60 + int(ss), title)


def fmt_mmss(seconds):
    s = int(round(seconds))
    return "{}:{:02d}".format(s // 60, s % 60)
