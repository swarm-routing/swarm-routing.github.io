#!/usr/bin/env python3
# Copyright (c) 2026 Daniel Joppi (https://github.com/swarm-routing)
# SPDX-License-Identifier: MIT OR GPL-2.0-only
"""The site's build marker (#28): which commit of this repository a page was built from.

GitHub serves a repository's own project Pages ahead of the org site for
/<repo>/, so a stale copy of /AntHocNet/ from another source once passed the
live smoke (it compared the core's hash, which had not changed). Every HTML
page of the assembled site therefore carries

    <meta name="swarm-site-build" content="<40-char commit>">

and the live smoke requires the commit it just deployed on the pages it fetches.

    stamp_build.py stamp <site-dir> <commit>   write the marker into every .html (replacing an older one)
    stamp_build.py check <site-dir> <commit>   exit 1 unless every .html carries exactly that marker
    stamp_build.py live <base-url> <commit> [--wait SECONDS] [PATH ...]
                                               fetch the pages (default: the hub, the project index, the game,
                                               its docs and its API) until each carries the marker, or fail
                                               after SECONDS (default 900: Pages caches for 10 minutes)
    stamp_build.py --self-test
Stdlib only.
"""
from __future__ import annotations

import http.server
import os
import re
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request

NAME = "swarm-site-build"
MARK = re.compile(r'<meta name="swarm-site-build" content="([^"]*)">')
HEAD = re.compile(r"<head(\s[^>]*)?>", re.IGNORECASE)
SHA = re.compile(r"[0-9a-f]{40}")
LIVE_PATHS = ("", "projects/", "AntHocNet/", "AntHocNet/docs/", "AntHocNet/api/")


def pages(site: str) -> list[str]:
    return sorted(os.path.join(d, f) for d, _, files in os.walk(site) for f in files if f.endswith(".html"))


def stamp(site: str, commit: str) -> list[str]:
    """Write the marker into every page; return the pages that have no <head> to carry it."""
    tag, bad = f'<meta name="{NAME}" content="{commit}">', []
    for path in pages(site):
        with open(path, encoding="utf-8") as f:
            text = f.read()
        if MARK.search(text):
            new = MARK.sub(tag, text, count=1)
        elif HEAD.search(text):
            new = HEAD.sub(lambda m: m.group(0) + tag, text, count=1)
        else:
            bad.append(os.path.relpath(path, site))
            continue
        if new != text:
            with open(path, "w", encoding="utf-8") as f:
                f.write(new)
    return bad


def check(site: str, commit: str) -> list[str]:
    errs = []
    for path in pages(site):
        with open(path, encoding="utf-8") as f:
            found = MARK.findall(f.read())
        if found != [commit]:
            errs.append(f"{os.path.relpath(path, site)}: marker {found or 'missing'}, expected {commit}")
    if not pages(site):
        errs.append("no pages found")
    return errs


def seen(url: str) -> str:
    """The marker a live page carries: its commit, '' when it has none, or the error fetching it."""
    try:
        req = urllib.request.Request(f"{url}?nocache={time.time_ns()}", headers={"Cache-Control": "no-cache"})
        with urllib.request.urlopen(req, timeout=20) as r:
            m = MARK.search(r.read().decode("utf-8", "replace"))
        return m.group(1) if m else ""
    except (OSError, urllib.error.URLError) as e:
        return f"error: {e}"


def live(base: str, commit: str, paths, wait: float, pause: float = 20.0) -> list[str]:
    deadline = time.monotonic() + wait
    while True:
        got = {p: seen(base + p) for p in paths}
        stale = [f"{base}{p}: marker {v or 'missing'}, expected {commit}" for p, v in got.items() if v != commit]
        if not stale or time.monotonic() >= deadline:
            return stale
        time.sleep(pause)


def self_test() -> None:
    a, b = "a" * 40, "b" * 40
    with tempfile.TemporaryDirectory() as d:
        os.makedirs(os.path.join(d, "x"))
        for rel, text in (("index.html", "<!doctype html><html><head><title>t</title></head><body></body></html>"),
                          ("x/index.html", '<html><HEAD lang="en">\n<title>t</title></HEAD></html>'),
                          ("x/notes.txt", "<head>")):
            with open(os.path.join(d, rel), "w", encoding="utf-8") as f:
                f.write(text)
        assert check(d, a) and stamp(d, a) == [] and check(d, a) == [], check(d, a)
        with open(os.path.join(d, "x", "notes.txt"), encoding="utf-8") as f:
            assert f.read() == "<head>"  # only .html is touched
        assert stamp(d, b) == [] and check(d, b) == [] and len(check(d, a)) == 2  # restamped, never doubled
        with open(os.path.join(d, "index.html"), encoding="utf-8") as f:
            assert f.read().count(NAME) == 1
        with open(os.path.join(d, "bare.html"), "w", encoding="utf-8") as f:
            f.write("<p>no head</p>")
        assert stamp(d, b) == ["bare.html"] and any("bare.html: marker missing" in e for e in check(d, b))
        os.remove(os.path.join(d, "bare.html"))

        class Quiet(http.server.SimpleHTTPRequestHandler):
            def __init__(self, *args):
                super().__init__(*args, directory=d)

            def log_message(self, *args):
                pass

        srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Quiet)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        base = f"http://127.0.0.1:{srv.server_address[1]}/"
        try:
            assert live(base, b, ("", "x/"), wait=0) == []
            old = live(base, a, ("", "x/"), wait=0)  # a page with another build's marker fails the live check
            assert len(old) == 2 and f"marker {b}, expected {a}" in old[0], old
            assert "error:" in live(base, b, ("nope/",), wait=0)[0]
            # a deploy that lands while we wait is seen: restamp to a after the first poll
            threading.Timer(0.3, stamp, (d, a)).start()
            assert live(base, a, ("", "x/"), wait=5, pause=0.2) == []
        finally:
            srv.shutdown()
    print("stamp_build.py self-test: ok")


def main(argv: list[str]) -> int:
    if argv == ["--self-test"]:
        self_test()
        return 0
    if len(argv) >= 3 and argv[0] in ("stamp", "check", "live") and SHA.fullmatch(argv[2]):
        cmd, where, commit, rest = argv[0], argv[1], argv[2], argv[3:]
        if cmd == "stamp" and not rest:
            errs = [f"{p}: no <head> to carry the marker" for p in stamp(where, commit)]
        elif cmd == "check" and not rest:
            errs = check(where, commit)
        elif cmd == "live":
            wait = 900.0
            if rest[:1] == ["--wait"] and len(rest) >= 2:
                wait, rest = float(rest[1]), rest[2:]
            errs = live(where if where.endswith("/") else where + "/", commit, tuple(rest) or LIVE_PATHS, wait)
        else:
            print(__doc__, file=sys.stderr)
            return 2
        for e in errs:
            print(e, file=sys.stderr)
        print(f"stamp_build.py {cmd}: {'FAIL, ' + str(len(errs)) + ' problems' if errs else 'ok'} ({commit[:12]})")
        return 1 if errs else 0
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
