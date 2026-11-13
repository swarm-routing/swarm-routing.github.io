#!/usr/bin/env python3
# Copyright (c) 2026 Daniel Joppi (https://github.com/swarm-routing)
# SPDX-License-Identifier: MIT OR GPL-2.0-only
"""Crawl the Colony Arena's own pages (everything outside /AntHocNet/, which
AntHocNet's check-site.py crawls) and fail on what a visitor would hit:
  * an internal link or asset (href/src) that resolves to no file, including
    links into /AntHocNet/ when that part was built;
  * a #fragment with no matching id in its target page;
  * two elements with the same id on one page;
  * a page without <html lang>, <title> or a <main> landmark;
  * a generated status (data-status, from data/hub.json; #104) that is not one
    of live, building, planned, unknown; a page that shows a status other
    than unknown without the date of its data (<time data-asof datetime=
    YYYY-MM-DD>); a project page (<p class="status" data-status=...>) whose
    status links no GitHub issues, the source it was computed from.
External links are not fetched. Stdlib only.

Usage:  python3 tools/check_hub.py <site-dir>
        python3 tools/check_hub.py --self-test
"""
from __future__ import annotations

import os
import re
import sys
import tempfile
from html.parser import HTMLParser
from urllib.parse import unquote, urlsplit


class Page(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: list[str] = []
        self.ids: list[str] = []
        self.lang = self.title = self.main = False
        self.statuses: list[str] = []  # every data-status on the page
        self.own: str | None = None    # a project page's own status: <p class="status" data-status>
        self.asof: list[str] = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "html" and a.get("lang"):
            self.lang = True
        if tag == "title":
            self.title = True
        if tag == "main":
            self.main = True
        if a.get("id"):
            self.ids.append(a["id"])
        if "data-status" in a:
            self.statuses.append(a["data-status"] or "")
            if tag == "p" and "status" in (a.get("class") or "").split():
                self.own = a["data-status"] or ""
        if "data-asof" in a:
            self.asof.append(a.get("datetime") or "")
        for k in ("href", "src"):
            if a.get(k) and tag not in ("base",):
                self.links.append(a[k])


def parse(path: str) -> Page:
    p = Page()
    with open(path, encoding="utf-8") as f:
        p.feed(f.read())
    return p


def target(site: str, page: str, link: str) -> tuple[str | None, str]:
    u = urlsplit(link)
    if u.scheme or u.netloc or link.startswith(("mailto:", "data:", "javascript:")):
        return None, ""
    path = unquote(u.path)
    if not path:
        return page, u.fragment
    base = site if path.startswith("/") else os.path.dirname(page)
    f = os.path.normpath(os.path.join(base, path.lstrip("/")))
    if path.endswith("/") or os.path.isdir(f):
        f = os.path.join(f, "index.html")
    return f, u.fragment


def check(site: str) -> list[str]:
    site = os.path.abspath(site)
    skip = os.path.join(site, "AntHocNet")
    errs: list[str] = []
    cache: dict[str, Page] = {}
    pages = []
    for d, dirs, files in os.walk(site):
        if os.path.abspath(d).startswith(skip):
            dirs[:] = []
            continue
        pages += [os.path.join(d, f) for f in files if f.endswith(".html") and f != "404.html"]
    for page in sorted(pages):
        rel = os.path.relpath(page, site)
        p = cache.setdefault(page, parse(page))
        for flag, what in ((p.lang, "<html lang>"), (p.title, "<title>"), (p.main, "<main>")):
            if not flag:
                errs.append(f"{rel}: no {what}")
        seen = set()
        for i in p.ids:
            if i in seen:
                errs.append(f"{rel}: duplicate id {i!r}")
            seen.add(i)
        errs += [f"{rel}: {e}" for e in generated(p)]
        for link in p.links:
            f, frag = target(site, page, link)
            if f is None:
                continue
            if not f.startswith(site):
                errs.append(f"{rel}: {link} leaves the site")
                continue
            if f.startswith(skip) and not os.path.isdir(skip):
                continue  # SKIP_ANTHOCNET build: that half is not there to check
            if not os.path.isfile(f):
                errs.append(f"{rel}: {link} -> missing {os.path.relpath(f, site)}")
                continue
            if frag and f.endswith(".html"):
                t = cache.setdefault(f, parse(f))
                if frag not in t.ids:
                    errs.append(f"{rel}: {link} -> no id {frag!r}")
    if not pages:
        errs.append("no pages found")
    return errs


STATUSES = ("live", "building", "planned", "unknown")
ISSUES = re.compile(r"^https://github\.com/[^/]+/[^/]+/issues\b")


def generated(p: Page) -> list[str]:
    """What is wrong with a page's generated status fields (none: [])."""
    errs = [f"data-status {s!r} is not one of {', '.join(STATUSES)}" for s in p.statuses if s not in STATUSES]
    errs += [f"data-asof {d!r} is not a YYYY-MM-DD date" for d in p.asof if not re.match(r"^\d{4}-\d\d-\d\d$", d)]
    if any(s != "unknown" for s in p.statuses) and not p.asof:
        errs.append("a generated status without the date of its data (<time data-asof>)")
    if p.own is not None and not any(ISSUES.match(link) for link in p.links):
        errs.append("a project status that links no GitHub issues (its source)")
    return errs


def self_test() -> None:
    with tempfile.TemporaryDirectory() as d:
        os.makedirs(os.path.join(d, "a"))
        ok = '<html lang="en"><title>x</title><main id="m"><a href="a/">a</a><a href="#m">m</a></main></html>'
        with open(os.path.join(d, "index.html"), "w") as f:
            f.write(ok)
        with open(os.path.join(d, "a", "index.html"), "w") as f:
            f.write('<html lang="en"><title>a</title><main><a href="../#m">x</a><a href="/">r</a>'
                    '<a href="https://e.org/">e</a></main></html>')
        assert check(d) == [], check(d)
        with open(os.path.join(d, "a", "index.html"), "w") as f:
            f.write('<html><title>a</title><main id="x"><i id="x"></i><a href="../nope/">n</a>'
                    '<a href="../#zz">z</a></main></html>')
        got = check(d)
        for want in ("no <html lang>", "duplicate id 'x'", "missing nope/index.html", "no id 'zz'"):
            assert any(want in e for e in got), (want, got)
        # the generated status fields
        t = '<time data-asof datetime="2026-11-13">2026-11-13</time>'
        src = '<a href="https://github.com/o/r/issues?q=label%3Aepic">epics</a>'
        cases = [
            (f'<p class="status" data-status="building">x {src}</p>{t}<i data-status="planned"></i>', None),
            ('<p class="status" data-status="unknown"><a href="https://github.com/o/r/issues">i</a></p>', None),
            ('<i data-status="unknown"></i>', None),  # no data: no date to show
            (f'<i data-status="live"></i>{src}', "without the date"),
            (f'<i data-status="done"></i>{t}', "'done' is not one of"),
            ('<i data-status="live"></i><time data-asof datetime="yesterday">y</time>', "not a YYYY-MM-DD date"),
            (f'<p class="status" data-status="live">x <a href="https://github.com/o/r">repo</a></p>{t}', "links no GitHub issues"),
        ]
        for body, want in cases:
            with open(os.path.join(d, "a", "index.html"), "w") as f:
                f.write(f'<html lang="en"><title>a</title><main>{body}</main></html>')
            got = check(d)
            assert (got == []) if want is None else any(want in e for e in got), (body, want, got)
    print("check_hub.py self-test: ok")


def main(argv: list[str]) -> int:
    if argv == ["--self-test"]:
        self_test()
        return 0
    if len(argv) != 1:
        print(__doc__, file=sys.stderr)
        return 2
    errs = check(argv[0])
    for e in errs:
        print(e, file=sys.stderr)
    print(f"check_hub.py: {'FAIL, ' + str(len(errs)) + ' problems' if errs else 'ok'}")
    return 1 if errs else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
