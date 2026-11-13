#!/usr/bin/env python3
# Copyright (c) 2026 Daniel Joppi (https://github.com/swarm-routing)
# SPDX-License-Identifier: MIT OR GPL-2.0-only
"""Inline-SVG diagrams for the Colony Arena (tools/render_hub.py).

Every diagram is plain SVG with CSS classes only (no inline colours), so the
site's light and dark tokens theme it. Each one is a <figure> with an SVG of
role="img", a <title> and a <desc> for screen readers, and a caption. Ids are
prefixed with the diagram's id, so several diagrams share a page without
duplicate ids.

Kinds: UML package diagram, UML sequence diagram (with combined fragments),
UML class diagram, the hexagonal (ports and adapters) view, a pipeline, and
the org dependency graph. Stdlib only.
"""
from __future__ import annotations

import html
import math

E = html.escape


class Diagram:
    def __init__(self, did: str, w: int, h: int, title: str, desc: str, caption: str = ""):
        self.id, self.w, self.h = did, w, h
        self.title, self.desc, self.caption = title, desc, caption
        self.parts: list[str] = []

    # -- primitives --------------------------------------------------------
    def raw(self, s: str) -> None:
        self.parts.append(s)

    def text(self, x: float, y: float, s: str, cls: str = "d-t", anchor: str = "middle") -> None:
        self.parts.append(f'<text x="{x:.1f}" y="{y:.1f}" class="{cls}" text-anchor="{anchor}">{E(s)}</text>')

    def lines(self, x: float, y: float, rows: list[str], cls: str = "d-s", anchor: str = "middle", lh: float = 15) -> None:
        for i, r in enumerate(rows):
            self.text(x, y + i * lh, r, cls, anchor)

    def box(self, x, y, w, h, title="", rows=(), cls="", rx=8, stereo=None) -> None:
        self.parts.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{rx}" class="d-box {cls}"/>')
        ty = y + 20
        if stereo:
            self.text(x + w / 2, ty - 3, f"«{stereo}»", "d-st")
            ty += 13
        if title:
            self.text(x + w / 2, ty, title, "d-t")
        if rows:
            self.lines(x + w / 2, ty + 17, list(rows))

    def package(self, x, y, w, h, name, rows=(), stereo=None, cls="") -> None:
        """A UML package: a folder with a name tab."""
        tw = min(w * 0.6, max(60, 8.2 * len(name) + 18))
        self.parts.append(
            f'<path class="d-pkg {cls}" d="M{x},{y + 18} v{h - 18} h{w} v{-(h - 18)} h{-(w - tw)} '
            f'l-6,-18 h{-(tw - 6)} z"/>')
        self.text(x + 9, y + 14, name, "d-pt", "start")
        ty = y + 38
        if stereo:
            self.text(x + w / 2, ty, f"«{stereo}»", "d-st")
            ty += 16
        self.lines(x + w / 2, ty, list(rows))

    def edge(self, pts, cls="", label=None, head="h", lx=None, ly=None) -> None:
        d = "M" + " L".join(f"{px:.1f},{py:.1f}" for px, py in pts)
        mk = f' marker-end="url(#{self.id}-{head})"' if head else ""
        self.parts.append(f'<path d="{d}" class="d-edge {cls}"{mk}/>')
        if label:
            (x1, y1), (x2, y2) = pts[len(pts) // 2 - 1], pts[len(pts) // 2]
            self.text(lx if lx is not None else (x1 + x2) / 2, ly if ly is not None else (y1 + y2) / 2 - 6,
                      label, "d-el")

    # -- output ------------------------------------------------------------
    def render(self) -> str:
        i = self.id
        defs = (f'<defs><marker id="{i}-h" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="8" '
                f'markerHeight="8" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" class="d-head"/></marker>'
                f'<marker id="{i}-o" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="9" markerHeight="9" '
                f'orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10" class="d-open"/></marker>'
                f'<marker id="{i}-t" viewBox="0 0 12 12" refX="11" refY="6" markerWidth="11" markerHeight="11" '
                f'orient="auto-start-reverse"><path d="M0,0 L11,6 L0,12 z" class="d-tri"/></marker></defs>')
        svg = (f'<svg class="diagram" viewBox="0 0 {self.w} {self.h}" role="img" '
               f'aria-labelledby="{i}-title {i}-desc" preserveAspectRatio="xMidYMid meet" '
               f'style="max-width:{self.w}px">'
               f'<title id="{i}-title">{E(self.title)}</title><desc id="{i}-desc">{E(self.desc)}</desc>'
               f'{defs}{"".join(self.parts)}</svg>')
        cap = f"<figcaption>{self.caption}</figcaption>" if self.caption else ""
        return f'<figure class="fig" id="{i}"><div class="fig-scroll">{svg}</div>{cap}</figure>'


def clip(cx, cy, w, h, tx, ty):
    """Where the segment from a box's centre towards (tx, ty) leaves the box."""
    dx, dy = tx - cx, ty - cy
    if dx == 0 and dy == 0:
        return cx, cy
    sx = (w / 2) / abs(dx) if dx else math.inf
    sy = (h / 2) / abs(dy) if dy else math.inf
    s = min(sx, sy)
    return cx + dx * s, cy + dy * s


# -- UML package diagram ---------------------------------------------------
def packages(did, title, desc, caption, pkgs, deps, cols=3, cw=250, ch=150, gap=34):
    """pkgs: list of dicts {key, name, rows, stereo, col, row, planned}.
    deps: (from_key, to_key, label, kind) where kind is 'use' (dashed, open
    head, UML «use») or 'flow' (solid, filled head)."""
    rows = max(p["row"] for p in pkgs) + 1
    w = cols * cw + (cols + 1) * gap
    h = rows * ch + (rows + 1) * gap + 10
    d = Diagram(did, w, h, title, desc, caption)
    pos = {}
    for p in pkgs:
        x = gap + p["col"] * (cw + gap)
        y = gap + p["row"] * (ch + gap)
        pw = p.get("span", 1) * cw + (p.get("span", 1) - 1) * gap
        pos[p["key"]] = (x, y, pw, ch)
    for a, b, label, kind in deps:
        ax, ay, aw, ah = pos[a]
        bx, by, bw, bh = pos[b]
        acx, acy, bcx, bcy = ax + aw / 2, ay + ah / 2, bx + bw / 2, by + bh / 2
        p1 = clip(acx, acy, aw, ah, bcx, bcy)
        p2 = clip(bcx, bcy, bw, bh, acx, acy)
        if kind == "use":
            d.edge([p1, p2], "d-dash", label, "o")
        else:
            d.edge([p1, p2], "", label, "h")
    for p in pkgs:
        x, y, pw, ph = pos[p["key"]]
        d.package(x, y, pw, ph, p["name"], p.get("rows", ()), p.get("stereo"),
                  ("d-planned " if p.get("planned") else "") + p.get("cls", ""))
    return d.render()


# -- UML sequence diagram --------------------------------------------------
def sequence(did, title, desc, caption, actors, steps, col=200, row=32):
    """actors: lifeline names. steps, in order, one of:
      ("msg", a, b, label, style)   style: '' solid | 'back' dashed | 'data' | 'ctl'
      ("self", a, label)            a note on a lifeline (an action)
      ("frame", label, n)           a combined fragment around the next n steps
      ("gap",)                      a little vertical space
    """
    left = 90
    w = left + col * (len(actors) - 1) + 90
    y0 = 70
    # Measure height first.
    hgt = y0 + 20 + sum(row if s[0] != "gap" else 12 for s in steps) + 40
    d = Diagram(did, w, hgt, title, desc, caption)
    xs = [left + i * col for i in range(len(actors))]
    for x, a in zip(xs, actors):
        d.box(x - 58, 14, 116, 34, a, (), "d-actor", 6)
        d.raw(f'<line x1="{x}" y1="48" x2="{x}" y2="{hgt - 16}" class="d-life"/>')
    y = y0 + 14
    frames = []
    for s in steps:
        k = s[0]
        if k == "frame":
            frames.append([s[1], y - 18, s[2]])
            continue
        if k == "gap":
            y += 12
            continue
        if k == "msg":
            _, a, b, label, style = s
            xa, xb = xs[a], xs[b]
            off = 4 if xb > xa else -4
            cls = {"back": "d-dash d-back", "data": "d-data", "ctl": "d-ctl"}.get(style, "")
            d.edge([(xa + off, y), (xb - off, y)], cls, None, "h")
            d.text((xa + xb) / 2, y - 6, label, "d-el")
        elif k == "self":
            _, a, label = s
            d.raw(f'<rect x="{xs[a] - 6}" y="{y - 12}" width="12" height="18" class="d-act"/>')
            d.text(xs[a] + 12, y + 1, label, "d-note", "start")
        y += row
        for f in frames:
            if len(f) == 3:
                f[2] -= 1
                if f[2] == 0:
                    f.append(y - 12)
    for label, fy0, _n, fy1 in [f for f in frames if len(f) == 4]:
        d.raw(f'<rect x="12" y="{fy0}" width="{w - 24}" height="{fy1 - fy0}" class="d-frame"/>')
        tw = 8 * len(label) + 16
        d.raw(f'<path d="M12,{fy0} h{tw} v12 l-8,8 h{-(tw - 8)} z" class="d-ftab"/>')
        d.text(18, fy0 + 14, label, "d-ft", "start")
    return d.render()


# -- hexagonal (ports and adapters) view -----------------------------------
def hexagon(did, title, desc, caption, core_title, core_rows, ports, adapters, planned=False):
    """A core hexagon with its ports on the rim (half in, half out) and the
    adapters outside. adapters: list of (side, name, rows, licence), side 'l' or 'r'.
    Even-indexed ports sit on the left rim, odd ones on the right."""
    w, h = 1000, 400
    cx, cy, r = w / 2, h / 2, 165
    d = Diagram(did, w, h, title, desc, caption)
    pts = [(cx + r * math.cos(math.radians(a)), cy + r * 0.92 * math.sin(math.radians(a)))
           for a in range(0, 360, 60)]
    pl = "d-planned " if planned else ""
    d.raw('<polygon class="d-hex %s" points="%s"/>' % (pl, " ".join(f"{x:.1f},{y:.1f}" for x, y in pts)))
    d.text(cx, cy - 62, "«MIT OR GPL-2.0-only»", "d-st")
    d.text(cx, cy - 42, core_title, "d-t")
    d.lines(cx, cy - 18, core_rows)
    pw = 136
    rows = (len(ports) + 1) // 2
    ys = [cy - 46 * (rows - 1) / 2 + 46 * k for k in range(rows)]
    for i, p in enumerate(ports):
        side = -1 if i % 2 == 0 else 1
        py = ys[i // 2]
        px = cx + side * (r + 4)
        d.raw(f'<rect x="{px - pw / 2}" y="{py - 14}" width="{pw}" height="28" rx="14" class="d-box d-port {pl}"/>')
        d.text(px, py + 4, p, "d-s")
    for side, name, rows_, lic in adapters:
        ax = 16 if side == "l" else w - 196
        d.box(ax, cy - 72, 180, 144, name, rows_, "d-adapter " + pl, 8, lic)
        ex = ax + 180 if side == "l" else ax
        tx = cx - r - 4 - pw / 2 if side == "l" else cx + r + 4 + pw / 2
        d.edge([(ex, cy), (tx, cy)], "d-dash", None, "o")
        d.text((ex + tx) / 2, cy - 30, "implements", "d-el")
        d.text((ex + tx) / 2, cy - 16, "the ports", "d-el")
    d.text(cx, h - 14, "ports on the rim: the only way in or out of core/", "d-note")
    return d.render()


# -- pipeline ----------------------------------------------------------------
def pipeline(did, title, desc, caption, stages, notes=(), bw=150, bh=86, gap=36, wrap=5):
    """stages: list of (name, rows, cls). Wraps after `wrap` stages (snake)."""
    n = len(stages)
    ncol = min(n, wrap)
    nrow = (n + wrap - 1) // wrap
    w = 20 + ncol * bw + (ncol - 1) * gap + 20
    h = 30 + nrow * bh + (nrow - 1) * (gap + 10) + 30 + 18 * len(notes)
    d = Diagram(did, w, h, title, desc, caption)
    pos = []
    for i, (name, rows, cls) in enumerate(stages):
        r, c = divmod(i, wrap)
        if r % 2:
            c = wrap - 1 - c
        x = 20 + c * (bw + gap)
        y = 30 + r * (bh + gap + 10)
        pos.append((x, y))
        d.box(x, y, bw, bh, name, rows, cls)
    for i in range(n - 1):
        (x1, y1), (x2, y2) = pos[i], pos[i + 1]
        if y1 == y2:
            if x2 > x1:
                d.edge([(x1 + bw, y1 + bh / 2), (x2, y2 + bh / 2)])
            else:
                d.edge([(x1, y1 + bh / 2), (x2 + bw, y2 + bh / 2)])
        else:
            d.edge([(x1 + bw / 2, y1 + bh), (x2 + bw / 2, y2)])
    ny = h - 12 - 18 * (len(notes) - 1)
    for i, note in enumerate(notes):
        d.text(20, ny + 18 * i, note, "d-note", "start")
    return d.render()


# -- UML class diagram -----------------------------------------------------
def classes(did, title, desc, caption, groups, links, cw=200):
    """groups: list of (package_name, stereo, x, y, w, h, [cls...]) where cls is
    (name, stereo|None, [members], x, y). links: (from, to, kind, label) with
    kind 'real' (interface realisation), 'use' (dependency)."""
    w = max(g[2] + g[4] for g in groups) + 20
    h = max(g[3] + g[5] for g in groups) + 20
    d = Diagram(did, w, h, title, desc, caption)
    boxes = {}
    for name, stereo, gx, gy, gw, gh, items in groups:
        d.package(gx, gy, gw, gh, name, (), None, "d-planned d-group")
        d.text(gx + gw - 10, gy + 34, f"«{stereo}»", "d-st", "end")
        for cname, cst, members, x, y in items:
            ch = 30 + (14 if cst else 0) + 15 * len(members) + 8
            boxes[cname] = (x, y, cw, ch)
            d.raw(f'<rect x="{x}" y="{y}" width="{cw}" height="{ch}" class="d-box d-class"/>')
            ty = y + 17
            if cst:
                d.text(x + cw / 2, ty, f"«{cst}»", "d-st")
                ty += 14
            d.text(x + cw / 2, ty, cname, "d-t" + (" d-it" if cst == "interface" else ""))
            sep = ty + 8
            d.raw(f'<line x1="{x}" y1="{sep}" x2="{x + cw}" y2="{sep}" class="d-sep"/>')
            for i, m in enumerate(members):
                d.text(x + 8, sep + 15 + 15 * i, m, "d-m", "start")
    for a, b, kind, label in links:
        ax, ay, aw, ah = boxes[a]
        bx, by, bw, bh = boxes[b]
        p1 = clip(ax + aw / 2, ay + ah / 2, aw, ah, bx + bw / 2, by + bh / 2)
        p2 = clip(bx + bw / 2, by + bh / 2, bw, bh, ax + aw / 2, ay + ah / 2)
        if kind == "real":
            d.edge([p1, p2], "d-dash", label, "t")
        else:
            d.edge([p1, p2], "d-dash", label, "o")
    return d.render()


# -- the org graph -------------------------------------------------------------
ORG_NODES = {
    # id: (x, y, label, sublabel, layer)
    "AntHocNet": (110, 70, "AntHocNet", "protocol · live", "proto"),
    "ARA": (300, 70, "ARA", "protocol", "proto"),
    "BeeAdHoc": (490, 70, "BeeAdHoc", "protocol", "proto"),
    "Termite": (680, 70, "Termite", "protocol", "proto"),
    "HOPNET": (870, 70, "HOPNET", "protocol", "proto"),
    "ns3-swarm-core": (395, 215, "swarm-core", "shared module", "found"),
    "ns3-tools": (775, 215, "ns3-tools", "harness · readers", "tool"),
    "ns3-containers": (585, 330, "ns3-containers", "ns3-dev images", "infra"),
    "benchmarks": (870, 330, "benchmarks", "datasets · verdicts", "data"),
    "site": (110, 450, "Colony Arena", "this site", "site"),
    "org-commons": (300, 330, ".github", "reusable CI · templates", "commons"),
}
ORG_EDGES = [
    # (from, to, label): each one checked against the repositories (their AGENTS.md)
    ("ARA", "ns3-swarm-core", "links"),
    ("BeeAdHoc", "ns3-swarm-core", "links"),
    ("Termite", "ns3-swarm-core", "links"),
    ("HOPNET", "ns3-swarm-core", "links"),
    ("AntHocNet", "ns3-swarm-core", "extracts"),
    ("ARA", "ns3-tools", "arm"),
    ("BeeAdHoc", "ns3-tools", "arm"),
    ("Termite", "ns3-tools", "arm"),
    ("HOPNET", "ns3-tools", "arm"),
    ("AntHocNet", "ns3-tools", "bench"),  # routing-bench + readers at the ns3-tools.lock pin
    ("ns3-swarm-core", "ns3-containers", "builds in"),
    ("ns3-tools", "ns3-containers", "runs in"),
    ("ns3-tools", "benchmarks", "verdicts"),
    ("AntHocNet", "site", "core/ → WASM"),
    ("benchmarks", "site", "leaderboard (planned)"),  # site#12
    ("org-commons", "ns3-containers", "CI images"),  # reusable-ns3-ci runs in ns3-dev
]


def org_graph(did, highlight=None, caption=""):
    w, h = 980, 510
    desc = ("Dependency graph of the swarm-routing organisation. ARA, BeeAdHoc, Termite and HOPNET "
            "link against swarm-core, which was extracted from AntHocNet, and register as arms in ns3-tools; "
            "AntHocNet runs its benchmarks on ns3-tools' harness; swarm-core and ns3-tools build and run "
            "inside the ns3-containers images; ns3-tools writes verdicts into benchmarks; the Colony "
            "Arena site builds AntHocNet's core to WebAssembly and will render the benchmarks leaderboard; "
            "the .github repository's reusable CI runs inside the ns3-containers images.")
    d = Diagram(did, w, h, "The swarm-routing organisation: who depends on whom", desc, caption)
    bw, bh = 150, 52
    near = set()
    if highlight:
        for a, b, _ in ORG_EDGES:
            if highlight in (a, b):
                near |= {a, b}
    for a, b, label in ORG_EDGES:
        ax, ay = ORG_NODES[a][:2]
        bx, by = ORG_NODES[b][:2]
        p1 = clip(ax, ay, bw, bh, bx, by)
        p2 = clip(bx, by, bw, bh, ax, ay)
        hl = " d-hl" if highlight in (a, b) else (" d-dim" if highlight else "")
        # the protocols' edges fan into two boxes: a label near its target, not at the
        # midpoint, keeps two crossing edges from stacking their labels
        t = 0.5
        if ay == 70 and by == 215:
            t = {"ns3-swarm-core": 0.8, "ns3-tools": 0.4 if a == "AntHocNet" else 0.55}[b]
        lx, ly = p1[0] + (p2[0] - p1[0]) * t, p1[1] + (p2[1] - p1[1]) * t - 6
        d.edge([p1, p2], "d-dash" + hl, label or None, "o", lx, ly)
    for k, (x, y, label, sub, layer) in ORG_NODES.items():
        hl = " d-hl" if k == highlight else (" d-dim" if highlight and k not in near else "")
        d.raw(f'<rect x="{x - bw / 2}" y="{y - bh / 2}" width="{bw}" height="{bh}" rx="10" '
              f'class="d-box d-l-{layer}{hl}"/>')
        d.text(x, y - 3, label, "d-t")
        d.text(x, y + 14, sub, "d-s")
    d.text(20, h - 12, "dashed arrow: «use» dependency (UML); highlighted: this project and its neighbours",
           "d-note", "start")
    return d.render()
