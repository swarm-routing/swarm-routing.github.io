#!/usr/bin/env python3
# Copyright (c) 2026 Daniel Joppi (https://github.com/swarm-routing)
# SPDX-License-Identifier: MIT OR GPL-2.0-only
"""Crawl the Colony Arena's own pages (everything outside /AntHocNet/, which
AntHocNet's check-site.py crawls) and fail on what a visitor would hit:
  * an internal link or asset (href/src) that resolves to no file, including
    links into /AntHocNet/ when that part was built;
  * a #fragment with no matching id in its target page;
  * two elements with the same id on one page;
  * a page without <html lang>, <title> or a <main> landmark.
External links are not fetched. Stdlib only.

Usage:  python3 tools/check_hub.py <site-dir>
        python3 tools/check_hub.py --self-test
"""
from __future__ import annotations

import os
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
