#!/usr/bin/env python3
# Copyright (c) 2026 Daniel Joppi (https://github.com/swarm-routing)
# SPDX-License-Identifier: MIT OR GPL-2.0-only
"""One token file for the whole site (#97): fail when a style sheet defines a
colour, a radius or a font of its own.

The tokens are site/anthocnet/shell/tokens.css. Every other style sheet of
the site (the rest of site/anthocnet/shell/, site/anthocnet/site/css/,
site/hub/) may only use them:
  * no colour literal in a declaration: no #hex, no rgb()/hsl()/... function,
    no named colour (transparent, currentColor and inherit are not colours);
  * border-radius takes tokens (and 0, 50%, calc()) only;
  * font and font-family name no family: the stack is a token;
  * no custom property that tokens.css defines is defined again;
  * every var(--name) names a token, or a property the sheet defines itself
    (Material's own --md-* are the docs theme's).
In tokens.css itself, night is written twice (CSS cannot share a block
between prefers-color-scheme and [data-theme="dark"]): the two blocks must be
identical, and may only redefine what day defines.
The game's pages and scripts are read too: a var(--name) there must exist.

Usage: python3 tools/check_tokens.py            (this repository)
       python3 tools/check_tokens.py --self-test
Stdlib only.
"""
from __future__ import annotations

import os
import re
import sys
import tempfile
import time

ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
TOKENS = "site/anthocnet/shell/tokens.css"
SHEET_DIRS = ("site/anthocnet/shell", "site/anthocnet/site/css", "site/hub")
USE_DIRS = ("site/anthocnet/site", "site/hub")  # pages and scripts that name a token

COMMENT = re.compile(r"/\*.*?\*/", re.DOTALL)
DECL = re.compile(r"(?<![\w-])(--[\w-]+|[a-z-]+)\s*:\s*([^;{}]+?)\s*(?=[;}])")
HEX = re.compile(r"#[0-9a-fA-F]{3,8}\b")
FUNC = re.compile(r"\b(?:rgba?|hsla?|hwb|lab|lch|oklab|oklch|color)\(")
NAMED = re.compile(r"(?<![\w-])(?:black|white|red|green|blue|yellow|orange|purple|pink|brown|gr[ae]y|silver|gold|"
                   r"cyan|magenta|navy|teal|olive|maroon|lime|aqua|fuchsia|beige|ivory|khaki|coral|salmon|tomato|"
                   r"crimson|indigo|violet|orchid|plum|tan|wheat|linen|snow|azure|lavender|turquoise|chocolate|"
                   r"sienna|peru|(?!lighter(?![\w-]))(?:dark|light|medium|pale|deep|dim)[a-z]+)(?![\w-])")  # lighter is a font weight
FAMILY = re.compile(r"""["']|(?<![\w-])(?:system-ui|sans-serif|serif|monospace|cursive|fantasy|ui-[a-z-]+)(?![\w-])""")
# font-family is one token; font's shorthand ends with one (or is a global keyword)
FAMILY_OK = re.compile(r"(?:inherit|initial|unset|var\(--[\w-]+\))")
FONT_OK = re.compile(r"(?:inherit|initial|unset|(?:[^,\"'()]*\s)?var\(--[\w-]+\))")
RADIUS_OK = re.compile(r"(?:var\(--[\w-]+\)|calc\([^)]*\)|0|50%|inherit)(?:\s+|$)")
VAR = re.compile(r"var\(\s*(--[\w-]+)")
# a quoted string; one way to match each character, so no backtracking blow-up
STRING = re.compile(r""""[^"\\]*(?:\\.[^"\\]*)*"|'[^'\\]*(?:\\.[^'\\]*)*'""", re.DOTALL)


def declarations(css: str):
    """(property, value, line) of every declaration; selectors are skipped."""
    css = COMMENT.sub(lambda m: re.sub(r"[^\n]", " ", m.group(0)), css)
    for m in DECL.finditer(css):
        # a declaration follows "{" or ";", a selector's pseudo-class does not
        before = css[:m.start()].rstrip()
        if before and before[-1] not in "{;":
            continue
        yield m.group(1), m.group(2), css.count("\n", 0, m.start()) + 1


def night_blocks(css: str) -> list[str]:
    """The declarations of each night block of the token file, normalised."""
    css = COMMENT.sub("", css)
    out = []
    for m in re.finditer(r':root(?::not\(\[data-theme="light"\]\)|\[data-theme="dark"\])\s*\{([^{}]*)\}', css):
        out.append(" ".join(m.group(1).split()))
    return out


def day_block(css: str) -> str:
    m = re.search(r":root\s*\{([^{}]*)\}", COMMENT.sub("", css))
    return m.group(1) if m else ""


def check(root: str) -> list[str]:
    errs: list[str] = []
    tokens_path = os.path.join(root, TOKENS)
    if not os.path.isfile(tokens_path):
        return [f"{TOKENS}: missing"]
    with open(tokens_path, encoding="utf-8") as f:
        tokens_css = f.read()
    day = {p for p, _, _ in declarations(":root {" + day_block(tokens_css) + "}") if p.startswith("--")}
    blocks = night_blocks(tokens_css)
    if len(blocks) != 2:
        errs.append(f"{TOKENS}: expected two night blocks (prefers-color-scheme and [data-theme=dark]), found {len(blocks)}")
    elif blocks[0] != blocks[1]:
        a, b = (dict((p, v) for p, v, _ in declarations("x {" + blk + "}")) for blk in blocks)
        diff = sorted(k for k in set(a) | set(b) if a.get(k) != b.get(k))
        errs.append(f"{TOKENS}: the two night blocks differ ({', '.join(diff) or 'order or comments'})")
    for blk in blocks:
        extra = sorted({p for p, _, _ in declarations("x {" + blk + "}") if p.startswith("--")} - day)
        if extra:
            errs.append(f"{TOKENS}: night defines what day does not: {', '.join(extra)}")
    if not day:
        errs.append(f"{TOKENS}: no token defined")

    sheets = []
    for d in SHEET_DIRS:
        full = os.path.join(root, d)
        if os.path.isdir(full):
            sheets += [os.path.join(d, n) for n in sorted(os.listdir(full)) if n.endswith(".css")]
    for rel in sheets:
        if rel == TOKENS:
            continue
        with open(os.path.join(root, rel), encoding="utf-8") as f:
            css = f.read()
        decls = list(declarations(css))
        local = {p for p, _, _ in decls if p.startswith("--")}
        for prop, value, line in decls:
            where = f"{rel}:{line}: {prop}"
            bare = STRING.sub('""', re.sub(r"url\([^)]*\)", "", value))
            bare_names = VAR.sub("var(", bare)  # a token's name may hold a colour's name
            for rx, what in ((HEX, "a colour literal"), (FUNC, "a colour function"), (NAMED, "a named colour")):
                m = rx.search(bare_names)
                if m:
                    errs.append(f"{where}: {what} ({m.group(0).rstrip('(')}): use a token of {TOKENS}")
            if prop == "border-radius" and RADIUS_OK.sub("", bare.replace("!important", "").strip()):
                errs.append(f"{where}: {value}: a radius is a token (--r-*)")
            ok = FAMILY_OK if prop == "font-family" else FONT_OK
            if prop in ("font", "font-family") and (FAMILY.search(value) or not ok.fullmatch(value.replace("!important", "").strip())):
                errs.append(f"{where}: {value}: a font stack is a token (--font, --font-display, --mono)")
            if prop in day:
                errs.append(f"{where}: defined again outside {TOKENS}")
            for name in VAR.findall(value):
                if name not in day and name not in local and not name.startswith("--md-"):
                    errs.append(f"{where}: var({name}) is not a token")
    for d in USE_DIRS:
        for dirpath, _, names in os.walk(os.path.join(root, d)):
            for n in sorted(names):
                if not n.endswith((".html", ".js", ".mjs")):
                    continue
                path = os.path.join(dirpath, n)
                with open(path, encoding="utf-8") as f:
                    text = f.read()
                for name in sorted(set(VAR.findall(text))):
                    if name not in day:
                        errs.append(f"{os.path.relpath(path, root)}: var({name}) is not a token")
    return errs


def self_test() -> None:
    night = "--bg: #000; --r-md: 8px;"
    good_tokens = (":root { color-scheme: light; --bg: #fff; --ink: #111; --r-md: 10px; --font: system-ui, sans-serif; }\n"
                   "@media (prefers-color-scheme: dark) { :root:not([data-theme=\"light\"]) { " + night + " } }\n"
                   ":root[data-theme=\"dark\"] { " + night + " }\n")
    good_sheet = ("/* a comment with #fff and red in it */\n"
                  "#top a:hover, .x:not(.y) { color: var(--ink); background: color-mix(in srgb, var(--bg) 80%, transparent);\n"
                  "  border-radius: 0 var(--r-md) var(--r-md) 0; font: 700 14px/1.3 var(--font); white-space: nowrap;\n"
                  "  content: \"red › #abc\"; fill: url(#glow); border-color: currentColor; --heat: 0; opacity: var(--heat); }\n"
                  ".c { border-radius: 50%; } [data-md-color-scheme] { --md-primary-fg-color: var(--bg); color: var(--md-x); }\n")

    def run(tokens: str, sheet: str, page: str = "") -> list[str]:
        with tempfile.TemporaryDirectory() as d:
            for rel, text in ((TOKENS, tokens), ("site/hub/a.css", sheet), ("site/hub/p.html", page)):
                os.makedirs(os.path.dirname(os.path.join(d, rel)), exist_ok=True)
                with open(os.path.join(d, rel), "w", encoding="utf-8") as f:
                    f.write(text)
            return check(d)
    assert run(good_tokens, good_sheet, '<i style="background:var(--bg)"></i>') == [], run(good_tokens, good_sheet)
    for sheet, want in (
            (".a { color: #b4530f; }", "a colour literal (#b4530f)"),
            (".a { box-shadow: 0 1px 2px rgba(0, 0, 0, .2); }", "a colour function (rgba)"),
            (".a { background: linear-gradient(white, var(--bg)); }", "a named colour (white)"),
            (".a { color: darkorange; }", "a named colour (darkorange)"),
            (".a { border-radius: 14px; }", "a radius is a token"),
            (".a { border-radius: var(--r-md) 4px; }", "a radius is a token"),
            (".a { font: 600 14px system-ui, sans-serif; }", "a font stack is a token"),
            (".a { font-family: \"Inter\"; }", "a font stack is a token"),
            (":root { --bg: var(--ink); }", "--bg: defined again"),
            (".a { color: var(--nope); }", "var(--nope) is not a token"),
            (".a{color:#fff}", "a colour literal (#fff)"),
            (".a { color: lightblue; }", "a named colour (lightblue)"),
            (".a { color: lightgoldenrodyellow; }", "a named colour (lightgoldenrodyellow)"),
            (".a { color: lightgray; }", "a named colour (lightgray)"),
            (".a { font-family: Arial; }", "a font stack is a token"),
            (".a { font-family: var(--font), Arial; }", "a font stack is a token"),
            (".a { font: 12px Arial; }", "a font stack is a token")):
        got = run(good_tokens, sheet)
        assert any(want in e for e in got), (sheet, got)
    for sheet in (".a { font-weight: lighter; }", ".a { font-family: var(--font); font: inherit; }",
                  ".a { font: var(--font); }"):
        got = run(good_tokens, sheet)
        assert got == [], (sheet, got)
    assert any("var(--gone) is not a token" in e for e in run(good_tokens, good_sheet, '<i style="color:var(--gone)"></i>'))
    drift = good_tokens.replace(':root[data-theme="dark"] { --bg: #000;', ':root[data-theme="dark"] { --bg: #010;')
    assert any("night blocks differ (--bg)" in e for e in run(drift, good_sheet)), run(drift, good_sheet)
    extra = good_tokens.replace(night, night + " --only-night: #123;")
    assert any("night defines what day does not: --only-night" in e for e in run(extra, good_sheet)), run(extra, good_sheet)
    one = good_tokens.replace(':root[data-theme="dark"] { ' + night + " }\n", "")
    assert any("expected two night blocks" in e for e in run(one, good_sheet)), run(one, good_sheet)
    # a string that never closes, full of escapes, is read in linear time (CodeQL: no backtracking blow-up)
    t0 = time.perf_counter()
    run(good_tokens, '.a { content: "' + "\\a" * 50000 + '; }')
    assert time.perf_counter() - t0 < 1.0, "STRING backtracks on an unclosed string of escapes"
    assert STRING.sub('""', 'content: "a\\"b" x') == 'content: "" x'
    print("check_tokens.py self-test: ok")


def main(argv: list[str]) -> int:
    if argv == ["--self-test"]:
        self_test()
        return 0
    if argv:
        print(__doc__, file=sys.stderr)
        return 2
    errs = check(ROOT)
    for e in errs:
        print(e, file=sys.stderr)
    print(f"check_tokens.py: {'FAIL, ' + str(len(errs)) + ' problems' if errs else 'ok'}")
    return 1 if errs else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
