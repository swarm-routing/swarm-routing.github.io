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
ORG_ROWS = (80, 225, 370, 515)  # the y of each row of regions, as on the colony map (render_hub.MAP_ROWS["wide"])
ORG_COL = [90 + 165 * i for i in range(8)]  # the x of each column: eight protocols side by side
ORG_NODES = {
    # id: (x, y, label, sublabel, layer); grouped as the map's regions (render_hub.REGIONS, #282).
    # A layer with " d-planned" draws a dashed box: a deferred repository with no code yet.
    "AntHocNet": (ORG_COL[0], 80, "AntHocNet", "protocol · live", "proto"),
    "ARA": (ORG_COL[1], 80, "ARA", "protocol", "proto"),
    "BeeAdHoc": (ORG_COL[2], 80, "BeeAdHoc", "protocol", "proto"),
    "Termite": (ORG_COL[3], 80, "Termite", "protocol", "proto"),
    "HOPNET": (ORG_COL[4], 80, "HOPNET", "protocol", "proto"),
    "POSANT": (ORG_COL[5], 80, "POSANT", "protocol · deferred", "proto d-planned"),
    "BeeSensor": (ORG_COL[6], 80, "BeeSensor", "protocol · deferred", "proto d-planned"),
    "Q-Swarm": (ORG_COL[7], 80, "Q-Swarm", "protocol · deferred", "proto d-planned"),
    "swarm-core": (ORG_COL[0], 225, "swarm-core", "ports · primitives", "found"),
    "swarm-adapter-ns3": (ORG_COL[1], 225, "swarm-adapter-ns3", "module swarm-core", "found"),
    "swarm-routingd": (ORG_COL[2], 225, "swarm-routingd", "Linux daemon · deferred", "found d-planned"),
    "swarm-adapter-omnet": (ORG_COL[3], 225, "swarm-adapter-omnet", "OMNeT++ · deferred", "found d-planned"),
    "vcpkg-registry": (ORG_COL[3], 370, "vcpkg-registry", "ports of the cores", "infra"),
    "benchmarks": (ORG_COL[4], 370, "benchmarks", "datasets · verdicts", "data"),
    "swarm-web-ui": (ORG_COL[5], 370, "swarm-web-ui", "workbench · deferred", "tool d-planned"),
    "sim-containers": (ORG_COL[6], 370, "sim-containers", "ns3-dev images", "infra"),
    "sim-tools": (ORG_COL[7], 370, "sim-tools", "harness · readers", "tool"),
    "site": (ORG_COL[0], 515, "Colony Arena", "this site", "site"),
    "ns3-upstream-report": (ORG_COL[1], 515, "ns3-upstream-report", "bridge to ns-3", "commons"),
    "org-commons": (ORG_COL[2], 515, ".github", "reusable CI · templates", "commons"),
    "swarm-mcp": (ORG_COL[3], 515, "swarm-mcp", "MCP server · read-only", "tool"),
    "skills": (ORG_COL[4], 515, "skills", "agent skills · plugin", "tool"),
}
ORG_ROUTES = {  # (from, to): the bends of an edge a straight line would draw through another box
    # (render_hub's self-test checks that no edge crosses a box it does not join)
    # AntHocNet -> the site: down the gap between swarm-core and swarm-adapter-ns3, under the Infra row, into the site
    ("AntHocNet", "site"): [(172, 150), (172, 445), (ORG_COL[0], 445)],
    # the two deferred runtimes -> swarm-core: under the adapters' row, then up into swarm-core
    ("swarm-routingd", "swarm-core"): [(ORG_COL[2], 282), (100, 282)],
    ("swarm-adapter-omnet", "swarm-core"): [(ORG_COL[3], 296), (80, 296)],
    # benchmarks -> the site: under the Infra row, then down into the site
    ("benchmarks", "site"): [(ORG_COL[4] - 20, 428), (ORG_COL[0] + 25, 428)],
    # .github -> sim-containers: above the bottom row, then up into the images
    ("org-commons", "sim-containers"): [(ORG_COL[2] + 30, 474), (ORG_COL[6] - 20, 474)],
    # swarm-adapter-ns3 -> sim-containers: under the adapters' row, then down into the images
    ("swarm-adapter-ns3", "sim-containers"): [(ORG_COL[1] + 40, 268), (ORG_COL[6], 268)],
    # sim-tools -> benchmarks and the upstream bridge -> sim-tools: under the Infra row
    ("sim-tools", "benchmarks"): [(ORG_COL[7] - 30, 412), (ORG_COL[4], 412)],
    ("ns3-upstream-report", "sim-tools"): [(ORG_COL[1], 458), (ORG_COL[7] + 30, 458)],
    # the released protocols -> sim-tools (their arms): one bus between the top two rows, down the right edge
    **{(p, "sim-tools"): [(ORG_COL[i] + 40, 165), (ORG_COL[7] + 50, 165), (ORG_COL[7] + 50, 300)]
       for i, p in enumerate(("AntHocNet", "ARA", "BeeAdHoc", "Termite", "HOPNET"))},
}
ORG_ROUTE_LABEL = {  # where a routed edge's label goes: on its long leg, between the rows
    ("AntHocNet", "site"): (128, 438), ("sim-tools", "benchmarks"): (790, 406),
    ("swarm-adapter-ns3", "sim-containers"): (800, 262), ("benchmarks", "site"): (430, 422), ("org-commons", "sim-containers"): (900, 468),
    ("ns3-upstream-report", "sim-tools"): (600, 452),
    # the five share the bus, so two labels say it all: AntHocNet's bench, the four others' arms
    ("AntHocNet", "sim-tools"): (960, 159), ("ARA", "sim-tools"): (1060, 159),
}
ORG_REGIONS = [  # (name, x0, x1, row): a labelled frame around each region's boxes
    ("Protocols", 8, 1332, 0), ("Core", 8, 170, 1), ("Adapters", 175, 667, 1), ("Infra", 503, 1332, 2),
    ("Others", 8, 502, 3), ("AI", 507, 832, 3),
]
ORG_EDGES = [
    # (from, to, label): each one checked against the repositories (their AGENTS.md);
    # the keys are the project ids (site/hub/projects.json), the repositories' names since the 2026-11-22 renames
    ("ARA", "swarm-adapter-ns3", "links"),
    ("BeeAdHoc", "swarm-adapter-ns3", "links"),
    ("Termite", "swarm-adapter-ns3", "links"),
    ("HOPNET", "swarm-adapter-ns3", "links"),
    ("AntHocNet", "swarm-adapter-ns3", "links"),  # AntHocNet ADR-0029: its ns-3 module derives from SwarmRoutingBase
    ("ARA", "sim-tools", "arm"),
    ("BeeAdHoc", "sim-tools", "arm"),
    ("Termite", "sim-tools", "arm"),
    ("HOPNET", "sim-tools", "arm"),
    ("AntHocNet", "sim-tools", "bench"),  # routing-bench + readers at the ns3-tools.lock pin (sim-tools)
    ("swarm-adapter-ns3", "sim-containers", "builds in"),
    ("sim-tools", "sim-containers", "runs in"),
    ("sim-tools", "benchmarks", "verdicts"),
    ("AntHocNet", "site", "core/ → WASM"),
    ("benchmarks", "site", "leaderboard (planned)"),  # site#12
    ("org-commons", "sim-containers", "CI images"),  # reusable-ns3-ci runs in ns3-dev
    ("swarm-mcp", "org-commons", "runs its scripts"),  # swarm-mcp AGENTS.md: each tool one .github script
    ("skills", "swarm-mcp", "bundles"),  # skills AGENTS.md (v0.35.0): .mcp.json runs swarm-mcp at swarm-mcp.lock's commit
    ("swarm-adapter-ns3", "swarm-core", "builds on"),  # swarm-adapter-ns3 AGENTS.md: swarm-core.lock, swarm::core PUBLIC
    ("swarm-routingd", "swarm-core", ""),  # swarm-routingd AGENTS.md: the cores on swarm-core's ports (deferred)
    ("swarm-adapter-omnet", "swarm-core", ""),  # swarm-adapter-omnet AGENTS.md: the adapter of swarm-core's ports (deferred)
    ("vcpkg-registry", "swarm-core", "ports"),  # vcpkg-registry README: the swarm-core port, from its release asset
    ("swarm-web-ui", "sim-containers", "runs in (planned)"),  # swarm-web-ui AGENTS.md: runs scenarios in sim-containers images
    ("ns3-upstream-report", "sim-tools", "register"),  # its AGENTS.md: one mirror ticket per NS3-NNN of the register
]


def org_edge_points(a, b, bw=150, bh=52):
    """The polyline of the org graph's edge a -> b: from a's box edge, through its bends, to b's box edge."""
    (ax, ay), (bx, by) = ORG_NODES[a][:2], ORG_NODES[b][:2]
    via = ORG_ROUTES.get((a, b), [])
    return [clip(ax, ay, bw, bh, *(via[0] if via else (bx, by))), *via,
            clip(bx, by, bw, bh, *(via[-1] if via else (ax, ay)))]


def org_graph(did, highlight=None, caption=""):
    w, h = 1340, 600
    desc = ("Dependency graph of the swarm-routing organisation, in the colony map's six regions: Protocols on top "
            "(AntHocNet, ARA, BeeAdHoc, Termite, HOPNET, and the deferred POSANT, BeeSensor and Q-Swarm); Core "
            "(swarm-core) and Adapters (swarm-adapter-ns3, and the deferred swarm-routingd and swarm-adapter-omnet) "
            "below them; then Infra (vcpkg-registry, benchmarks, the deferred swarm-web-ui, sim-containers, sim-tools); "
            "Others (this site, ns3-upstream-report, .github) and AI (swarm-mcp, skills) at the bottom. "
            "The five released protocols link the ns-3 module of swarm-adapter-ns3, which builds on swarm-core's "
            "release, and register as arms in sim-tools (AntHocNet runs its benchmarks on its harness); "
            "swarm-routingd and swarm-adapter-omnet will use swarm-core's ports; vcpkg-registry ports swarm-core; "
            "swarm-adapter-ns3 and sim-tools build and run inside the sim-containers images, where swarm-web-ui will "
            "run scenarios too; sim-tools writes verdicts into benchmarks; ns3-upstream-report carries sim-tools' "
            "register of ns-3 bugs upstream; the Colony Arena site builds AntHocNet's core to WebAssembly and will "
            "render the benchmarks leaderboard; the .github repository's reusable CI runs inside the sim-containers "
            "images; swarm-mcp, the org's MCP server, runs the .github repository's scripts, and the skills plugin bundles it.")
    d = Diagram(did, w, h, "The swarm-routing organisation: who depends on whom", desc, caption)
    bw, bh = 150, 52
    for name, x0, x1, row in ORG_REGIONS:
        y = ORG_ROWS[row]
        d.raw(f'<rect x="{x0}" y="{y - 50}" width="{x1 - x0}" height="100" rx="12" class="d-frame d-dash"/>')
        d.text(x0 + 10, y - 36, name, "d-s", "start")
    near = set()
    if highlight:
        for a, b, _ in ORG_EDGES:
            if highlight in (a, b):
                near |= {a, b}
    for a, b, label in ORG_EDGES:
        ax, ay = ORG_NODES[a][:2]
        bx, by = ORG_NODES[b][:2]
        via = ORG_ROUTES.get((a, b), [])
        p1, *_, p2 = org_edge_points(a, b, bw, bh)
        hl = " d-hl" if highlight in (a, b) else (" d-dim" if highlight else "")
        # the protocols' edges fan into two boxes: a label near its target, not at the
        # midpoint, keeps two crossing edges from stacking their labels
        t = 0.5
        if ay == ORG_ROWS[0]:
            t = {"swarm-adapter-ns3": 0.55, "sim-tools": 0.75}.get(b, 0.5)
        lx, ly = p1[0] + (p2[0] - p1[0]) * t, p1[1] + (p2[1] - p1[1]) * t - 6
        if ay == by:  # neighbours in a row: the gap is narrower than the label, so it goes under the arrow
            ly = ay + bh / 2 + 16
        if via:  # a routed edge: its label where the route puts it, between the rows (none: it shares another's)
            lx, ly = ORG_ROUTE_LABEL.get((a, b), (0, 0))
            label = label if (a, b) in ORG_ROUTE_LABEL else ""
        d.edge([p1, *via, p2], "d-dash" + hl, label or None, "o", lx, ly)
    for k, (x, y, label, sub, layer) in ORG_NODES.items():
        hl = " d-hl" if k == highlight else (" d-dim" if highlight and k not in near else "")
        d.raw(f'<rect x="{x - bw / 2}" y="{y - bh / 2}" width="{bw}" height="{bh}" rx="10" '
              f'class="d-box d-l-{layer}{hl}"/>')
        d.text(x, y - 3, label, "d-t")
        d.text(x, y + 14, sub, "d-s")
    d.text(20, h - 12, "dashed arrow: «use» dependency (UML); highlighted: this project and its neighbours",
           "d-note", "start")
    return d.render()
