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
  * a page without the site's one top bar, or with a bar that differs from
    the hub's (#97). The current-place marker may differ, and so may the
    relative depth of a link (links are compared by what they resolve to);
    AntHocNet's game, docs and API pages, when built, carry the same bar
    plus AntHocNet's own row.
External links are not fetched. Stdlib only.

Usage:  python3 tools/check_hub.py <site-dir>
        python3 tools/check_hub.py --self-test
"""
from __future__ import annotations

import os
import posixpath
import re
import shutil
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
        self.own_links: list[str] = []  # the links inside that paragraph
        self.in_own = False
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
                self.in_own = True
        if "data-asof" in a:
            self.asof.append(a.get("datetime") or "")
        for k in ("href", "src"):
            if a.get(k) and tag not in ("base",):
                self.links.append(a[k])
                if self.in_own:
                    self.own_links.append(a[k])

    def handle_endtag(self, tag):
        if tag == "p":
            self.in_own = False


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


BAR = re.compile(r'<header class="ahn-bar".*?</header>', re.DOTALL)
ROW2 = re.compile(r'[ \t]*<div class="ahn-row ahn-row2">.*?</div>\n(?=\s*</header>)', re.DOTALL)
LINK = re.compile(r'((?:href|action|data-root)=")([^"]*)(")')
AHN_SAMPLE = ("index.html", "workshop.html", "replay.html", "docs/index.html", "docs/places/lab/index.html",
              "api/index.html", "api/annotated.html")  # the game, the docs and the API reference


def bar_of(site: str, page: str) -> str | None:
    """The page's top bar, made comparable: no current-place marker, no
    AntHocNet row, every internal link as the site path it resolves to."""
    with open(page, encoding="utf-8", errors="replace") as f:
        m = BAR.search(f.read())
    if not m:
        return None
    here = "/" + posixpath.dirname(os.path.relpath(page, site).replace(os.sep, "/"))

    def resolve(mm: re.Match) -> str:
        url = mm.group(2)
        if urlsplit(url).scheme or url.startswith("#"):
            return mm.group(0)
        path = posixpath.normpath(posixpath.join(here, url))
        return mm.group(1) + path + ("/" if url.endswith("/") and path != "/" else "") + mm.group(3)
    bar = re.sub(r' aria-current="(?:page|true)"', "", ROW2.sub("", m.group(0)))
    return LINK.sub(resolve, bar)


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
    # One top bar (#97): every page's, and AntHocNet's when that half is built.
    home = os.path.join(site, "index.html")
    want = bar_of(site, home) if os.path.isfile(home) else None
    redirects = {p for p in pages if 'http-equiv="refresh"' in open(p, encoding="utf-8").read()}
    for page in sorted(set(pages) - redirects) + [os.path.join(skip, n) for n in AHN_SAMPLE]:
        if not os.path.isfile(page):
            continue
        got = bar_of(site, page)
        rel = os.path.relpath(page, site)
        if got is None:
            errs.append(f"{rel}: no top bar")
        elif want is not None and got != want:
            errs.append(f"{rel}: its top bar differs from the hub's")
    return errs


STATUSES = ("live", "building", "planned", "unknown")
ISSUES = re.compile(r"^https://github\.com/[^/]+/[^/]+/issues\b")


def generated(p: Page) -> list[str]:
    """What is wrong with a page's generated status fields (none: [])."""
    errs = [f"data-status {s!r} is not one of {', '.join(STATUSES)}" for s in p.statuses if s not in STATUSES]
    errs += [f"data-asof {d!r} is not a YYYY-MM-DD date" for d in p.asof if not re.match(r"^\d{4}-\d\d-\d\d$", d)]
    if any(s != "unknown" for s in p.statuses) and not p.asof:
        errs.append("a generated status without the date of its data (<time data-asof>)")
    if p.own is not None and not any(ISSUES.match(link) for link in p.own_links):
        errs.append("a project status that links no GitHub issues (its source)")
    return errs


def self_test() -> None:
    with tempfile.TemporaryDirectory() as d:
        os.makedirs(os.path.join(d, "a"))
        def bar(hub, ahn, on="", row2=""):
            return (f'<header class="ahn-bar" role="banner">\n  <div class="ahn-row">\n    <a href="{hub}">Colony Arena</a>'
                    f'<a href="{ahn}"{on}>Play</a><a href="https://e.org/">GitHub</a>\n  </div>\n{row2}</header>')
        row2 = '  <div class="ahn-row ahn-row2">\n    <a href="./docs/" aria-current="page">Lab</a>\n  </div>\n'
        ok = ('<html lang="en"><title>x</title>' + bar("./", "AntHocNet/")
              + '<main id="m"><a href="a/">a</a><a href="#m">m</a></main></html>')
        with open(os.path.join(d, "index.html"), "w") as f:
            f.write(ok)
        with open(os.path.join(d, "a", "index.html"), "w") as f:
            f.write('<html lang="en"><title>a</title>' + bar("../", "../AntHocNet/", ' aria-current="page"')
                    + '<main><a href="../#m">x</a><a href="/">r</a><a href="https://e.org/">e</a></main></html>')
        assert check(d) == [], check(d)
        # AntHocNet's half: the same bar plus its own row, the hub root-absolute
        os.makedirs(os.path.join(d, "AntHocNet", "docs"))
        for rel, html in (("index.html", bar("/", "./", ' aria-current="page"', row2)),
                          ("docs/index.html", bar("/", "../", ' aria-current="true"', row2.replace("./docs/", "./")))):
            with open(os.path.join(d, "AntHocNet", rel), "w") as f:
                f.write(html)
        assert check(d) == [], check(d)
        with open(os.path.join(d, "AntHocNet", "docs", "index.html"), "w") as f:
            f.write(bar("/", "../", "", row2).replace("Play", "Jogar"))
        with open(os.path.join(d, "AntHocNet", "workshop.html"), "w") as f:
            f.write("<html><body>no bar</body></html>")
        got = check(d)
        for want in ("AntHocNet/docs/index.html: its top bar differs from the hub's", "AntHocNet/workshop.html: no top bar"):
            assert any(want in e for e in got), (want, got)
        shutil.rmtree(os.path.join(d, "AntHocNet"))
        with open(os.path.join(d, "a", "index.html"), "w") as f:
            f.write('<html><title>a</title><main id="x"><i id="x"></i><a href="../nope/">n</a>'
                    '<a href="../#zz">z</a></main></html>')
        got = check(d)
        for want in ("no <html lang>", "duplicate id 'x'", "missing nope/index.html", "no id 'zz'", "a/index.html: no top bar"):
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
            # an issues link elsewhere on the page is not the status's source
            (f'<p class="status" data-status="live">x</p>{src}{t}', "links no GitHub issues"),
        ]
        for body, want in cases:
            with open(os.path.join(d, "a", "index.html"), "w") as f:
                f.write(f'<html lang="en"><title>a</title><main>{body}</main></html>')
            got = [e for e in check(d) if "top bar" not in e]  # the bar has its own case above
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
