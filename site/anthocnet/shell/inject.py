# SPDX-License-Identifier: GPL-2.0-only
# Copyright (C) 2026 Daniel Henrique Joppi
"""Put the site's one top bar on every surface (#626/#627, #97).

The game, the docs (mkdocs) and the API reference (Doxygen) are three builds,
and the Colony Arena hub a fourth (tools/render_hub.py, which reads the same
topbar.html). They share one bar: web/shell/topbar.html, rendered here with
the page's path to AntHocNet's root and its active place, plus the shell's
assets: tokens.css (every colour, radius and font of the site), shell.css,
theme.js (the one day/night choice, before the first paint) and shell.js.
Each surface carries its own copy of the assets, so the docs and the API also
work when built and served on their own.

Used these ways:
  * game:  python3 web/shell/inject.py game <site-dir>     (build-site.sh)
  * api:   python3 web/shell/inject.py api  <api-html-dir>  (pages.yml)
  * docs:  imported by docs/tools/mkdocs_hooks.py (on_post_page / on_post_build)
  * bar:   python3 web/shell/inject.py bar <root> [place]   prints the bar (the
           hub's renderer compares its own with it)
  * python3 web/shell/inject.py --self-test                 (fixtures, no build)
"""
from __future__ import annotations

import html as _html
import os
import re
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PLACES = ("guide", "lab", "shop", "arch")  # AntHocNet's own places: the bar's second row
TOPS = ("play", "projects", "refs", "run")  # the site's first-level places
# The Colony Arena hub is the site root. AntHocNet's pages name it root-absolute:
# they are also built and crawled on their own (AntHocNet's check-site.py), where
# a relative "../" would leave the tree.
HUB = "/"
ASSETS = ("tokens.css", "shell.css", "theme.js", "shell.js")
MARKER = re.compile(r"<!--AHN-TOPBAR(?: (\w+))?-->")


def topbar(root: str, active: str | None) -> str:
    """The bar's markup for a page whose path to the site root is `root`."""
    with open(os.path.join(HERE, "topbar.html"), encoding="utf-8") as f:
        html = f.read()
    html = re.sub(r"<!--.*?-->\s*", "", html, count=1, flags=re.DOTALL)  # header comment
    html = re.sub(r"[ \t]*<!--/?AHN-ROW2-->\n", "", html)  # AntHocNet's row stays: this is AntHocNet
    for p in PLACES:
        html = html.replace(f"{{ON:{p}}}", ' aria-current="page"' if p == active else "")
    # Every page here is under Play: the game itself, or a place inside it.
    here = ' aria-current="true"' if active in PLACES else ' aria-current="page"'
    for t in TOPS:
        html = html.replace(f"{{TOP:{t}}}", here if t == "play" else "")
    return html.replace("{HUB}", HUB).replace("{ROOT}", root).strip()


def breadcrumb(items: list[tuple[str, str | None]], place: str | None = None) -> str:
    """The trail from the site root to this page (#652): `items` are (label,
    href) pairs from AntHocNet's root down, the last one the current page; an
    href of None is a level with no page of its own. The trail starts at the
    site's root, the Colony Arena hub (#97). The place's colour comes from
    `data-place`."""
    items = [("Colony Arena", HUB)] + list(items)
    lis = []
    for i, (label, href) in enumerate(items):
        text = _html.escape(label)
        if i == len(items) - 1:
            lis.append(f'<li><span aria-current="page">{text}</span></li>')
        elif href:
            lis.append(f'<li><a href="{_html.escape(href)}">{text}</a></li>')
        else:
            lis.append(f"<li><span>{text}</span></li>")
    return (f'<nav class="ahn-crumb" aria-label="Breadcrumb" data-place="{place or ""}">'
            f'<ol>{"".join(lis)}</ol></nav>')


def copy_assets(dest: str, extra: tuple[str, ...] = ()) -> None:
    os.makedirs(dest, exist_ok=True)
    for name in ASSETS + extra:
        shutil.copyfile(os.path.join(HERE, name), os.path.join(dest, name))


def inject_page(html: str, root: str, active: str | None, assets: str,
                css: tuple[str, ...] = ("shell.css",), script: str | None = None) -> str:
    """Add the stylesheet(s) to <head>, the bar after <body>, and the shell
    script before </body>. `assets` is the page's relative path to the copied
    shell assets. Idempotent: a page that already has the bar is returned as is."""
    if 'class="ahn-bar"' in html:
        return html
    # The tokens come first; theme.js is a plain script, so the page never
    # paints in the wrong theme.
    links = "".join(f'<link rel="stylesheet" href="{assets}{c}">' for c in ("tokens.css",) + tuple(css))
    links += f'<script src="{assets}theme.js"></script>'
    html = html.replace("</head>", links + "</head>", 1)
    m = MARKER.search(html)
    if m:
        html = html[:m.start()] + topbar(root, m.group(1) or active) + html[m.end():]
    else:
        bar = topbar(root, active)
        html = re.sub(r"(<body[^>]*>)", lambda mm: mm.group(1) + bar, html, count=1)
    if script:
        html = html.replace("</body>", script + "</body>", 1)
    return html


def boot_script(assets: str) -> str:
    if not assets.startswith((".", "/")):
        assets = "./" + assets  # a bare specifier is not a relative module URL
    return f'<script type="module">import {{ initPage }} from "{assets}shell.js"; initPage();</script>'


# --- game --------------------------------------------------------------------
def game(site: str) -> None:
    """Every page in the game's root carries the marker (optionally naming its
    place, `<!--AHN-TOPBAR shop-->`). The pages' own scripts own the theme
    button and search wiring (app.js: the in-game reader), so no boot script."""
    pages = sorted(n for n in os.listdir(site) if n.endswith(".html") and n != "404.html")
    for name in pages:
        path = os.path.join(site, name)
        with open(path, encoding="utf-8") as f:
            html = f.read()
        if not MARKER.search(html):
            sys.exit(f"inject.py: {path} has no <!--AHN-TOPBAR--> marker")
        with open(path, "w", encoding="utf-8") as f:
            f.write(inject_page(html, "./", None, "shell/"))
    copy_assets(os.path.join(site, "shell"))


# --- API reference -------------------------------------------------------------
def api(apidir: str) -> None:
    """Doxygen writes a flat html/ directory (plus search/); the API lives at
    <site>/api/, so the site root is one level up from a top-level page."""
    copy_assets(os.path.join(apidir, "ahn"), ("api.css",))
    n = 0
    for dirpath, _, names in os.walk(apidir):
        rel = os.path.relpath(dirpath, apidir)
        if rel.startswith(("ahn", "search")):
            continue
        depth = 0 if rel == "." else rel.count(os.sep) + 1
        up = "../" * depth
        for name in names:
            if not name.endswith(".html"):
                continue
            p = os.path.join(dirpath, name)
            with open(p, encoding="utf-8", errors="replace") as f:
                html = f.read()
            out = inject_page(html, up + "../", "shop", up + "ahn/",
                              css=("shell.css", "api.css"), script=boot_script(up + "ahn/"))
            out = _api_crumb(out, name, up)
            out = _api_icon_links(out)
            if out != html:
                with open(p, "w", encoding="utf-8") as f:
                    f.write(out)
                n += 1
    print(f"inject.py: top bar on {n} API pages")


_ICON_LINK = re.compile(r'<a href="([^"]+)">(<span class="icon[a-z]*"></span>)</a>')


def _api_icon_links(html: str) -> str:
    """Doxygen's file list links each file's source with an icon and no text,
    which leaves the link without a name for a screen reader (axe link-name,
    #645). Name it after the page it opens."""
    def named(m: re.Match) -> str:
        href = m.group(1)
        base = os.path.basename(href).removesuffix(".html")
        if base.endswith("_source"):
            # Doxygen escapes the file name: "_" -> "__", "." -> "_8".
            label = "Source of " + base.removesuffix("_source").replace("_8", ".").replace("__", "_")
        else:
            label = base.replace("__", "_")
        return f'<a href="{href}" aria-label="{_html.escape(label)}">{m.group(2)}</a>'
    return _ICON_LINK.sub(named, html)


def _api_crumb(html: str, name: str, up: str) -> str:
    """Colony Arena › AntHocNet › Workshop › API reference › <page>, above Doxygen's own header."""
    if 'class="ahn-crumb"' in html or '<div id="top">' not in html:
        return html
    m = re.search(r"<title>(?:AntHocNet: )?([^<]*)</title>", html)
    title = _html.unescape(m.group(1).strip()) if m else name
    root = up + "../"
    items = [("AntHocNet", root), ("Workshop", root + "docs/places/workshop/")]
    items += [("API reference", None if name == "index.html" else up + "index.html")]
    if name != "index.html":
        items.append((title, None))
    return html.replace('<div id="top">', breadcrumb(items, "shop") + '<div id="top">', 1)


# --- docs (called from the mkdocs hook) ----------------------------------------
SECTION_PLACE = {"Field guide": "guide", "Lab": "lab", "Workshop": "shop", "Archive": "arch"}


def docs_page(html: str, page_url: str, section: str | None) -> str:
    depth = page_url.strip("/").count("/") + 1 if page_url.strip("/") else 0
    to_docs = "../" * depth
    return inject_page(html, to_docs + "../", SECTION_PLACE.get(section or ""),
                       to_docs + "assets/ahn/", css=("shell.css", "docs.css"),
                       script=boot_script(to_docs + "assets/ahn/"))


def docs_assets(site_dir: str) -> None:
    copy_assets(os.path.join(site_dir, "assets", "ahn"), ("docs.css",))


# --- self-test -----------------------------------------------------------------
def bar_of(html: str) -> str:
    """The bar's markup in a page."""
    m = re.search(r'<header class="ahn-bar".*?</header>', html, re.DOTALL)
    return m.group(0) if m else ""


def same_bar(html: str) -> str:
    """A bar with what may differ between two pages taken out: the
    current-place markers and the depth of the path to AntHocNet's root."""
    html = re.sub(r' aria-current="(?:page|true)"', "", html)
    return re.sub(r'((?:href|action|data-root)=")(?:\./|(?:\.\./)+|/AntHocNet/)', r"\1@/", html)


def self_test() -> None:
    import tempfile
    game_html = ('<!doctype html><html lang="en"><head><title>g</title></head><body>\n'
                 '<!--AHN-TOPBAR{}-->\n<main></main></body></html>')
    docs_html = '<!doctype html><html><head><title>d</title></head><body data-md-color-scheme="default"><main></main></body></html>'
    api_html = ('<html><head><title>AntHocNet: anthocnet::core::X Class Reference</title></head><body>'
                '<div id="top"></div><a href="x_8h_source.html"><span class="icon"></span></a></body></html>')
    with tempfile.TemporaryDirectory() as d:
        site = os.path.join(d, "site")
        apidir = os.path.join(d, "api")
        os.makedirs(site)
        os.makedirs(os.path.join(apidir, "search"))
        for name, place in (("index.html", ""), ("workshop.html", " shop")):
            with open(os.path.join(site, name), "w", encoding="utf-8") as f:
                f.write(game_html.format(place))
        for name in ("index.html", "classX.html", os.path.join("search", "all_0.html")):
            with open(os.path.join(apidir, name), "w", encoding="utf-8") as f:
                f.write(api_html)
        game(site)
        api(apidir)

        def read(*parts: str) -> str:
            with open(os.path.join(*parts), encoding="utf-8") as f:
                return f.read()
        pages = {
            "game": read(site, "index.html"),
            "workshop": read(site, "workshop.html"),
            "docs": docs_page(docs_html, "benchmarks/scenarios/vanet/", "Lab"),
            "docs home": docs_page(docs_html, "", None),
            "api": read(apidir, "classX.html"),
            "404": inject_page(docs_html, "/AntHocNet/", None, "/AntHocNet/docs/assets/ahn/", css=("shell.css", "docs.css")),
        }
        bars = {k: bar_of(v) for k, v in pages.items()}
        for k, html in pages.items():
            assert bars[k], f"{k}: no bar"
            assert not re.search(r"\{(?:ROOT|HUB|ON:|TOP:)", html) and "AHN-" not in html, f"{k}: a placeholder is left"
            # the same bar everywhere, apart from the current place and the depth
            assert same_bar(bars[k]) == same_bar(bars["game"]), f"{k}: its bar differs from the game's"
            # the hub, the projects and the references: one click away, each with a text label
            for href, label in ((HUB, "Colony&nbsp;Arena"), (HUB + "projects/", "Projects"),
                                (HUB + "references/", "References"), (HUB + "pipeline/", "How it runs")):
                assert re.search(rf'<a [^>]*href="{re.escape(href)}"[^>]*>(?:<span[^>]*></span>)?{label}</a>', bars[k]), (k, href)
            head = html[:html.index("</head>")]
            order = [head.index(a) for a in ("tokens.css", "shell.css", "theme.js")]
            assert order == sorted(order), f"{k}: tokens.css, shell.css, theme.js out of order"
            assert inject_page(html, "./", None, "shell/") == html, f"{k}: injecting twice changed the page"
        tops = re.findall(r'data-top="(\w+)"[^>]*?( aria-current="\w+")?[ >]', bars["game"])
        assert [t for t, _ in tops] == list(TOPS), tops
        # the current place: Play on the game; inside a place, the place, and Play as its section
        assert 'data-top="play" href="./"' + ' aria-current="page"' in bars["game"], bars["game"]
        assert bars["game"].count("aria-current") == 1, bars["game"]
        for k, place in (("workshop", "shop"), ("docs", "lab"), ("api", "shop")):
            assert re.search(rf'data-place="{place}"[^>]*aria-current="page"', bars[k]), (k, bars[k])
            assert bars[k].count('aria-current="page"') == 1 and 'href="' in bars[k], k
            assert re.search(r'data-top="play"[^>]*aria-current="true"', bars[k]), k
        assert 'href="../../../../docs/places/lab/"' in bars["docs"] and 'href="../docs/places/lab/"' in bars["api"], bars["docs"]
        assert 'href="/AntHocNet/docs/places/lab/"' in bars["404"], bars["404"]
        # assets beside each surface
        for parts in ((site, "shell"), (apidir, "ahn")):
            for a in ASSETS:
                assert os.path.isfile(os.path.join(*parts, a)), (parts, a)
        assert "ahn-bar" not in read(apidir, "search", "all_0.html")
        # the breadcrumb starts at the hub; the API's names its page
        crumb = breadcrumb([("AntHocNet", "../"), ("Lab", None), ("A <page>", None)], "lab")
        assert crumb.count("<li>") == 4 and f'<li><a href="{HUB}">Colony Arena</a></li><li><a href="../">AntHocNet</a></li>' in crumb, crumb
        assert '<span aria-current="page">A &lt;page&gt;</span>' in crumb and 'data-place="lab"' in crumb, crumb
        assert ">anthocnet::core::X Class Reference</span>" in pages["api"] and 'aria-label="Source of x.h"' in pages["api"]
    print("inject.py self-test: ok")


if __name__ == "__main__":
    if sys.argv[1:] == ["--self-test"]:
        self_test()
    elif len(sys.argv) in (3, 4) and sys.argv[1] == "bar":
        print(topbar(sys.argv[2], sys.argv[3] if len(sys.argv) == 4 else None))
    elif len(sys.argv) == 3 and sys.argv[1] in ("game", "api"):
        {"game": game, "api": api}[sys.argv[1]](sys.argv[2])
    else:
        sys.exit("usage: inject.py game <site-dir> | inject.py api <api-html-dir> | "
                 "inject.py bar <root> [place] | inject.py --self-test")
