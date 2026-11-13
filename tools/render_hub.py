#!/usr/bin/env python3
# Copyright (c) 2026 Daniel Joppi (https://github.com/swarm-routing)
# SPDX-License-Identifier: MIT OR GPL-2.0-only
"""Render the Colony Arena hub and one space per org project (ADR-0001).

Reads site/hub/projects.json (the facts an issue cannot say), data/hub.json
(what the issues say: each public repository's epics, their sub-issue counts
and its latest release, written by tools/hub_data.py; a missing file, or a
repository missing from it, renders "status not available" and never fails
the build), protocols.lock (the pinned
commits) and each project's public repository's CITATION.cff and
docs/references.bib (fetched at the pinned commit, else at main; missing,
empty or unreachable: no Cite or References section, never a failed build),
writes:
  <out>/index.html                 the hub: the colony map, the quest log,
                                   how the colony is built
  <out>/projects/index.html        every project, one card each
  <out>/projects/<id>/index.html   a project's page: what it does, where it
                                   sits, its package structure, diagrams,
                                   how to cite it, its references
  <out>/references/index.html      every work the projects cite, once
  <out>/arena/{,<id>/}index.html   redirects: a project page was at
                                   /arena/<id>/ until #102
  <out>/arena/arena.{css,js}       the hub's assets (copied from site/hub/)
The map, the cards and every diagram are static HTML + SVG; arena.js only
adds the day/night switch, the map's focus card, the walking ants, and the
copy buttons and the filter of the citation and references sections.

Usage: python3 tools/render_hub.py <out-dir>
       python3 tools/render_hub.py --self-test
Stdlib only.
"""
from __future__ import annotations

import html
import http.client
import json
import os
import re
import shutil
import sys
import urllib.error
import urllib.request
from urllib.parse import urlsplit

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bib  # noqa: E402  (vendored from swarm-routing/.github tools/fidelity/bib.py)
import diagrams as dg  # noqa: E402
import lock  # noqa: E402

ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
HUB = os.path.join(ROOT, "site", "hub")
DATA = os.path.join(ROOT, "data", "hub.json")
E = html.escape
GH = "https://github.com/swarm-routing"
CURRENT = ' aria-current="page"'
PROJECTS = "projects"  # where a project page lives: /projects/<id>/ (was /arena/<id>/, #102)

STATUS = {"live": ("Unlocked", "st-live"), "building": ("Under construction", "st-build"),
          "planned": ("Locked", "st-lock"), "unknown": ("Status not available", "st-none")}
SITE_REPO = "swarm-routing.github.io"
KIND = {"protocol": "Protocol", "foundation": "Shared module", "tooling": "Tooling",
        "infrastructure": "Infrastructure", "data": "Data", "commons": "Org commons"}


def md(s: str) -> str:
    """The few marks projects.json uses: **bold**, `code`, [text](url)."""
    s = E(s, quote=False)
    s = re.sub(r"`([^`]+)`", r"<code>\1</code>", s)
    s = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", s)
    s = re.sub(r"\[([^\]]+)\]\(([^)\s]+)\)", r'<a href="\2">\1</a>', s)
    return s


# -- status, quests and the colony level: derived from data/hub.json, never typed (#104) --
def load_hub(path: str = DATA) -> dict:
    """data/hub.json, or {} when it is missing or unreadable (the build goes on)."""
    try:
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
        if not isinstance(d.get("repos"), dict) or not re.match(r"^\d{4}-\d\d-\d\d$", str(d.get("asOf"))):
            raise ValueError("no repos or no asOf date")
        return d
    except (OSError, ValueError, AttributeError) as e:
        print(f"render_hub.py: no issue data ({path}: {e}); every status reads 'status not available'", file=sys.stderr)
        return {}


def epic_status(e) -> str:
    """As swarm-routing/.github tools/epics/epics.py: Done / Dropped once the
    epic itself is closed; open, In progress with a sub-issue closed, else Planned."""
    if e["state"] == "closed":
        return "Dropped" if e.get("state_reason") == "not_planned" else "Done"
    return "In progress" if e["completed"] else "Planned"


def epic_title(title: str) -> str:
    """'[epic][protocol] ARA as …' and 'epic: …' -> the title alone (as epics.py)."""
    t = re.sub(r"^\s*(\[[^\]]*\]\s*)+", "", title)
    return re.sub(r"^\s*epic\s*:\s*", "", t, flags=re.I).strip()


def plural(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


def whole(r) -> bool:
    """A repository record with every field repo_status and the pages read, each of its type."""
    def text(d, *keys):
        return all(isinstance(d.get(k), str) and d[k] for k in keys)

    def epic(e):
        return (isinstance(e, dict) and text(e, "title", "url", "state")
                and all(type(e.get(k)) is int for k in ("number", "total", "completed")))
    if not isinstance(r, dict) or not text(r, "url") or not isinstance(r.get("epics"), list):
        return False
    rel = r.get("release")
    return all(epic(e) for e in r["epics"]) and (rel is None or (isinstance(rel, dict) and text(rel, "tag", "url")))


def repo_status(name: str, hubdata: dict) -> dict:
    """What data/hub.json says about one repository. The rule, in this order:
      unknown   the repository is not in the data (or there is no data), or its
                record lacks a field the pages read
      live      its latest release is 1.0.0 or later
      building  an epic is In progress
      live      it has epics, none is open, and at least one is Done
      building  it has a release (a 0.x one)
      planned   otherwise: only Planned epics, or none, and no release
    """
    r = (hubdata.get("repos") or {}).get(name)
    if not whole(r):
        return {"status": "unknown", "text": "", "epics": [], "release": None, "source": "", "done": 0, "total": 0}
    epics = [dict(e, status=epic_status(e)) for e in r["epics"]]
    n = {k: sum(e["status"] == k for e in epics) for k in ("In progress", "Planned", "Done", "Dropped")}
    rel = r.get("release")
    m = re.match(r"^v?(\d+)\.", rel["tag"]) if rel else None
    if m and int(m.group(1)) >= 1:
        status = "live"
    elif n["In progress"]:
        status = "building"
    elif epics and not n["Planned"] and n["Done"]:
        status = "live"
    elif rel:
        status = "building"
    else:
        status = "planned"
    if n["In progress"]:
        work = plural(n["In progress"], "epic") + " in progress" + (f", {n['Planned']} planned" if n["Planned"] else "")
    elif n["Planned"]:
        work = plural(n["Planned"], "epic") + " planned"
    else:
        work = "every epic closed" if epics else "no epic yet"
    return {"status": status, "text": (f"{rel['tag']} released, " if rel else "no release, ") + work,
            "epics": epics, "release": rel, "source": f"{r['url']}/issues?q=label%3Aepic",
            "done": sum(e["completed"] for e in epics), "total": sum(e["total"] for e in epics)}


def apply_status(data: dict, hubdata: dict) -> None:
    """Give every project and repository of projects.json its generated status."""
    data["hub"] = hubdata
    for p in data["projects"]:
        p["gen"] = repo_status(p["repo"].split("/", 1)[1], hubdata)
        p["status"], p["statusText"] = p["gen"]["status"], p["gen"]["text"]
    for r in data["repos"]:
        r["gen"] = repo_status(r["repo"], hubdata)


def chip(p) -> str:
    label, cls = STATUS[p["status"]]
    return f'<span class="chip {cls}">{E(label)}{": " + E(p["statusText"]) if p["statusText"] else ""}</span>'


def as_of(data) -> str:
    """The date of the issue data, as a <time> the crawler can find; '' with no data."""
    d = data["hub"].get("asOf")
    return f'<time data-asof datetime="{E(d)}">{E(d)}</time>' if d else ""


# -- glyphs: one small building per kind of place -------------------------------
def glyph(kind: str) -> str:
    g = {
        "mound": '<path class="g-earth" d="M-46,22 C-40,-18 -18,-34 0,-34 C18,-34 40,-18 46,22 Z"/>'
                 '<ellipse class="g-hole" cx="0" cy="8" rx="9" ry="7"/><ellipse class="g-hole" cx="-19" cy="14" rx="5" ry="4"/>'
                 '<ellipse class="g-hole" cx="18" cy="-8" rx="5" ry="4"/>',
        "hive": "".join(f'<polygon class="g-wax" points="{_hexpts(x, y, 13)}"/>' for x, y in
                        [(-22, 6), (0, 6), (22, 6), (-11, -13), (11, -13), (0, -32)])
                + '<ellipse class="g-hole" cx="0" cy="8" rx="5" ry="4"/>',
        "spire": '<path class="g-clay" d="M-34,22 L-14,-12 L-8,-44 L0,-24 L8,-52 L14,-14 L34,22 Z"/>'
                 '<ellipse class="g-hole" cx="0" cy="12" rx="7" ry="6"/>',
        "zones": '<circle class="g-zone" cx="0" cy="-6" r="34"/><circle class="g-zone" cx="0" cy="-6" r="20"/>'
                 '<rect class="g-stone" x="-5" y="-30" width="10" height="48" rx="2"/>'
                 '<circle class="g-beacon" cx="0" cy="-32" r="5"/>',
        "chamber": '<rect class="g-stone" x="-44" y="-6" width="88" height="28" rx="4"/>'
                   '<path class="g-crown" d="M-18,-10 L-18,-30 L-9,-20 L0,-34 L9,-20 L18,-30 L18,-10 Z"/>',
        "lab": '<path class="g-glass" d="M-10,-40 h20 v16 l20,40 a6,6 0 0 1 -5,8 h-50 a6,6 0 0 1 -5,-8 l20,-40 z"/>'
               '<path class="g-liquid" d="M-22,6 h44 l7,14 a5,5 0 0 1 -4,4 h-50 a5,5 0 0 1 -4,-4 z"/>',
        "foundry": '<rect class="g-crate" x="-44" y="-2" width="40" height="24" rx="2"/>'
                   '<rect class="g-crate2" x="2" y="-2" width="40" height="24" rx="2"/>'
                   '<rect class="g-crate3" x="-22" y="-28" width="40" height="24" rx="2"/>'
                   '<path class="g-stroke" d="M-38,4 v12 M-28,4 v12 M-18,4 v12 M8,4 v12 M18,4 v12 M28,4 v12 M-16,-22 v12 M-6,-22 v12 M4,-22 v12"/>',
        "archive": '<rect class="g-stone" x="-40" y="-36" width="80" height="58" rx="4"/>'
                   '<path class="g-stroke" d="M-32,-20 h64 M-32,-4 h64 M-32,12 h64"/>'
                   '<rect class="g-book" x="-28" y="-33" width="7" height="12"/><rect class="g-book2" x="-19" y="-33" width="7" height="12"/>'
                   '<rect class="g-book" x="6" y="-17" width="7" height="12"/><rect class="g-book2" x="-10" y="-1" width="7" height="12"/>',
        "hall": '<path class="g-roof" d="M-46,-14 L0,-40 L46,-14 Z"/><rect class="g-stone" x="-40" y="-14" width="80" height="36"/>'
                '<path class="g-stroke" d="M-28,-10 v30 M-12,-10 v30 M12,-10 v30 M28,-10 v30"/>',
        "arena": '<ellipse class="g-arena" cx="0" cy="6" rx="46" ry="18"/><ellipse class="g-sand" cx="0" cy="4" rx="30" ry="10"/>'
                 '<path class="g-flag" d="M0,-6 v-34 l18,7 l-18,7"/>',
    }
    return g[kind]


def _hexpts(x, y, r):
    import math
    return " ".join(f"{x + r * math.cos(math.radians(a)):.1f},{y + r * math.sin(math.radians(a)):.1f}"
                    for a in range(30, 390, 60))


# -- the colony map ---------------------------------------------------------------
MAP = {  # id: (x, y) on a 1200 x 640 field
    "AntHocNet": (170, 170), "ARA": (390, 120), "BeeAdHoc": (640, 110), "Termite": (880, 135),
    "HOPNET": (1070, 220), "ns3-swarm-core": (520, 300), "ns3-tools": (860, 340),
    "ns3-containers": (640, 500), "benchmarks": (1010, 500), "org-commons": (320, 500),
    "site": (150, 420),
}
TRAILS = [  # pheromone trails = the dependency graph (diagrams.ORG_EDGES)
    (a, b) for a, b, _ in dg.ORG_EDGES
]


def colony_map(projects, site) -> str:
    by = {p["id"]: p for p in projects + [site]}
    trails = []
    for i, (a, b) in enumerate(TRAILS):
        (x1, y1), (x2, y2) = MAP[a], MAP[b]
        mx, my = (x1 + x2) / 2, (y1 + y2) / 2 + 28
        live = all(by[k]["status"] in ("live", "building") for k in (a, b))
        trails.append(f'<path id="trail-{i}" class="trail{" trail-live" if live else ""}" '
                      f'd="M{x1},{y1 + 18} Q{mx},{my} {x2},{y2 + 18}"/>')
    places = []
    for p in projects + [site]:
        x, y = MAP[p["id"]]
        label, cls = STATUS[p["status"]]
        href = p.get("href") or f"{PROJECTS}/{p['id']}/"
        aria = f"{p['name']}: {p['place']}, {KIND.get(p['kind'], p['kind'])}. {label}{', ' + p['statusText'] if p['statusText'] else ''}."
        lockmark = ('<g class="padlock" transform="translate(34,-34)"><rect x="-8" y="-2" width="16" height="13" rx="2"/>'
                    '<path d="M-5,-2 v-4 a5,5 0 0 1 10,0 v4"/></g>') if p["status"] == "planned" else ""
        scaffold = ('<path class="scaffold" d="M-50,24 L-50,-44 M50,24 L50,-44 M-50,-10 H50 M-50,-44 L50,24 M50,-44 L-50,24"/>'
                    if p["status"] == "building" else "")
        places.append(
            f'<a class="place {cls}" href="{E(href)}" data-id="{E(p["id"])}" data-status="{p["status"]}" aria-label="{E(aria)}">'
            f'<g transform="translate({x},{y})"><ellipse class="pad" cx="0" cy="24" rx="64" ry="18"/>'
            f'<g class="bld">{glyph(p["glyph"])}</g>{scaffold}{lockmark}'
            f'<g class="tag"><rect x="-70" y="40" width="140" height="38" rx="9"/>'
            f'<text x="0" y="57" class="tag-t">{E(p["name"])}</text>'
            f'<text x="0" y="71" class="tag-s">{E(p["place"])} · {E(label)}</text></g></g></a>')
    return (
        '<div class="map-wrap"><svg class="colony" viewBox="0 0 1200 640" role="group" '
        'aria-label="The colony map: every swarm-routing project as a place; trails are dependencies">'
        '<defs><radialGradient id="map-glow" cx="50%" cy="40%" r="70%"><stop offset="0" class="sky0"/>'
        '<stop offset="1" class="sky1"/></radialGradient></defs>'
        '<rect class="field" x="0" y="0" width="1200" height="640" rx="22" fill="url(#map-glow)"/>'
        '<g class="dirt">' + "".join(
            f'<circle cx="{(i * 137) % 1200}" cy="{(i * 251) % 640}" r="{1 + i % 3}"/>' for i in range(70)) + '</g>'
        '<g class="trails">' + "".join(trails) + '</g><g class="ants" aria-hidden="true"></g>'
        '<g class="places">' + "".join(places) + '</g></svg>'
        '<aside class="map-card" id="map-card" aria-live="polite"><p class="mc-k">Pick a place</p>'
        '<p class="mc-t">Hover or tab through the colony.</p><p class="mc-s">Every building is a project of the '
        'organisation; every trail is a dependency an ant walks.</p></aside></div>')


def site_place(hubdata: dict) -> dict:
    """This site as a place on the map; its status from its own repository's issues."""
    gen = repo_status(SITE_REPO, hubdata)
    return {"id": "site", "name": "Colony Arena", "place": "Arena", "glyph": "arena", "kind": "site",
            "status": gen["status"], "statusText": gen["text"], "gen": gen, "href": "#build"}


# -- per-project diagrams ---------------------------------------------------------------
ANT_PORTS = ["IClock", "IRng", "INeighborProvider", "ITimerScheduler", "ILinkState", "IRouterObserver"]
PLANNED_PORTS = ["clock port", "rng port", "neighbour port", "timer port", "link-state port", "observer port"]


def protocol_hex(pid, live, core_rows, module):
    adapters = [("l", "ns-3 adapter", [f"contrib module {module}", "header ⇄ message", "timers, queue",
                                       "on swarm-core"], "GPL-2.0-only")]
    if live:
        adapters.append(("r", "browser adapter", ["core/ → WebAssembly", "-ffp-contract=off",
                                                  "detSin / detCos", "this site"], "GPL-2.0-only"))
    else:
        adapters.append(("r", "browser adapter", ["core/ → WebAssembly", "when the protocol", "reaches the site",
                                                  "(site#13)"], "GPL-2.0-only"))
    return dg.hexagon(
        f"{pid}-hex", f"{pid}: hexagonal architecture",
        f"{pid}'s simulator-agnostic core in the centre, reached only through ports; the ns-3 module and the "
        f"browser adapter outside only convert headers and carry out the core's route decisions.",
        "Ports and adapters: <code>core/</code> includes no simulator header; time, randomness, neighbours "
        "and timers arrive through ports, and every adapter only carries out the core's decisions."
        + ("" if live else " Dashed: planned."),
        "core/", core_rows, ANT_PORTS if pid == "AntHocNet" else PLANNED_PORTS, adapters, planned=not live)


def protocol_pkgs(pid, module, live, tree=()):
    """`tree` is the project's package table (projects.json): a package the
    table has as present is drawn solid, whether or not this site builds it."""
    def planned(*paths):
        return not any(row[0] in paths and row[3] == "present" for row in tree)
    pk = [
        {"key": "core", "name": "core", "stereo": "MIT OR GPL-2.0-only", "col": 0, "row": 0,
         "rows": ["algorithm, messages, codec", "ports (injected)", "unit tests"], "planned": planned("core/")},
        {"key": "ns3", "name": f"ns3::{module}", "stereo": "GPL-2.0-only", "col": 1, "row": 0,
         "rows": ["header codec, adapter", "helper, examples", "test.py suite"], "planned": planned("ns3/", f"ns3/{module}/")},
        {"key": "swarm", "name": "swarm-core", "stereo": "ns-3 contrib module", "col": 2, "row": 0,
         "rows": ["PheromoneTable, VisitedPath", "wire helpers, RouteDecision", "SwarmRoutingBase"],
         "planned": True, "cls": "d-ext"},
        {"key": "docs", "name": "docs", "stereo": "GPL-2.0-only", "col": 0, "row": 1,
         "rows": ["fidelity sheet", "paper § → implementation", "parameters with sources"], "planned": planned("docs/", "docs/fidelity.md")},
        {"key": "bench", "name": "ns3-tools::routing-bench", "stereo": "harness", "col": 1, "row": 1,
         "rows": ["arm registration", "##RUN## / ##BENCH## lines"], "cls": "d-ext"},
        {"key": "site", "name": "Colony Arena", "stereo": "this site", "col": 2, "row": 1,
         "rows": ["core/ → WebAssembly", "pinned in protocols.lock"], "cls": "d-ext", "planned": not live},
    ]
    deps = [("ns3", "core", "«use»", "use"), ("ns3", "swarm", "«use»", "use"), ("core", "swarm", "«use»", "use"),
            ("ns3", "bench", "registers arm", "flow"), ("site", "core", "builds", "use"),
            ("docs", "core", "cites", "use")]
    if pid == "AntHocNet":
        pk[2]["rows"] = ["primitives extracted", "from AntHocNet core/", "(Phase 2)"]
        deps = [d for d in deps if d[1] != "swarm"] + [("core", "swarm", "extracted into", "flow")]
    return dg.packages(
        f"{pid}-pkg", f"{pid}: package diagram",
        f"UML package diagram of {pid}: the core package, the ns-3 module that uses it, the shared "
        f"swarm-core module, the docs, the ns3-tools harness the module registers with, and this site.",
        "Package diagram (UML): dashed arrows are «use» dependencies; the licence of each package is its "
        "stereotype. The dependency never points from <code>core</code> to GPL-only code."
        + ("" if live else " Dashed outlines: planned."), pk, deps)


SEQ = {
    "AntHocNet": dict(
        actors=["source S", "node 1", "node 2", "destination D"],
        steps=[("self", 0, "data for D, no pheromone"),
               ("frame", "opt [no route: reactive set-up]", 6),
               ("msg", 0, 1, "reactive forward ant (broadcast)", "ctl"),
               ("msg", 1, 2, "forward ant, visited[] grows", "ctl"),
               ("msg", 2, 3, "forward ant", "ctl"),
               ("msg", 3, 2, "backward ant: deposit τ(2→D)", "back"),
               ("msg", 2, 1, "backward ant: deposit τ(1→2)", "back"),
               ("msg", 1, 0, "backward ant: deposit τ(S→1)", "back"),
               ("msg", 0, 1, "data, next hop drawn ∝ τ^β", "data"),
               ("msg", 1, 2, "data", "data"),
               ("msg", 2, 3, "data", "data"),
               ("frame", "loop [every ProactiveInterval while the session lives]", 2),
               ("msg", 0, 1, "proactive forward ant (unicast, may broadcast)", "ctl"),
               ("msg", 1, 0, "… backward ant refreshes pheromone", "back"),
               ("frame", "alt [link 1→2 breaks]", 2),
               ("self", 1, "repair ant if no other route, else …"),
               ("msg", 1, 0, "LinkFail: discount τ via 1", "ctl")]),
    "ARA": dict(
        actors=["source S", "node 1", "node 2", "destination D"],
        steps=[("frame", "opt [route discovery]", 6),
               ("msg", 0, 1, "FANT (flooded, seq no.)", "ctl"),
               ("msg", 1, 2, "FANT: pheromone back to S", "ctl"),
               ("msg", 2, 3, "FANT", "ctl"),
               ("msg", 3, 2, "BANT: pheromone towards D", "back"),
               ("msg", 2, 1, "BANT", "back"),
               ("msg", 1, 0, "BANT", "back"),
               ("frame", "loop [route maintenance: no ants]", 3),
               ("msg", 0, 1, "data: reinforces τ(S→1)", "data"),
               ("msg", 1, 2, "data: reinforces τ(1→2)", "data"),
               ("self", 2, "τ evaporates on every link over time"),
               ("frame", "alt [link 1→2 fails]", 2),
               ("self", 1, "try another next hop"),
               ("msg", 1, 0, "route error (if none left)", "ctl")]),
    "BeeAdHoc": dict(
        actors=["dance floor at S", "packer at S", "node 1", "destination D"],
        steps=[("self", 1, "packer holds data for D"),
               ("frame", "opt [no forager knows D]", 4),
               ("msg", 1, 2, "scout (broadcast)", "ctl"),
               ("msg", 2, 3, "scout", "ctl"),
               ("msg", 3, 2, "returning scout carries the path", "back"),
               ("msg", 2, 0, "scout dances: path to D", "back"),
               ("msg", 0, 1, "foragers recruited ∝ dance", "ctl"),
               ("msg", 1, 2, "forager carries data (source route)", "data"),
               ("msg", 2, 3, "forager: data delivered", "data"),
               ("msg", 3, 2, "forager returns: delay, battery", "back"),
               ("msg", 2, 0, "forager dances by route quality", "back")]),
    "Termite": dict(
        actors=["node A", "node 1", "node 2", "node B"],
        steps=[("msg", 0, 1, "data A→B carries A's pheromone", "data"),
               ("self", 1, "τ(→A via A) ↑"),
               ("msg", 1, 2, "data, next hop drawn ∝ τ", "data"),
               ("self", 2, "τ(→A via 1) ↑"),
               ("msg", 2, 3, "data delivered", "data"),
               ("self", 3, "τ(→A via 2) ↑: a route home for free"),
               ("msg", 3, 2, "data B→A follows τ(→A)", "data"),
               ("msg", 2, 1, "… and lays τ(→B)", "data"),
               ("self", 1, "all τ decays with time"),
               ("msg", 1, 0, "data delivered", "data")]),
    "HOPNET": dict(
        actors=["source S", "border of S's zone", "border of next zone", "destination D"],
        steps=[("frame", "loop [inside each zone: proactive]", 1),
               ("self", 0, "local ants keep intrazone routes"),
               ("frame", "opt [D outside S's zone: reactive]", 4),
               ("msg", 0, 1, "forward ant to a border node", "ctl"),
               ("msg", 1, 2, "ant hops zone to zone", "ctl"),
               ("msg", 2, 3, "D inside this zone: intrazone route", "ctl"),
               ("msg", 3, 0, "backward ant: pheromone along borders", "back"),
               ("msg", 0, 3, "data along the zone path", "data")]),
}


def project_diagrams(p, pins) -> list[str]:
    pid = p["id"]
    out = []
    if p["kind"] == "protocol":
        live = pid in pins  # drawn from the code this site builds at its pin, else from the paper
        s = SEQ[pid]
        out.append(dg.sequence(
            f"{pid}-seq", f"{pid}: how a route forms (UML sequence diagram)",
            f"Sequence diagram of {pid}'s mechanism across {len(s['actors'])} lifelines: " + "; ".join(
                st[3] if st[0] == "msg" else st[2] for st in s["steps"] if st[0] in ("msg", "self")) + ".",
            "Sequence diagram (UML): solid arrows are control messages, dashed arrows return, bold arrows "
            "carry data; boxes are combined fragments (<code>opt</code>, <code>loop</code>, <code>alt</code>). "
            + ("Read from AntHocNet's <code>core/</code> and its ant-types page." if live else
               "Drawn from the paper; the repository's fidelity sheet is the authority once written."),
            s["actors"], s["steps"]))
        module = {"AntHocNet": "anthocnet"}.get(pid, pid.lower())
        rows = {
            "AntHocNet": ["AntRouterLogic::onReceiveAnt", "PheromoneEngine, PheromoneTable",
                          "AntMessage codec (kWireVersion)", "VisitedPath, AntHistory"],
            "ARA": ["FANT / BANT handling", "pheromone + evaporation", "duplicate detection"],
            "BeeAdHoc": ["packer, scout, forager", "dance floor", "delay + energy metrics"],
            "Termite": ["pheromone on data packets", "randomised forwarding", "decay"],
            "HOPNET": ["zone membership", "intrazone tables", "border-hopping ants"],
        }[pid]
        out.append(protocol_hex(pid, live, rows, module))
        out.append(protocol_pkgs(pid, module, live, p.get("tree", ())))
    elif pid == "ns3-swarm-core":
        out.append(dg.classes(
            "swarm-core-cls", "swarm-core: planned primitives and glue (UML class diagram)",
            "Class diagram of swarm-core's planned API. In core, simulator-free: VisitedPath, PheromoneTable, "
            "RouteDecision, the ILinkState and ILinkMetric interfaces, evaporation and roulette selection. In "
            "model, the ns-3 glue: SwarmRoutingBase, DeferredPacketQueue, WifiLinkMonitor realising ILinkState, "
            "EnergyMetricHook and IslLinkMonitor.",
            "Class diagram (UML) of the planned API (dashed: not written yet; ns3-swarm-core#8, #9). Hollow "
            "triangles: interface realisation; open arrows: «use». Only <code>model</code> includes "
            "<code>ns3/*</code>.",
            [("core", "MIT OR GPL-2.0-only", 20, 20, 470, 470, [
                ("VisitedPath", None, ["+ push(node) : bool", "+ contains(node) : bool", "- cap : size_t"], 40, 70),
                ("PheromoneTable", None, ["+ get(dst, via) : double", "+ deposit(dst, via, Δτ)", "+ evaporate(ρ)"], 270, 70),
                ("RouteDecision", None, ["+ action : Forward|Drop|Queue", "+ nextHop : NodeId"], 40, 210),
                ("roulette", "function", ["+ pick(weights, rng)"], 270, 220),
                ("ILinkState", "interface", ["+ isUp(nbr) : bool"], 40, 340),
                ("ILinkMetric", "interface", ["+ cost(nbr) : double"], 270, 340)]),
             ("model", "GPL-2.0-only · ns-3", 520, 20, 470, 470, [
                ("SwarmRoutingBase", None, ["ns3::Ipv4RoutingProtocol", "+ execute(RouteDecision)"], 540, 70),
                ("DeferredPacketQueue", None, ["+ enqueue(p, dst)", "- cap : size_t"], 770, 70),
                ("WifiLinkMonitor", None, ["MAC tx-failure traces"], 540, 210),
                ("IslLinkMonitor", None, ["satellite ISL state"], 770, 210),
                ("EnergyMetricHook", None, ["ns3::EnergySource"], 655, 340)])],
            [("WifiLinkMonitor", "ILinkState", "real", ""), ("IslLinkMonitor", "ILinkState", "real", ""),
             ("EnergyMetricHook", "ILinkMetric", "real", ""), ("SwarmRoutingBase", "RouteDecision", "use", "«use»"),
             ("PheromoneTable", "roulette", "use", ""), ("SwarmRoutingBase", "DeferredPacketQueue", "use", "")]))
        out.append(dg.pipeline(
            "swarm-core-gate", "swarm-core: the determinism gate",
            "The determinism gate: build swarm-core-seed, run it with seed 1 twice and compare the output byte "
            "for byte, then run seed 2 and require a difference.",
            "The determinism gate every run of its CI has (org invariant 5).",
            [("build", ["ns3-build-contrib", "--strict-warnings"], ""), ("seed=1", ["run A"], ""),
             ("seed=1", ["run B"], ""), ("cmp A B", ["byte-identical"], "d-good"),
             ("seed=2", ["must differ"], "d-good")], bw=150, wrap=5))
    elif pid == "ns3-tools":
        out.append(dg.pipeline(
            "tools-flow", "ns3-tools: from an arm to a verdict",
            "Data flow through ns3-tools: a protocol's module registers an arm through its bench-arms helper; "
            "routing-bench runs the scenario over at least twenty seeds per arm and prints the versioned marker "
            "lines; the stdlib readers parse them, pair runs by seed and compute deltas and a noise verdict; the "
            "result is written into the benchmarks repository with its manifest.",
            "Data flow: the marker lines are a versioned contract (fields only appended), and every verdict is "
            "a script's output, never an eyeballed number.",
            [("arm", ["helper/<m>-", "bench-arms.cc"], ""), ("routing-bench", ["routing-compare", "≥ 20 seeds"], ""),
             ("marker lines", ["##CONFIG## ##RUN##", "##BENCH## ##DIAG##"], "d-contract"),
             ("ns3_tool", ["bench_parse", "stats_util, pool_runs"], ""),
             ("verdict", ["paired Δ per seed", "noise call"], "d-good"),
             ("benchmarks", ["runs/ + manifest", "verdicts/"], "d-ext")], bw=150, wrap=6))
        out.append(dg.packages(
            "tools-pkg", "ns3-tools: package diagram",
            "UML package diagram of ns3-tools: the routing-bench harness module, the planned comparator arm "
            "modules and probes, the ns3_tool Python readers and their tests, and the ns3-dev images they run in.",
            "Package diagram (UML). Each comparator arm is its own module that registers exactly as an "
            "out-of-repo arm does; no code outside its directory names it. Dashed: planned.",
            [{"key": "rb", "name": "ns3::routing-bench", "stereo": "GPL-2.0-only", "col": 0, "row": 0,
              "rows": ["routing-compare", "arm registry", "marker emitters"]},
             {"key": "arms", "name": "ns3/arms/<name>", "stereo": "GPL-2.0-only", "col": 1, "row": 0,
              "rows": ["SAODV, SEAD, TAODV", "DRL, DTN", "one module each"], "planned": True},
             {"key": "probe", "name": "ns3 probes + arenas", "stereo": "GPL-2.0-only", "col": 2, "row": 0,
              "rows": ["TopologyOracle", "DropCauseClassifier", "manet-, leo-walker-arena"], "planned": True},
             {"key": "py", "name": "python/ns3_tool", "stereo": "MIT OR GPL-2.0-only", "col": 0, "row": 1,
              "rows": ["bench_parse, stats_util", "pool_runs, sweep_summary", "native / comparator views"]},
             {"key": "tests", "name": "python/tests", "stereo": "MIT OR GPL-2.0-only", "col": 1, "row": 1,
              "rows": ["self-tests", "13 AntHocNet cells", "byte-identical output"]},
             {"key": "img", "name": "ns3-dev image", "stereo": "ns3-containers", "col": 2, "row": 1,
              "rows": ["latest-debug", "latest-sanitized"], "cls": "d-ext"}],
            [("arms", "rb", "registers", "flow"), ("probe", "rb", "«use»", "use"), ("py", "rb", "parses lines", "use"),
             ("tests", "py", "«use»", "use"), ("rb", "img", "builds in", "use")]))
    elif pid == "ns3-containers":
        out.append(dg.pipeline(
            "img-pipe", "ns3-containers: the publish-images pipeline",
            "The publish-images pipeline: resolve the supported ns-3 release and base digests; build each image "
            "once as a candidate; run every test stage on that digest (structure, profile, smoke, integration, "
            "unit, security); promote by retagging the same digest; sign; attest; move the latest tags; discard "
            "the run's candidates.",
            "What is tested is what is tagged: one build, every test by digest, tags are a copy of that digest "
            "(<code>imagetools create</code>), never a rebuild.",
            [("resolve", ["ns3_matrix.py", "base digests"], ""), ("build once", ["candidate in", "ns3-dev-ci"], ""),
             ("test by digest", ["structure, profile", "smoke, integration", "unit, security"], "d-contract"),
             ("promote", ["retag the", "same digest"], "d-good"), ("sign", ["cosign"], ""),
             ("attest", ["provenance"], ""), ("latest-*", ["moving tags"], ""),
             ("clean up", ["discard this run's", "candidates"], "")], bw=160, wrap=4))
        out.append(image_matrix())
        out.append(dg.sequence(
            "img-use", "ns3-containers: a downstream module in CI (UML sequence diagram)",
            "How a protocol repository's CI uses an image: the reusable workflow pulls ns3-dev latest-debug, "
            "mounts the module, ns3-build-contrib links it into the warm ns-3 tree and builds only the module, "
            "then test.py runs its suites.",
            "A downstream CI job: only the module compiles (8 Ninja steps on the smoke fixture).",
            ["protocol CI", "ns3-dev image", "ns3-build-contrib", "ns-3 tree /opt/ns-3"],
            [("msg", 0, 1, "docker run latest-debug", "ctl"), ("msg", 1, 2, "mount module (read-only)", "ctl"),
             ("msg", 2, 3, "link into contrib/", "ctl"), ("self", 3, "ninja: only the module's targets"),
             ("msg", 3, 2, "built", "back"), ("msg", 2, 3, "test.py -s <module>", "ctl"),
             ("msg", 3, 0, "suites pass / fail", "back")]))
    elif pid == "benchmarks":
        out.append(dg.pipeline(
            "bench-flow", "benchmarks: from a campaign to the leaderboard",
            "A campaign runs on the immutable optimized image with pinned protocol commits; the raw marker lines "
            "and a manifest land in runs; a script recomputes the paired verdicts; this site's CI regenerates "
            "the leaderboard from those verdicts.",
            "Every number on the leaderboard traces back to an image digest, protocol commits, a scenario and "
            "its seeds. Dashed: planned (benchmarks#3, site#12).",
            [("campaign", ["ns3-dev:<ver>-", "optimized-<sha7>"], "d-planned"),
             ("runs/", ["marker lines", "manifest.json"], "d-planned"),
             ("verdicts/", ["recomputed", "by script"], "d-planned d-good"),
             ("leaderboard", ["this site's CI", "(site#12)"], "d-planned")], bw=170, wrap=4))
        out.append(manifest_classes())
    elif pid == "org-commons":
        out.append(dg.pipeline(
            "commons-flow", "The org commons: how a rule reaches every repository",
            "A template change in swarm-routing/.github is rendered by org-sync into each repository; the "
            "org-sync check in each repository's CI turns red on drift until it applies the change; reusable "
            "workflows are called at main by every repository.",
            "One source of truth, checked in every repository's CI.",
            [("templates/", ["AGENTS/CLAUDE sections", "badges, SECURITY"], ""),
             ("org-sync apply", ["per repository", "(org-repo skill)"], ""),
             ("org-sync check", ["red on drift"], "d-contract"),
             ("reusable CI", ["ns-3, Python", "licence, PR title"], "d-good")], bw=170, wrap=4))
    return out


def image_matrix() -> str:
    d = dg.Diagram("img-matrix", 760, 250, "ns3-containers: base × profile matrix",
                   "Which profiles are built for the supported ns-3 release on each base: Ubuntu 24.04 gets "
                   "default, debug, sanitized and optimized; Debian 13 and Debian 13 slim get default and debug; "
                   "Alpine, experimental, gets debug.",
                   "Images built for the supported release (the latest ns-3; 3.49 today). Older releases: on demand, "
                   "Ubuntu, <code>default</code> and <code>debug</code>.")
    profiles = ["default", "debug", "sanitized", "optimized"]
    bases = [("Ubuntu 24.04", {0, 1, 2, 3}), ("Debian 13", {0, 1}), ("Debian 13 slim", {0, 1}),
             ("Alpine (exp.)", {1})]
    x0, y0, cw, rh = 170, 40, 140, 44
    for j, pr in enumerate(profiles):
        d.text(x0 + j * cw + cw / 2, y0 - 12, pr, "d-t")
    for i, (b, on) in enumerate(bases):
        y = y0 + i * rh
        d.text(x0 - 12, y + 26, b, "d-s", "end")
        for j in range(4):
            cls = "d-cell-on" if j in on else "d-cell-off"
            d.raw(f'<rect x="{x0 + j * cw + 6}" y="{y + 6}" width="{cw - 12}" height="{rh - 10}" rx="6" class="{cls}"/>')
            d.text(x0 + j * cw + cw / 2, y + 30, "built" if j in on else "—", "d-s")
    return d.render()


def manifest_classes() -> str:
    return dg.classes(
        "bench-manifest", "benchmarks: what a run's manifest pins (UML class diagram)",
        "Class diagram of a planned run manifest: an image reference by immutable tag and digest, one commit "
        "per protocol, the scenario, the seeds (at least twenty) and the exact command line; a verdict refers "
        "to two runs paired by seed.",
        "Planned shape (the schema is benchmarks#3); every field is required: no manifest, no merge.",
        [("dataset", "GPL-2.0-only · data", 20, 20, 720, 300, [
            ("Manifest", None, ["+ image : ns3-dev:<ver>-<profile>-<sha7>", "+ digest : sha256",
                                "+ commits : {protocol: sha}", "+ scenario : string",
                                "+ seeds : int[≥ 20]", "+ command : string"], 40, 70),
            ("Run", None, ["+ markers : ##RUN## / ##BENCH##", "+ manifest : Manifest"], 290, 70),
            ("Verdict", None, ["+ a, b : Run (paired by seed)", "+ delta : per-seed Δ", "+ noise : verdict"], 520, 70),
            ("Supersedes", None, ["+ old : Run", "+ issue : why"], 290, 210)])],
        [("Run", "Manifest", "use", "1"), ("Verdict", "Run", "use", "2"), ("Supersedes", "Run", "use", "")],
        cw=210)


def repos_section(data) -> str:
    rs = data["repos"]
    bad = [r["repo"] for r in rs if r.get("visibility") != "public"]
    if bad:
        raise SystemExit(f"render_hub.py: refusing non-public repositories {bad} (the site lists public ones only)")
    layers = ["Protocols", "Foundation", "Tooling and infrastructure", "Data", "Site and commons"]
    pos = {"AntHocNet": (0, 0), "ARA": (1, 0), "BeeAdHoc": (2, 0), "Termite": (3, 0), "HOPNET": (4, 0),
           "ns3-swarm-core": (1, 1), "ns3-tools": (3, 1), "ns3-containers": (2, 2), "benchmarks": (4, 2),
           ".github": (1, 2), "skills": (1, 3), "swarm-routing.github.io": (0, 3)}
    pk = []
    for r in rs:
        c, w = pos[r["repo"]]
        pk.append({"key": r["repo"], "name": r["repo"], "col": c, "row": w,
                   "stereo": {"Protocols": "protocol", "Foundation": "foundation", "Data": "data",
                              "Tooling and infrastructure": "tooling"}.get(
                       r["layer"], "site" if r["repo"].endswith(".github.io") else "commons"),
                   "rows": [x.split(" (")[0] for x in r["packages"][:3]],
                   "planned": r["gen"]["status"] == "planned", "cls": "d-hl" if r["repo"] == "swarm-routing.github.io" else ""})
    deps = [(p, "ns3-swarm-core", "«use»", "use") for p in ("ARA", "BeeAdHoc", "Termite")] + [
        ("HOPNET", "ns3-tools", "arm", "use"), ("ns3-swarm-core", "ns3-containers", "builds in", "use"),
        ("ns3-tools", "ns3-containers", "runs in", "use"), ("ns3-tools", "benchmarks", "verdicts", "flow"),
        ("swarm-routing.github.io", "AntHocNet", "builds core/", "use"), ("skills", ".github", "drives org-sync", "use"),
        ("AntHocNet", "ns3-swarm-core", "extracts", "flow")]
    fig = dg.packages(
        "org-pkg", "The public repositories as a package diagram",
        "UML package diagram of the organisation's twelve public repositories in four rows: the five protocols; "
        "swarm-core and ns3-tools; .github, ns3-containers and benchmarks; this site and skills. Arrows show the "
        "main dependencies: protocols use swarm-core, the bench and swarm-core run in the ns3-dev images, the "
        "bench writes verdicts into benchmarks, this site builds AntHocNet's core, skills drives org-sync.",
        "Package diagram (UML) of every public repository; the stereotype is its layer. Dashed outlines: "
        "planned, no release and no epic in progress. Highlighted: this site.", pk, deps, cols=5, cw=200, ch=140, gap=30)
    rows = []
    for layer in layers:
        for r in [r for r in rs if r["layer"] == layer]:
            space = f'<a href="{PROJECTS}/{E(r["space"])}/">page</a> · ' if r["space"] else '<a href="#build">this site</a> · '
            label, st = STATUS[r["gen"]["status"]]
            src = f'<a href="{E(r["gen"]["source"])}">epics</a> · ' if r["gen"]["source"] else ""
            rows.append(
                f'<tr><th scope="row"><a href="{GH}/{E(r["repo"])}">{E(r["repo"])}</a></th><td>{E(layer)}</td>'
                f'<td>{E(r["role"])}</td><td><ul class="pk">{"".join(f"<li><code>{E(x)}</code></li>" for x in r["packages"])}</ul></td>'
                f'<td><span class="lic">{E(r["licence"])}</span></td>'
                f'<td><span class="chip {st}" data-status="{r["gen"]["status"]}">{E(label)}</span><br>{src}{space}<a href="{GH}/{E(r["repo"])}/blob/main/AGENTS.md">AGENTS.md</a></td></tr>')
    return f"""<section id="repos" aria-labelledby="repos-t"><h2 id="repos-t">Package structure: the public repositories</h2>
<p class="intro">Every public repository of <a href="{GH}">swarm-routing</a>, what it ships and under which licence.
Private repositories are never listed.</p>
{fig}
<div class="table-scroll"><table class="tree"><caption class="sr">Public repositories of swarm-routing</caption>
<thead><tr><th scope="col">Repository</th><th scope="col">Layer</th><th scope="col">Role</th><th scope="col">Packages</th><th scope="col">Licence</th><th scope="col">State</th></tr></thead>
<tbody>{"".join(rows)}</tbody></table></div></section>
"""


# -- references: each project's docs/references.bib -----------------------------------
RAW = "https://raw.githubusercontent.com"
ROLE_LABEL = {"implemented": "Implemented", "restates": "Restates", "compared": "Compared against",
              "dataset": "Datasets", "tool": "Software it builds on", "background": "Background"}


def fetch_file(repo: str, ref: str, path: str) -> str:
    """A file of a public repository at ref; '' when it has none or cannot be
    reached (a warning, never a failed build)."""
    url = f"{RAW}/{repo}/{ref}/{path}"
    try:
        with urllib.request.urlopen(url, timeout=10) as r:
            return r.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        if e.code != 404:
            print(f"render_hub.py: warning: {url}: HTTP {e.code}; not shown", file=sys.stderr)
    except (OSError, http.client.HTTPException, UnicodeDecodeError) as e:
        print(f"render_hub.py: warning: {url}: {e}; not shown", file=sys.stderr)
    return ""


def fetch_bib(repo: str, ref: str) -> str:
    """docs/references.bib of a public repository at ref ('' when it has none)."""
    return fetch_file(repo, ref, "docs/references.bib")


def fetch_cff(repo: str, ref: str) -> str:
    """CITATION.cff of a public repository at ref ('' when it has none)."""
    return fetch_file(repo, ref, "CITATION.cff")


def safe_https(link: str) -> bool:
    """An absolute https URL with no whitespace whose host is DNS labels (none empty)."""
    if re.search(r"\s", link):
        return False
    try:
        u = urlsplit(link)
        host = u.hostname
    except ValueError:
        return False
    return u.scheme == "https" and bool(host) and all(
        re.fullmatch(r"[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?", label) for label in host.split("."))


def public_ref(p, pins, data, what: str) -> str:
    """The ref a project's files are read at: its protocols.lock commit, else
    main. Only a repository projects.json lists as public is ever fetched."""
    name = p["repo"].split("/", 1)[1]
    if not any(r["repo"] == name and r.get("visibility") == "public" for r in data["repos"]):
        raise SystemExit(f"render_hub.py: refusing {what} of {p['repo']}: not a public repository in projects.json")
    pin = pins.get(p["id"])
    return pin["commit"] if pin and pin["repo"] == p["repo"] else "main"


def where(ref: str) -> str:
    return f"<code>{E(ref[:12])}</code> (protocols.lock)" if ref != "main" else "<code>main</code>"


def link_label(link: str) -> str:
    """What a reference's link says: its DOI, or the host of its page."""
    doi = "https://doi.org/"
    return f"DOI {link[len(doi):]}" if link.startswith(doi) else (urlsplit(link).hostname or link)


def copy_button(text: str, label: str) -> str:
    return f'<button type="button" class="mini" data-copy="{E(text)}">{E(label)}</button>'


def project_refs(p, pins, data, fetch=fetch_bib, sink=None) -> str:
    """The References section of a project page, '' without entries. Every
    entry links its DOI (its publisher's page when it has none). `sink`, a dict
    keyed by link, collects each work for the site-wide /references/ page."""
    ref = public_ref(p, pins, data, "references")
    try:
        entries = bib.parse(fetch(p["repo"], ref))
    except bib.BibError as e:
        print(f"render_hub.py: warning: {p['repo']} docs/references.bib: {e}; no references shown", file=sys.stderr)
        return ""
    groups: dict[str, list[str]] = {}
    for e in entries:
        rs = bib.roles(e)
        role = next((r for r in bib.ROLES if r in rs), "background")
        link = bib.doi_link(e) or ""
        if not safe_https(link):
            print(f"render_hub.py: warning: {p['repo']} docs/references.bib: {e['key']} has no doi or https url; "
                  "left out", file=sys.stderr)
            continue
        cite = re.sub(r"\*([^*]+)\*", r"<cite>\1</cite>", E(bib.citation(e), quote=False))
        item = (f'<span class="ref-c">{cite}.</span> <span class="ref-a"><a class="doi" href="{E(link)}">'
                f'{E(link_label(link))}</a> {copy_button(bib.format_entry(e), "Copy BibTeX")}</span>')
        groups.setdefault(role, []).append(f"<li>{item}</li>")
        if sink is not None:
            doi = "https://doi.org/"  # a DOI is case-insensitive: one work whatever case a bib writes it in
            key = link.lower() if link.startswith(doi) else link
            work = sink.setdefault(key, {"item": item, "sort": bib.citation(e).lower(), "by": []})
            if p["id"] not in [i for i, _ in work["by"]]:
                work["by"].append((p["id"], p.get("name", p["id"])))
    if not groups:
        return ""
    n = sum(len(v) for v in groups.values())
    body = "".join(f'<h3>{E(ROLE_LABEL[r])}</h3><ul class="sources refs">{"".join(groups[r])}</ul>'
                   for r in bib.ROLES if r in groups)
    return (f'<section id="references" class="reflist" aria-labelledby="refs-t"><h2 id="refs-t">References</h2>'
            f'<p class="intro">The {n} work{"s" if n != 1 else ""} '
            f'<a href="https://github.com/{E(p["repo"])}/blob/{E(ref)}/docs/references.bib">'
            f'<code>docs/references.bib</code></a> lists, read at {where(ref)} when this site was built. Each links '
            f'its DOI; a work with none links its publisher\'s or institution\'s page.</p>{body}</section>\n')


# -- how to cite a project ------------------------------------------------------------
DOI_RE = re.compile(r"10\.\d{4,9}/[^\s\"<>]+")


def parse_cff(text: str) -> dict:
    """The CITATION.cff fields the cite block shows: the top-level scalars, the
    authors and the licence. A reader of that subset, not of YAML: block
    scalars and every other nested key (references, identifiers) are skipped."""
    def value(v: str) -> str:
        v = v.strip()
        if v[:1] in ("\"", "'"):  # a quoted scalar ends at its closing quote; a comment may follow
            end = v.find(v[0], 1)
            return v[1:end] if end > 0 else v[1:]
        cut = v.find(" #")
        return (v[:cut] if cut >= 0 else v).rstrip()
    top: dict = {"authors": [], "license": []}
    block, cur, folded = None, None, None  # folded: (key, joiner) of a top-level block scalar being read
    for raw in text.splitlines():
        line = raw.strip()
        indent = len(raw) - len(raw.lstrip(" "))
        if folded and (indent > 0 or not line):
            if line:
                top[folded[0]] = (top[folded[0]] + folded[1] if top.get(folded[0]) else "") + line
            continue
        folded = None
        if not line or line.startswith("#"):
            continue
        # "key: value" without a regex over the value (no backtracking): m[1] the key, m[2] the value or None
        head, colon, rest = (line[2:].strip() if line.startswith("- ") else line).partition(":")
        keyed = bool(colon) and re.fullmatch(r"[A-Za-z][A-Za-z0-9-]*", head) and (not rest or rest[0] in " \t")
        m = (None, head, rest.strip() or None) if keyed else None
        if indent == 0 and not line.startswith("- "):
            block, cur = (m[1], None) if m else (None, None)
            if m and m[2] and m[2][0] in ">|" and block not in ("authors", "license"):
                folded = (block, " " if m[2][0] == ">" else "\n")  # a folded (>) or literal (|) scalar
            elif m and m[2] and block not in ("authors", "license"):
                top[block] = value(m[2])
            elif m and m[2] and block == "license":
                top["license"] = [value(m[2])]
        elif block == "authors":
            if line.startswith("- "):
                cur = {}
                top["authors"].append(cur)
            if m and cur is not None and m[2]:
                cur[m[1]] = value(m[2])
        elif block == "license" and line.startswith("- "):
            top["license"].append(value(line[2:]))
    return top


def cite_formats(p, cff) -> tuple[str, str]:
    """The project's citation as text and as BibTeX, from its CITATION.cff."""
    people = [(a["name"], True) if a.get("name") else
              (", ".join(x for x in (a.get("family-names"), a.get("given-names")) if x), False) for a in cff["authors"]]
    names = [n for n, _ in people if n]
    # BibTeX reads an unbraced name as "First Last": an entity keeps its name whole in inner braces
    bib_names = [f"{{{n}}}" if entity else n for n, entity in people if n]
    year = str(cff.get("date-released", ""))[:4]
    doi = cff.get("doi", "")
    url = f"https://doi.org/{doi}" if doi else f"https://github.com/{p['repo']}"
    kind = "Data set" if cff.get("type") == "dataset" else "Computer software"
    version = f" (version {cff['version']})" if cff.get("version") else ""
    text = f"{'; '.join(names)} ({year or 'n.d.'}). {cff['title']}{version} [{kind}]. {url}"
    fields = [("author", " and ".join(bib_names)), ("title", cff["title"]), ("version", cff.get("version", "")),
              ("year", year), ("doi", doi), ("url", cff.get("repository-code") or f"https://github.com/{p['repo']}")]
    key = re.sub(r"[^a-z0-9]", "", p["id"].lower()) or "project"
    entry = "@misc" if cff.get("type") == "dataset" else "@software"
    bibtex = f"{entry}{{{key},\n" + ",\n".join(f"  {k:<7} = {{{v}}}" for k, v in fields if v) + "\n}"
    return text, bibtex


def project_cite(p, pins, data, fetch=fetch_cff) -> str:
    """The "Cite this project" section, '' when the repository has no usable
    CITATION.cff. Every field is the file's; a DOI is shown only when the file
    gives one that looks like a DOI (never typed here)."""
    ref = public_ref(p, pins, data, "the citation")
    cff = parse_cff(fetch(p["repo"], ref))
    if not cff.get("title") or not cff["authors"]:
        return ""
    if cff.get("doi") and not DOI_RE.fullmatch(cff["doi"]):
        print(f"render_hub.py: warning: {p['repo']} CITATION.cff: doi {cff['doi']!r} is not a DOI; left out", file=sys.stderr)
        del cff["doi"]
    text, bibtex = cite_formats(p, cff)
    doi = cff.get("doi", "")
    people = []
    for a in cff["authors"]:
        name = a.get("name") or " ".join(x for x in (a.get("given-names"), a.get("family-names")) if x)
        orcid = a.get("orcid", "")
        people.append(E(name) + (f' · <a href="{E(orcid)}">ORCID</a>' if safe_https(orcid) else ""))
    facts = [("Version", E(str(cff.get("version", ""))) + (f" · released {E(str(cff['date-released']))}" if cff.get("date-released") else "")),
             ("Author" if len(people) == 1 else "Authors", "<br>".join(people)),
             ("DOI", f'<a class="doi" href="https://doi.org/{E(doi)}">{E(doi)}</a>' if doi else
              "None yet: not released. Cite the repository."),
             ("Licence", E(", ".join(cff["license"])))]
    dl = "".join(f"<div><dt>{k}</dt><dd>{v}</dd></div>" for k, v in facts if v)
    blob = f"https://github.com/{E(p['repo'])}/blob/{E(ref)}/CITATION.cff"
    return (f'<section id="cite" aria-labelledby="cite-t"><h2 id="cite-t">Cite this project</h2>'
            f'<p class="intro">Using {E(p.get("name", p["id"]))} in a paper? Cite the project as below, and the works it '
            f'rests on from its references.</p>'
            f'<div class="cite"><div class="cite-main">'
            f'<h3 class="cite-h">Text</h3><pre class="cite-out" tabindex="0">{E(text)}</pre>'
            f'<p class="cite-acts">{copy_button(text, "Copy text")}</p>'
            f'<h3 class="cite-h">BibTeX</h3><pre class="cite-out" tabindex="0">{E(bibtex)}</pre>'
            f'<p class="cite-acts">{copy_button(bibtex, "Copy BibTeX")}</p></div>'
            f'<dl class="cite-facts">{dl}</dl></div>'
            f'<p class="note">Read from <a href="{blob}"><code>CITATION.cff</code></a> at {where(ref)} when this site '
            f'was built.</p></section>\n')


def redirect(to: str, title: str) -> str:
    """A page that sends an old address to its new one (as site-redirects.sh
    does for AntHocNet's old docs URLs): meta refresh, canonical, a link."""
    return (f'<!doctype html>\n<html lang="en"><head><meta charset="utf-8"><title>{E(title)}</title>'
            f'<meta http-equiv="refresh" content="0; url={E(to)}"><link rel="canonical" href="{E(to)}">'
            f'<meta name="robots" content="noindex"></head>'
            f'<body><main><p>This page moved: <a href="{E(to)}">{E(title)}</a>.</p></main></body></html>\n')


# -- pages ---------------------------------------------------------------------------
def page(title: str, desc: str, root: str, body: str, active: str = "") -> str:
    nav = "".join(
        f'<a href="{root}{h}"{CURRENT if k == active else ""}>{E(t)}</a>'
        for k, t, h in [("map", "Colony map", "#map"), ("projects", "Projects", f"{PROJECTS}/"), ("quests", "Quest log", "#quests"),
                        ("repos", "Repositories", "#repos"), ("build", "How it is built", "#build"), ("pipeline", "Pipeline", "pipeline/"),
                        ("play", "Play AntHocNet", "AntHocNet/")])
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{E(title)}</title>
<meta name="description" content="{E(desc)}">
<meta name="color-scheme" content="light dark">
<link rel="stylesheet" href="{root}arena/arena.css">
<script>try{{var t=localStorage.getItem('arena-theme');if(t)document.documentElement.dataset.theme=t;}}catch(e){{}}</script>
</head><body>
<a class="skip" href="#main">Skip to content</a>
<header class="bar"><a class="brand" href="{root}"><span class="logo" aria-hidden="true"></span>Colony&nbsp;Arena <span class="sub">swarm-routing</span></a>
<nav class="places-nav" aria-label="Sections">{nav}</nav>
<button type="button" class="btn" id="theme" aria-label="Switch day and night" title="Day / night">☾</button>
<a class="btn" href="{GH}" title="swarm-routing on GitHub" aria-label="swarm-routing on GitHub">⌥</a></header>
<main id="main">{body}</main>
<footer class="foot"><p>Colony Arena is the swarm-routing organisation's site, GPL-2.0-only. Every simulation
runs a protocol's original C++ <code>core/</code>, compiled to WebAssembly from its repository at a pinned commit
(<a href="{GH}/swarm-routing.github.io/blob/main/protocols.lock">protocols.lock</a>); nothing is vendored or
rewritten (<a href="{root}pipeline/">how it is compiled and deployed</a>).
<a href="{GH}/swarm-routing.github.io">Source</a>.</p>
<p>Built by <a href="https://github.com/danieljoppi">Daniel Joppi</a>, reviving a 2008 NS-2 college project with AI
assistance, with tests, determinism checks and paired benchmarks as the safeguard:
<a href="{GH}#why-this-exists">why this exists</a>.</p></footer>
<script src="{root}arena/arena.js" defer></script>
</body></html>
"""


def card(p, root) -> str:
    cls = STATUS[p["status"]][1]
    return (f'<li class="card {cls}" data-status="{p["status"]}"><a href="{root}{PROJECTS}/{E(p["id"])}/">'
            f'<svg class="card-g" viewBox="-60 -60 120 100" aria-hidden="true">{glyph(p["glyph"])}</svg>'
            f'<span class="card-k">{E(p["place"])} · {E(KIND[p["kind"]])}</span>'
            f'<span class="card-t">{E(p["name"])}</span>'
            f'<span class="card-s">{E(p["tagline"])}</span>'
            f'{chip(p)}</a></li>')


def hub(data, pins) -> str:
    ps = data["projects"]
    when = as_of(data)
    roadmap = f"{GH}/.github/blob/main/ROADMAP.md#epics"
    known = [r for r in data["repos"] if r["gen"]["status"] != "unknown"]
    epics = [(r, e) for r in known for e in r["gen"]["epics"]]
    done = sum(r["gen"]["done"] for r in known)
    total = sum(r["gen"]["total"] for r in known)
    if when:
        level = (f'<p class="xp-v">{done}<span>/ {total} sub-issues closed</span></p>'
                 f'<div class="xp-bar" role="progressbar" aria-label="Sub-issues closed" aria-valuemin="0" '
                 f'aria-valuemax="{total}" aria-valuenow="{done}"><i style="width:{round(100 * done / total) if total else 0}%"></i></div>'
                 f'<p class="xp-s">Closed sub-issues over all sub-issues of the <a href="{roadmap}">{plural(len(epics), "epic")}</a> '
                 f'of {len(known)} public repositor{"y" if len(known) == 1 else "ies"}, as the issues stood on {when}.</p>')
    else:
        level = ('<p class="xp-v">–</p><p class="xp-s">Status not available: this build has no issue data. '
                 f'The <a href="{roadmap}">ROADMAP</a> lists every epic.</p>')
    going = [(r, e) for r, e in epics if e["status"] == "In progress"]
    rest = {k: sum(e["status"] == k for _, e in epics) for k in ("Planned", "Done", "Dropped")}
    quests = "".join(
        f'<li class="q-open"><span class="q-box" aria-hidden="true"></span>'
        f'<span><a href="{E(e["url"])}">{E(r["repo"])}#{e["number"]} {E(epic_title(e["title"]))}</a><br>'
        f'<span class="note">In progress · {e["completed"]} / {e["total"]} sub-issues closed</span></span></li>'
        for r, e in going)
    if when:
        log = (f'<p class="intro">The epics in progress across the colony, as the issues stood on {E(data["hub"]["asOf"])}: '
               f'an epic is in progress once one of its sub-issues is closed. {plural(rest["Planned"], "more epic")} '
               f'{"is" if rest["Planned"] == 1 else "are"} planned, {rest["Done"]} done and {rest["Dropped"]} dropped: each project\'s page '
               f'lists its own, and the <a href="{roadmap}">ROADMAP</a> lists them all.</p>'
               + (f'<ul class="quests">{quests}</ul>' if going else '<p class="intro">No epic is in progress.</p>'))
    else:
        log = (f'<p class="intro">Status not available: this build has no issue data. The '
               f'<a href="{roadmap}">ROADMAP</a> lists every epic of every public repository.</p>')
    by_kind = [("Protocols: the colonies", [p for p in ps if p["kind"] == "protocol"]),
               ("Foundations, tools and infrastructure", [p for p in ps if p["kind"] != "protocol"])]
    cards = "".join(f'<h3>{E(h)}</h3><ul class="cards">{"".join(card(p, "") for p in group)}</ul>'
                    for h, group in by_kind)
    body = f"""
<section class="hero" aria-labelledby="hero-t">
  <div><p class="eyebrow">swarm-routing · {len([p for p in ps if p['kind'] == 'protocol'])} protocols, one colony</p>
  <h1 id="hero-t">Colony Arena</h1>
  <p class="lede">Swarm-intelligence routing for wireless networks, built in the open: ants, bees and termites as
  network protocols, one shared ns-3 module, a protocol-agnostic test bench, tested simulator images, and
  reproducible data. Explore the colony; every place is a repository.</p>
  <p class="cta"><a class="button primary" href="AntHocNet/">Play AntHocNet</a>
  <a class="button" href="#map">Explore the colony</a>
  <a class="button" href="AntHocNet/docs/">Read the docs</a>
  <a class="button" href="pipeline/">How it runs</a></p>
  <p class="note">The game runs AntHocNet's original C++ routing core, compiled to WebAssembly and checked
  byte for byte against the native build (<a href="pipeline/">the pipeline</a>).</p></div>
  <div class="xp" role="group" aria-label="Colony level">
    <p class="xp-k">Colony level</p>{level}
  </div>
</section>
<section id="map" aria-labelledby="map-t"><h2 id="map-t">The colony map</h2>
<p class="intro">A place is unlocked once its repository has a 1.0 release, or every epic it opened is closed;
scaffolding means an epic is in progress or the releases are still 0.x; a padlock means neither has started.
Each status is computed from the repository's issues and releases{" as they stood on " + E(data["hub"]["asOf"]) if when else ""};
a project's page links them. Ants walk the trails between projects that depend on each other.</p>
{colony_map(ps, site_place(data["hub"]))}
{cards}
</section>
{repos_section(data)}
<section id="quests" aria-labelledby="q-t"><h2 id="q-t">Quest log: the epics in progress</h2>
{log}</section>
<section id="build" aria-labelledby="b-t"><h2 id="b-t">How the colony is built</h2>
<p class="intro">Four rules hold the whole organisation together. Each diagram below is the rule drawn.</p>
<div class="rules">
<article><h3>1. One algorithm, many adapters</h3><p>Each protocol's <code>core/</code> is simulator-agnostic C++
that receives time, randomness, neighbours and timers through ports. The ns-3 module and the browser adapter only
convert headers and carry out the core's decisions, so the game on this site runs the very code the benchmarks
measure, compiled to WebAssembly (<a href="pipeline/">the pipeline</a>).</p></article>
<article><h3>2. The licence boundary goes one way</h3><p><code>core/</code> and standalone tools are
<code>MIT OR GPL-2.0-only</code>; ns-3 modules, this site, docs and data are <code>GPL-2.0-only</code>. GPL code
may use the dual parts, never the reverse.</p></article>
<article><h3>3. Determinism, then pairing</h3><p>A fixed seed gives byte-identical output, natively and in
WebAssembly. Comparisons pair runs by seed over at least twenty seeds, and a script, not a reader, makes the
noise call.</p></article>
<article><h3>4. Pinned, never vendored</h3><p>This site builds each protocol from its own repository at the
commit in <code>protocols.lock</code>; simulator images are tested by digest and published numbers pin an
immutable tag.</p></article></div>
{dg.org_graph("org-graph", None, "The organisation as a dependency graph (UML «use» arrows): protocols on top, the shared module and the bench in the middle, images, data and the org commons below.")}
{dg.hexagon("org-hex", "A protocol's hexagonal architecture", "The pattern every protocol follows: a simulator-agnostic core reached through ports, with an ns-3 adapter and a browser adapter outside.", "Ports and adapters, as every protocol repository lays them out (AntHocNet's ports shown).", "core/", ["routing logic", "pheromone math", "wire codec"], ANT_PORTS, [("l", "ns-3 adapter", ["contrib module", "on swarm-core", "header ⇄ message"], "GPL-2.0-only"), ("r", "browser adapter", ["core/ → WebAssembly", "byte-identical trace", "this site"], "GPL-2.0-only")])}
{dg.pipeline("org-evidence", "From code to evidence", "The evidence chain: a protocol commit is pinned, built inside a tested ns3-dev image, run by the routing-bench harness over twenty or more seeds, judged by the ns3_tool scripts, stored with a manifest in benchmarks, and rendered on this site.", "The evidence chain. Every step is pinned or scripted, so any number can be rebuilt from its manifest.", [("protocol commit", ["40-char SHA", "protocols.lock"], ""), ("ns3-dev image", ["tested by digest", "-<sha7> tag"], ""), ("routing-bench", ["≥ 20 seeds", "marker lines"], "d-contract"), ("ns3_tool", ["paired Δ", "noise verdict"], "d-good"), ("benchmarks", ["runs + manifest", "verdicts"], ""), ("Colony Arena", ["game, docs", "leaderboard"], "")], bw=140, wrap=6)}
</section>
"""
    return page("Colony Arena — swarm-routing",
                "The swarm-routing organisation: ant, bee and termite routing protocols, the shared ns-3 module, "
                "the test bench, the simulator images and the data, as one explorable colony.", "", body, "map")


CORE_SOURCES = ["pheromone_table.cpp", "pheromone_engine.cpp", "ant_history.cpp",
                "ant_message_codec.cpp", "ant_router_logic.cpp", "link_metric_registry.cpp"]


def pipeline_page(pins) -> str:
    """/pipeline/: the browser runs the protocol's own C++ core, and how it is packaged and deployed."""
    root = "../"
    ahn = pins.get("AntHocNet", {})
    sha = ahn.get("commit", "")
    pin = (f'<a href="https://github.com/{E(ahn["repo"])}/commit/{E(sha)}"><code>{E(sha[:12])}</code></a>'
           if sha else "<code>protocols.lock</code>")
    src = "".join(f"<li><code>core/src/{E(f)}</code></li>" for f in CORE_SOURCES)
    steps = [
        ("Pin", "protocols.lock", ("One line per protocol: repository, 40-character commit, tag. It changes only by "
         "pull request, and that PR runs every gate below."), "python3 tools/lock.py AntHocNet commit"),
        ("Fetch", ".github/workflows/pages.yml", ("actions/checkout checks the protocol out at the pinned commit "
         "(locally, tools/build-site.sh fetches it). Its core/, docs/, api/ and toolchain pins come from there."),
         "tools/build-site.sh build/site"),
        ("Overlay", "tools/build-site.sh", ("site/anthocnet/ (the browser adapter, the game and the site shell) is "
         "laid over the checkout as its web/. Nothing of the protocol is copied into this repository."), ""),
        ("Compile", "site/anthocnet/CMakeLists.txt", ("Emscripten (emsdk 4.0.10, the protocol's own pin) compiles the "
         "core's C++ sources and the adapter into anthocnet.wasm plus its ES-module loader anthocnet.js, as C++14, "
         "Release, -ffp-contract=off."), "emcmake cmake -S web -B web/build-wasm && cmake --build web/build-wasm --target anthocnet"),
        ("Assemble", "site/anthocnet/build-pages.sh", ("The game with the module (cache-busted by the module's "
         "sha256), the protocol's mkdocs docs at docs/, its Doxygen API at api/, all under one top bar, plus the "
         "old-URL redirects. Then tools/render_hub.py writes the hub, every project space and this page."), "web/build-pages.sh"),
        ("Prove", "site/anthocnet/test/parity.sh", ("The same sources are built natively and to WebAssembly; both "
         "run every built-in scenario for seeds 1, 2, 7 and 42 over 120 simulated seconds, and the decision traces "
         "must be byte-identical."), 'web/test/parity.sh 120 "1 2 7 42"'),
        ("Check", ".github/workflows/pages.yml", ("The protocol's web tests (quests, translations, Nest coverage, "
         "tuning bench, campaign levels, labs), both crawls (every link, asset and anchor), and both browser smokes "
         "with axe, in day and night."), "node site/anthocnet/test/smoke.mjs …; node test/hub-smoke.mjs …"),
        ("Deploy", "actions/deploy-pages", ("Only main deploys: the assembled tree is uploaded as the Pages "
         "artifact and published. Pull requests run every step above and stop here."), ""),
        ("Verify", "site/anthocnet/test/live-smoke.mjs", ("After the deploy, the live site must serve the module this "
         "build made (its hash in engine.js), the game must deliver packets, the docs, API and 404 must carry the "
         "top bar, and the hub and every project space must answer 200. A failure opens a tracking issue."), ""),
    ]
    rows = "".join(f'<tr><th scope="row">{i}. {E(n)}<br><code>{E(f)}</code></th><td>{E(w)}</td>'
                   f'<td>{f"<code>{E(c)}</code>" if c else "—"}</td></tr>'
                   for i, (n, f, w, c) in enumerate(steps, 1))
    body = f"""
<nav class="crumb" aria-label="Breadcrumb"><ol><li><a href="{root}">Colony Arena</a></li><li><span aria-current="page">Pipeline</span></li></ol></nav>
<section class="hero" aria-labelledby="pl-t">
  <div><p class="eyebrow">How the site runs and ships</p>
  <h1 id="pl-t">The original core, compiled</h1>
  <p class="lede">Every simulation on this site runs the protocol's own C++ routing code, the same
  <code>core/</code> the ns-3 benchmarks run, compiled to WebAssembly from the protocol's repository at a pinned
  commit. Nothing is rewritten in JavaScript and nothing is vendored. This page shows how that code is compiled,
  proven identical, packaged and deployed.</p>
  <p class="cta"><a class="button primary" href="{root}AntHocNet/">Play AntHocNet</a>
  <a class="button" href="#compile">The compile</a> <a class="button" href="#deploy">Package and deploy</a></p></div>
</section>
<section id="compile" aria-labelledby="c-t"><h2 id="c-t">The simulation is the real core</h2>
<div class="cols"><div>
<p>AntHocNet's routing logic lives once, in <code>core/</code>: simulator-agnostic C++14 that takes time,
randomness, neighbours and timers through ports and returns decisions. The browser build compiles exactly these
core sources, unmodified, at the commit this site pins ({pin}):</p>
<ul class="sources">{src}</ul>
<p>Around them, the browser adapter (<code>site/anthocnet/src/</code>: the world, mobility and radio in
<code>sim.cpp</code>, the scenarios, and the Embind binding in <code>bindings.cpp</code>) only moves packets and
carries out the core's decisions. The JavaScript draws what the WebAssembly module reports; it holds no routing
logic (AntHocNet ADR-0021).</p></div>
<aside class="facts" aria-labelledby="cf-t"><h2 id="cf-t">The module</h2><dl>
<div><dt>Language</dt><dd>C++14, the core unmodified</dd></div>
<div><dt>Compiler</dt><dd>Emscripten, emsdk 4.0.10 (the protocol's pin)</dd></div>
<div><dt>Flags</dt><dd><code>-ffp-contract=off</code>, Release, no fast-math</dd></div>
<div><dt>Output</dt><dd><code>anthocnet.wasm</code> + ES module <code>anthocnet.js</code> (<code>createAntHocNet</code>)</dd></div>
<div><dt>Licence</dt><dd>core <code>MIT OR GPL-2.0-only</code>; the built site GPL-2.0-only</dd></div>
</dl></aside></div>
{dg.pipeline("pl-compile", "From the C++ core to the page", "The compile: the protocol's core sources at the pinned commit and the browser adapter go through Emscripten's CMake toolchain with floating-point contraction off; the result is a WebAssembly module and its ES-module loader, which the game's engine.js imports, cache-busted by the module's hash.", "The compile. The core sources come from the protocol's repository at the pinned commit, never from a copy here.", [("core/ (C++14)", ["the protocol's repo", "at the pinned commit"], "d-contract"), ("browser adapter", ["site/anthocnet/src", "sim · scenarios · bind"], ""), ("emcmake + CMake", ["emsdk 4.0.10", "-ffp-contract=off"], ""), ("anthocnet.wasm", ["+ anthocnet.js", "createAntHocNet()"], "d-good"), ("the game", ["engine.js imports it", "?v=<sha256>"], "")], bw=150, wrap=5)}
</section>
<section id="parity" aria-labelledby="p-t"><h2 id="p-t">Proof: byte-identical to the native build</h2>
<p class="intro">"The same code" is checked, not claimed. The same sources are built twice, natively and to
WebAssembly, and both builds of the trace runner replay every built-in scenario. Every ant and data
transmission, reception, route change, queue and drop is written with its simulated time; the two traces must
match byte for byte, and so must the scenario features' link-rule checks. It runs on every pull request here and on every <code>core/</code> pull request in
AntHocNet, whose CI fetches this adapter.</p>
{dg.pipeline("pl-parity", "Native vs WebAssembly parity", "The parity gate: the same sources build a native and a WebAssembly trace runner; both run every scenario for seeds 1, 2, 7 and 42 over 120 simulated seconds; the traces are compared byte for byte and must also show delivered packets.", "Determinism makes the comparison possible: randomness is drawn into named locals, mobility uses arithmetic sine and cosine, never libm trigonometry.", [("same sources", ["core/ + adapter"], ""), ("native build", ["ahn-web-trace", "g++ / clang"], ""), ("WASM build", ["ahn-web-trace", "emcc, node"], ""), ("every scenario", ["seeds 1 2 7 42", "120 s simulated"], ""), ("diff", ["byte-identical", "and delivering"], "d-good")], bw=150, wrap=5)}
</section>
<section id="deploy" aria-labelledby="d-t"><h2 id="d-t">Package and deploy</h2>
<p class="intro">One script builds the site, locally and in CI (<code>tools/build-site.sh</code>); one workflow
gates and ships it (<code>.github/workflows/pages.yml</code>). A newer core reaches the site only through a
<code>protocols.lock</code> bump pull request, which runs every step before anything is published.</p>
{dg.pipeline("pl-deploy", "From a pinned commit to the live site", "The deploy pipeline: pin the commit in protocols.lock, check the protocol out at it, overlay this repository's browser adapter as its web directory, compile the core to WebAssembly, assemble the game, docs, API and hub, prove parity, run the tests, crawls and browser smokes with axe, deploy from main to GitHub Pages, and smoke the live site.", "Pull requests run steps 1 to 7; main also deploys and verifies the live site.", [("1 pin", ["protocols.lock", "40-char SHA"], ""), ("2 fetch", ["checkout", "at the pin"], ""), ("3 overlay", ["site/anthocnet", "→ its web/"], ""), ("4 compile", ["core → WASM", "emsdk 4.0.10"], "d-contract"), ("5 assemble", ["game · docs · API", "hub · this page"], ""), ("6 prove", ["parity", "byte-identical"], "d-good"), ("7 check", ["tests · crawls", "smokes + axe"], "d-good"), ("8 deploy", ["main only", "GitHub Pages"], ""), ("9 verify", ["live smoke", "module hash"], "d-good")], bw=140, wrap=5)}
<div class="table-scroll"><table class="tree"><caption class="sr">The pipeline step by step</caption>
<thead><tr><th scope="col">Step and where</th><th scope="col">What happens</th><th scope="col">Run it</th></tr></thead>
<tbody>{rows}</tbody></table></div>
<p class="note">The full write-up, with the local commands and the toolchain pins, is
<a href="{GH}/swarm-routing.github.io/blob/main/docs/pipeline.md">docs/pipeline.md</a>; the decision behind it is
<a href="{GH}/swarm-routing.github.io/blob/main/docs/adr/0001-the-site-builds-protocols-from-pinned-commits.md">ADR-0001</a>.</p>
</section>
"""
    return page("Pipeline — Colony Arena",
                "The site's simulations run the protocol's own C++ core compiled to WebAssembly: how it is compiled, "
                "proven byte-identical to the native build, packaged and deployed.", root, body, "pipeline")


def project_page(p, pins, data, sink=None) -> str:
    pid = p["id"]
    root = "../../"
    cls = STATUS[p["status"]][1]
    gen, when = p["gen"], as_of(data)
    issues = f'https://github.com/{E(p["repo"])}/issues'

    def href(h):
        return root + h[1:] if h.startswith("/") else h
    links = "".join(f'<a class="button{" primary" if i == 0 else ""}" href="{E(href(h))}">{E(t)}</a>'
                    for i, (t, h) in enumerate(p["links"]))
    facts = "".join(f"<div><dt>{E(k)}</dt><dd>{E(v)}</dd></div>" for k, v in p["facts"])
    pin = pins.get(pid)
    if pin:
        facts += (f'<div><dt>Pinned here</dt><dd><a href="https://github.com/{E(pin["repo"])}/commit/{E(pin["commit"])}">'
                  f'<code>{E(pin["commit"][:12])}</code></a> (protocols.lock)</dd></div>')
    tree = "".join(
        f'<tr class="t-{E(st)}"><th scope="row"><code>{E(path)}</code></th><td>{E(note)}</td>'
        f'<td><span class="lic">{E(lic)}</span></td><td><span class="chip st-{E(st)}">{E(st)}</span></td></tr>'
        for path, note, lic, st in p["tree"])
    def quest(e):
        done = e["status"] == "Done"
        tail = f', closed {E(e["closed"])}' if e.get("closed") else ""
        return (f'<li class="{"q-done" if done else "q-open"}"><span class="q-box" aria-hidden="true">{"✓" if done else ""}</span>'
                f'<span><a href="{E(e["url"])}">#{e["number"]} {E(epic_title(e["title"]))}</a><br>'
                f'<span class="note">{E(e["status"])}{tail} · '
                f'{str(e["completed"]) + " / " + str(e["total"]) + " sub-issues closed" if e["total"] else "no sub-issues"}</span></span></li>')
    order = {"In progress": 0, "Planned": 1}
    live = sorted((e for e in gen["epics"] if e["state"] == "open"), key=lambda e: (order[e["status"]], e["number"]))
    shut = sorted((e for e in gen["epics"] if e["state"] != "open"), key=lambda e: (e.get("closed") or "", e["number"]), reverse=True)
    if p["status"] == "unknown":
        status = (f'<p class="status" data-status="unknown">{chip(p)} <span class="note">This build has no issue data for '
                  f'this repository: see <a href="{issues}">its issues</a>.</span></p>')
        quests = f'<p class="intro">Status not available. The repository\'s <a href="{issues}?q=label%3Aepic">epics</a> are its quests.</p>'
    else:
        rel = (f' · <a href="{E(gen["release"]["url"])}">release {E(gen["release"]["tag"])}</a>' if gen["release"] else "")
        status = (f'<p class="status" data-status="{p["status"]}">{chip(p)} <span class="note">Computed from '
                  f'<a href="{E(gen["source"])}">its {plural(len(gen["epics"]), "epic")}</a>{rel}, as they stood on {when}.</span></p>')
        quests = (f'<p class="intro">The repository\'s <a href="{E(gen["source"])}">epics</a> and their sub-issues, as the issues '
                  f'stood on {E(data["hub"]["asOf"])}: {gen["done"]} of {plural(gen["total"], "sub-issue")} closed.</p>'
                  if gen["epics"] else
                  f'<p class="intro">No epic yet: the work here is tracked as <a href="{issues}">single issues</a> '
                  f'(as of {E(data["hub"]["asOf"])}).</p>')
        if live:
            quests += f'<ul class="quests">{"".join(quest(e) for e in live)}</ul>'
        if shut:
            quests += (f'<details{" open" if not live else ""}><summary>Closed: {plural(len(shut), "epic")}</summary>'
                       f'<ul class="quests">{"".join(quest(e) for e in shut)}</ul></details>')
    sources = "".join("<li>" + (f'<a href="{E(href(h))}">{E(t)}</a>' if h else E(t)) + "</li>"
                      for t, h in p["sources"])
    figs = "".join(project_diagrams(p, pins))
    others = [q for q in data["projects"] if q["id"] != pid]
    nxt = "".join(f'<a href="{root}{PROJECTS}/{E(q["id"])}/">{E(q["name"])}</a>' for q in others)
    body = f"""
<nav class="crumb" aria-label="Breadcrumb"><ol><li><a href="{root}">Colony Arena</a></li><li><a href="{root}{PROJECTS}/">Projects</a></li><li><span aria-current="page">{E(p['name'])}</span></li></ol></nav>
<section class="hero proj {cls}" aria-labelledby="p-t">
  <svg class="hero-g" viewBox="-60 -60 120 100" aria-hidden="true">{glyph(p['glyph'])}</svg>
  <div><p class="eyebrow">{E(p['place'])} · {E(KIND[p['kind']])} · <a href="https://github.com/{E(p['repo'])}">{E(p['repo'])}</a></p>
  <h1 id="p-t">{E(p['name'])}</h1>
  <p class="lede">{E(p['tagline'])}</p>
  {status}
  <p class="cta">{links}</p></div>
</section>
<div class="cols">
<section aria-labelledby="w-t"><h2 id="w-t">What it does</h2>{"".join(f"<p>{md(s)}</p>" for s in p['summary'])}</section>
<aside class="facts" aria-labelledby="f-t"><h2 id="f-t">At a glance</h2><dl>{facts}</dl></aside>
</div>
<section aria-labelledby="d-t"><h2 id="d-t">Diagrams</h2>{figs}</section>
<section aria-labelledby="s-t"><h2 id="s-t">Package structure</h2>
<p class="intro">The repository's layout, its licence per directory (<code>LICENSING.md</code>) and what exists today.</p>
<div class="table-scroll"><table class="tree"><caption class="sr">Directories of {E(p['repo'])}</caption>
<thead><tr><th scope="col">Path</th><th scope="col">What</th><th scope="col">Licence</th><th scope="col">State</th></tr></thead>
<tbody>{tree}</tbody></table></div></section>
<section aria-labelledby="c-t"><h2 id="c-t">Where it sits in the colony</h2>
{dg.org_graph(f"{pid}-org", pid if pid in dg.ORG_NODES else None, f"{E(p['name'])} and its neighbours in the organisation.")}</section>
<section id="quests" aria-labelledby="q-t"><h2 id="q-t">Quests</h2>{quests}</section>
{project_cite(p, pins, data)}{project_refs(p, pins, data, sink=sink)}<section aria-labelledby="r-t"><h2 id="r-t">Sources</h2><ul class="sources">{sources}</ul>
<p class="note">The status and the quests come from the repository's issues and releases{" (" + E(data["hub"]["asOf"]) + ")" if when else ""}; the other
facts on this page are kept by hand from its <code>AGENTS.md</code> (as of {E(data['asOf'])}).</p></section>
<nav class="others" aria-label="Other places">{nxt}</nav>
"""
    return page(f"{p['name']} — Colony Arena", p["tagline"], root, body, "projects")


def group_cards(ps, root) -> str:
    by_kind = [("Protocols: the colonies", [p for p in ps if p["kind"] == "protocol"]),
               ("Foundations, tools and infrastructure", [p for p in ps if p["kind"] != "protocol"])]
    return "".join(f'<h2>{E(h)}</h2><ul class="cards">{"".join(card(p, root) for p in group)}</ul>'
                   for h, group in by_kind)


def projects_index(data) -> str:
    root = "../"
    body = f"""
<nav class="crumb" aria-label="Breadcrumb"><ol><li><a href="{root}">Colony Arena</a></li><li><span aria-current="page">Projects</span></li></ol></nav>
<section class="hero" aria-labelledby="pi-t"><div><p class="eyebrow">swarm-routing · {len(data['projects'])} projects</p>
<h1 id="pi-t">Projects</h1>
<p class="lede">Every project of the organisation has a page: what it does, its diagrams and package structure,
its quests, how to cite it, and the works it rests on. <a href="{root}references/">All references</a> on one page.</p>
<p class="note">{"Each status is computed from the repository's epics and releases, as they stood on " + as_of(data) + "; a project's page links them." if as_of(data) else "Status not available: this build has no issue data."}</p></div></section>
{group_cards(data['projects'], root)}
"""
    return page("Projects — Colony Arena", "Every swarm-routing project: what it does, how to cite it and its references.",
                root, body, "projects")


def references_page(sink) -> str:
    root = "../"
    works = sorted(sink.values(), key=lambda w: w["sort"])
    items = "".join(
        f'<li>{w["item"]} <span class="ref-by">Cited by '
        + ", ".join(f'<a href="{root}{PROJECTS}/{E(i)}/#references">{E(n)}</a>' for i, n in w["by"]) + "</span></li>"
        for w in works)
    body = f"""
<nav class="crumb" aria-label="Breadcrumb"><ol><li><a href="{root}">Colony Arena</a></li><li><span aria-current="page">References</span></li></ol></nav>
<section class="hero" aria-labelledby="ra-t"><div><p class="eyebrow">swarm-routing · {len(works)} works</p>
<h1 id="ra-t">References</h1>
<p class="lede">Every work the <a href="{root}{PROJECTS}/">projects</a> rest on, once, with the projects that cite it.
Each is read from a repository's <code>docs/references.bib</code> when this site is built, and links its DOI.</p></div></section>
<section class="reflist" aria-label="All references">{f'<ul class="sources refs">{items}</ul>' if works else '<p class="intro">No project lists a reference yet.</p>'}</section>
"""
    return page("References — Colony Arena", "Every work the swarm-routing projects cite, with its DOI link.", root, body)


def self_test() -> None:
    data = {"repos": [{"repo": "X", "visibility": "public"}, {"repo": "P", "visibility": "private"}]}
    good = """% header
@software{AHN, author = {Joppi, Daniel}, title = {Tool & co}, year = {2026}, version = {v1},
  doi = {10.5281/zenodo.1}, keywords = {tool}}
@incollection{DDG04, author = {Di Caro, Gianni and Ducatelle, Frederick}, title = {A <b>paper</b>},
  booktitle = {PPSN}, year = {2004}, pages = {461--470}, doi = {https://doi.org/10.1007/x_47},
  keywords = {implemented, compared}}
@phdthesis{W07, author = {Wang, Jianping}, title = {T}, school = {U}, year = {2007},
  url = {https://example.org/t.pdf}, keywords = {background}}
"""
    seen = []

    def fake(text):
        return lambda repo, ref: seen.append((repo, ref)) or text
    p = {"id": "X", "repo": "swarm-routing/X"}
    out = project_refs(p, {}, data, fake(good))
    assert seen == [("swarm-routing/X", "main")], seen
    for want in ('id="refs-t"', "<h3>Implemented</h3>", "<h3>Software it builds on</h3>", "<h3>Background</h3>",
                 'href="https://doi.org/10.1007/x_47"', 'href="https://doi.org/10.5281/zenodo.1"',
                 'href="https://example.org/t.pdf"', "<cite>A &lt;b&gt;paper&lt;/b&gt;</cite>", "Tool &amp; co"):
        assert want in out, (want, out)
    assert out.index("Implemented") < out.index("Software it builds on") < out.index("Background"), out
    assert "Compared against" not in out, out  # one role per entry: implemented wins
    pin = {"X": {"repo": "swarm-routing/X", "commit": "a" * 40}}
    seen.clear()
    assert "aaaaaaaaaaaa" in project_refs(p, pin, data, fake(good)) and seen[0][1] == "a" * 40, seen
    out = project_refs(p, {}, data, fake(good + "@misc{N, title = {No link}}\n@misc{H, title = {Plain}, url = {http://e.org/}}\n"
                                       "@misc{U, title = {Hostless}, url = {https://}}\n"
                                       "@misc{V, title = {Bracket}, url = {https://[bad}}\n"
                                       "@misc{W, title = {Spaced}, url = {https://bad host/path}}\n"
                                       "@misc{Y, title = {Dotted}, url = {https://example..org/p}}\n"))
    assert "No link" not in out and "Plain" not in out and "Hostless" not in out and "Bracket" not in out and "Spaced" not in out and "Dotted" not in out and "A &lt;b&gt;" in out, out
    for empty in ("", "% header alone\n", "@misc{broken, title = {x}", "@misc{N, title = {No link}}"):
        assert project_refs(p, {}, data, fake(empty)) == "", empty
    for repo in ("swarm-routing/P", "swarm-routing/unknown"):
        try:
            project_refs({"id": "P", "repo": repo}, {}, data, fake(good))
        except SystemExit:
            continue
        raise AssertionError(f"fetched the references of {repo}")
    class Truncated:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            raise http.client.IncompleteRead(b"@", 9)
    real, urllib.request.urlopen = urllib.request.urlopen, lambda *a, **k: Truncated()
    try:
        assert fetch_bib("swarm-routing/X", "main") == ""  # a cut-off response: no section, no crash
    finally:
        urllib.request.urlopen = real
    # the site-wide sink: one work per link, with every project that cites it
    sink: dict = {}
    project_refs(p, {}, data, fake(good), sink)
    project_refs({"id": "X2", "repo": "swarm-routing/X", "name": "Second"}, {}, data, fake(good), sink)
    project_refs({"id": "X3", "repo": "swarm-routing/X", "name": "Third"}, {}, data,
                 fake("@misc{D, title = {Same work}, doi = {10.1007/X_47}}\n"), sink)
    assert len(sink) == 3 and sink["https://doi.org/10.1007/x_47"]["by"] == [("X", "X"), ("X2", "Second"), ("X3", "Third")], sink
    refs = references_page(sink)
    assert refs.count('class="doi"') == 3 and 'href="../projects/X2/#references"' in refs, refs
    assert "DOI 10.1007/x_47" in out and ">example.org</a>" in out and 'data-copy="@incollection{DDG04,' in out, out
    # the cite block: every field from CITATION.cff, nothing from its nested blocks
    cff = """# a comment
cff-version: 1.2.0
title: "Tool <X> for NS-3"
abstract: >-
  title: not this
  doi: 10.1/not-this
type: software
authors:
  - family-names: Joppi
    given-names: Daniel Henrique
    orcid: "https://orcid.org/0000-0000-0000-0001"
  - name: "The Team"
version: 2.6.1   # a trailing comment
date-released: "2026-10-29"
license:
  - GPL-2.0-only
  - MIT
repository-code: "https://github.com/swarm-routing/X"
doi: "10.5281/zenodo.123"
identifiers:
  - type: doi
    value: "10.5281/zenodo.999"
references:
  - type: book
    title: "A cited book"
    authors:
      - family-names: "Other"
    doi: "10.1007/other"
"""
    got = parse_cff(cff)
    assert got["title"] == "Tool <X> for NS-3" and got["version"] == "2.6.1" and got["doi"] == "10.5281/zenodo.123", got
    assert got["authors"] == [{"family-names": "Joppi", "given-names": "Daniel Henrique",
                               "orcid": "https://orcid.org/0000-0000-0000-0001"}, {"name": "The Team"}], got
    assert got["license"] == ["GPL-2.0-only", "MIT"], got
    seen.clear()
    out = project_cite(p, pin, data, fake(cff))
    assert seen == [("swarm-routing/X", "a" * 40)], seen
    for want in ('id="cite-t"', "Joppi, Daniel Henrique; The Team (2026). Tool &lt;X&gt; for NS-3 (version 2.6.1) "
                 "[Computer software]. https://doi.org/10.5281/zenodo.123", "@software{x,", "author  = {Joppi, Daniel Henrique and {The Team}}",
                 'href="https://doi.org/10.5281/zenodo.123"', 'href="https://orcid.org/0000-0000-0000-0001"',
                 "2.6.1 · released 2026-10-29", "GPL-2.0-only, MIT", "/blob/" + "a" * 40 + "/CITATION.cff"):
        assert want in out, (want, out)
    for absent in ("zenodo.999", "10.1007/other", "not-this", "A cited book", "Other"):
        assert absent not in out, (absent, out)
    folded = parse_cff('title: >-\n  A folded\n  title\nabstract: |\n  line one\n  line two\ndoi: "10.5281/zenodo.7"  # the concept DOI\n'
                       "version: '1.0' # quoted\nauthors:\n  - name: N\n")
    assert folded["title"] == "A folded title" and folded["abstract"] == "line one\nline two", folded
    assert folded["doi"] == "10.5281/zenodo.7" and folded["version"] == "1.0" and folded["authors"] == [{"name": "N"}], folded
    assert 'href="https://doi.org/10.5281/zenodo.7"' in project_cite(p, {}, data, fake(
        'title: >-\n  A folded\n  title\nauthors:\n  - name: N\ndoi: "10.5281/zenodo.7"  # the concept DOI\n'))
    unreleased = project_cite(p, {}, data, fake('title: T\nauthors:\n  - name: N\ndoi: "javascript:alert(1)"\n'))
    assert "None yet: not released" in unreleased and "https://github.com/swarm-routing/X" in unreleased and "javascript" not in unreleased, unreleased
    for empty in ("", "title: T\n", "authors:\n  - name: N\n", ": : :\n- x\n"):
        assert project_cite(p, {}, data, fake(empty)) == "", empty
    try:
        project_cite({"id": "P", "repo": "swarm-routing/P"}, {}, data, fake(cff))
    except SystemExit:
        pass
    else:
        raise AssertionError("fetched the citation of a private repository")
    stub = redirect("../../projects/X/", "X & co")
    assert 'content="0; url=../../projects/X/"' in stub and 'rel="canonical" href="../../projects/X/"' in stub and "X &amp; co" in stub, stub
    self_test_status()
    print("render_hub.py self-test: ok")


def self_test_status() -> None:
    """The generated fields (#104): the rule, the pages with and without data."""
    import contextlib
    import io
    import tempfile

    def e(n, state="open", done=0, total=0, reason=None, closed=None, title=None):
        return {"number": n, "title": title or f"[epic][x] quest {n}", "url": f"{GH}/R/issues/{n}", "state": state,
                "state_reason": reason, "closed": closed, "total": total, "completed": done}

    def repo(epics=(), tag=None):
        return {"url": f"{GH}/R", "epics": list(epics), "release": {"tag": tag, "url": f"{GH}/R/releases/{tag}"} if tag else None}

    assert [epic_status(x) for x in (e(1), e(2, done=1, total=2), e(3, "closed", reason="completed"),
                                     e(4, "closed", reason="not_planned"))] == ["Planned", "In progress", "Done", "Dropped"]
    assert epic_title("[epic][protocol] ARA as | x") == "ARA as | x" and epic_title("epic: image tests") == "image tests"
    done, drop = e(3, "closed", 2, 2, "completed", "2026-10-01"), e(4, "closed", 0, 1, "not_planned", "2026-10-02")
    cases = [  # (repository, status, text)
        (repo([e(1, done=1, total=3)], "v2.6.1"), "live", "v2.6.1 released, 1 epic in progress"),
        (repo([e(1, done=1, total=3), e(2)], "v0.1.0"), "building", "v0.1.0 released, 1 epic in progress, 1 planned"),
        (repo([e(1, done=1, total=3), e(2, done=2, total=2)]), "building", "no release, 2 epics in progress"),
        (repo([done, drop]), "live", "no release, every epic closed"),
        (repo([drop]), "planned", "no release, every epic closed"),  # nothing was ever done
        (repo([done], "v0.3.0"), "live", "v0.3.0 released, every epic closed"),
        (repo([e(1), done], "v0.1.0"), "building", "v0.1.0 released, 1 epic planned"),
        (repo([], "v0.1.0"), "building", "v0.1.0 released, no epic yet"),
        (repo([e(1), e(2)]), "planned", "no release, 2 epics planned"),
        (repo([]), "planned", "no release, no epic yet"),
        (repo([e(1)], "nightly"), "building", "nightly released, 1 epic planned"),  # a tag that is no version: not 1.0
    ]
    for r, want, text in cases:
        got = repo_status("R", {"repos": {"R": r}})
        assert (got["status"], got["text"]) == (want, text), (got["status"], got["text"], want, text)
        assert got["source"] == f"{GH}/R/issues?q=label%3Aepic", got
    got = repo_status("R", {"repos": {"R": repo([e(1, done=1, total=3), done, drop])}})
    assert (got["done"], got["total"]) == (3, 6), got  # closed sub-issues over all sub-issues, every epic
    for nodata in ({}, {"repos": {}}, {"repos": {"Other": repo()}}):
        got = repo_status("R", nodata)
        assert got["status"] == "unknown" and not got["text"] and not got["epics"], got
    # A record that lacks a field the pages read is no data, never a crash (the build goes on).
    for cut in ({}, [], "x", {"url": f"{GH}/R"}, {"epics": []}, {"url": f"{GH}/R", "epics": [{}]},
                {"url": f"{GH}/R", "epics": [dict(e(1), completed=None)]}, dict(repo(), release={"tag": "v1.0.0"})):
        got = repo_status("R", {"repos": {"R": cut}})
        assert got["status"] == "unknown" and not got["epics"] and got["release"] is None, (cut, got)
    with tempfile.TemporaryDirectory() as d, contextlib.redirect_stderr(io.StringIO()):
        assert load_hub(os.path.join(d, "none.json")) == {}
        for bad in ("{", "[]", '{"repos": {}}', '{"asOf": "today", "repos": {}}'):
            with open(os.path.join(d, "bad.json"), "w") as f:
                f.write(bad)
            assert load_hub(os.path.join(d, "bad.json")) == {}, bad

    # The real projects.json holds no status of its own, and renders with data, with none, and with a project missing.
    with open(os.path.join(HUB, "projects.json"), encoding="utf-8") as f:
        raw = f.read()
    for typed in ('"status"', '"statusText"', '"quests"', '"phases"', '"state"'):
        assert typed not in raw, f"projects.json types {typed}: it comes from data/hub.json"
    names = [r["repo"] for r in json.loads(raw)["repos"]]
    full = {"asOf": "2026-11-13", "repos": {n: repo([e(1, done=1, total=4), e(2), done, drop], "v0.1.0") for n in names}}
    full["repos"]["AntHocNet"] = repo([e(7, done=3, total=3, title="[epic] <b>ants</b>")], "v2.6.1")
    full["repos"]["HOPNET"] = repo([e(1), e(2)])
    full["repos"]["benchmarks"] = repo([], "v0.1.0")
    partial = {"asOf": "2026-11-13", "repos": {k: v for k, v in full["repos"].items() if k not in ("ARA", SITE_REPO)}}

    def render(hubdata):
        data = json.loads(raw)
        for p in data["projects"]:
            p.setdefault("name", p["id"])
        apply_status(data, hubdata)
        pages = {"": hub(data, {}), "projects/": projects_index(data)}
        for p in data["projects"]:
            pages[p["id"]] = project_page(p, {}, data, {})
        return pages

    def down(*a, **k):
        raise OSError("unreachable")
    real, urllib.request.urlopen = urllib.request.urlopen, down  # GitHub unreachable: the build still succeeds
    try:
        with contextlib.redirect_stderr(io.StringIO()):
            with_data, without, missing = render(full), render({}), render(partial)
    finally:
        urllib.request.urlopen = real
    stamp = '<time data-asof datetime="2026-11-13">2026-11-13</time>'
    front = with_data[""]
    n_known, per = len(names), 3 + 2 + 0 + 1  # per repository of the default fixture: 1/4 + 0/0 + 2/2 + 0/1
    want_done, want_total = (n_known - 3) * 3 + 3, (n_known - 3) * 7 + 3
    assert per == 6 and f'<p class="xp-v">{want_done}<span>/ {want_total} sub-issues closed</span></p>' in front, front[:3000]
    assert stamp in front and "milestones" not in front
    assert stamp in with_data["projects/"] and "data-asof" not in without["projects/"]
    assert front.count('data-status="planned"') == 3 and front.count('class="padlock"') == 1, "HOPNET: card, place, table row; one padlock"
    assert f'<a href="{GH}/R/issues/1">ARA#1 quest 1</a>' in front and "#2 quest 2" not in front  # the log: epics in progress only
    assert f'<a href="{GH}/R/issues?q=label%3Aepic">epics</a>' in front  # each repository's status links its issues
    # The package diagram follows the project's own package table, not whether this site builds it.
    solid, dashed = protocol_pkgs("ARA", "ara", False, [["core/", "", "", "present"], ["ns3/", "", "", "present"]]), protocol_pkgs("T", "t", False, [["core/", "", "", "planned"], ["docs/adr/", "", "", "present"]])
    assert solid.count("d-planned") + 2 == dashed.count("d-planned"), (solid.count("d-planned"), dashed.count("d-planned"))
    ant = with_data["AntHocNet"]
    assert 'data-status="live"' in ant and "Unlocked: v2.6.1 released, 1 epic in progress" in ant, ant[:3000]
    assert f'<a href="{GH}/R/issues/7">#7 &lt;b&gt;ants&lt;/b&gt;</a>' in ant and "<b>ants</b>" not in ant
    assert f'Computed from <a href="{GH}/R/issues?q=label%3Aepic">its 1 epic</a> · <a href="{GH}/R/releases/v2.6.1">release v2.6.1</a>' in ant
    assert stamp in ant and "3 / 3 sub-issues closed" in ant
    ara = with_data["ARA"]
    assert "Under construction: v0.1.0 released, 1 epic in progress, 1 planned" in ara
    assert ara.index("#1 quest 1") < ara.index("#2 quest 2") < ara.index("<details>") < ara.index("#4 quest 4") < ara.index("#3 quest 3")
    assert "Dropped, closed 2026-10-02" in ara and "Done, closed 2026-10-01" in ara and ara.count("q-done") == 1
    assert 'data-status="planned"' in with_data["HOPNET"] and "Locked: no release, 2 epics planned" in with_data["HOPNET"]
    assert "No epic yet" in with_data["benchmarks"] and '<ul class="quests">' not in with_data["benchmarks"]
    for name, page_ in without.items():
        assert "data-asof" not in page_ and 'data-status="live"' not in page_ and 'class="padlock"' not in page_, name
        assert "tatus not available" in page_, name
    assert without[""].count('data-status="unknown"') == 10 + 11 + len(names), "every card, place and table row"
    assert "Status not available" in missing["ARA"] and 'data-status="unknown"' in missing["ARA"]
    assert '<a href="https://github.com/swarm-routing/ARA/issues">its issues</a>' in missing["ARA"]
    assert "Under construction" in missing["BeeAdHoc"] and stamp in missing[""]
    assert missing[""].count('data-status="unknown"') == 5, "ARA: card, place, table row; this site: place, table row"


def main(argv) -> int:
    if argv == ["--self-test"]:
        self_test()
        return 0
    if len(argv) != 1:
        print(__doc__, file=sys.stderr)
        return 2
    out = argv[0]
    with open(os.path.join(HUB, "projects.json"), encoding="utf-8") as f:
        data = json.load(f)
    for p in data["projects"]:
        p.setdefault("name", p["id"].replace("ns3-swarm-core", "swarm-core").replace("org-commons", "Org commons"))
    apply_status(data, load_hub())
    pins = lock.read()
    os.makedirs(os.path.join(out, "arena"), exist_ok=True)
    for name in ("arena.css", "arena.js"):
        shutil.copyfile(os.path.join(HUB, name), os.path.join(out, "arena", name))
    with open(os.path.join(out, "index.html"), "w", encoding="utf-8") as f:
        f.write(hub(data, pins))
    os.makedirs(os.path.join(out, "pipeline"), exist_ok=True)
    with open(os.path.join(out, "pipeline", "index.html"), "w", encoding="utf-8") as f:
        f.write(pipeline_page(pins))
    def write(rel: str, text: str) -> None:
        d = os.path.join(out, rel)
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "index.html"), "w", encoding="utf-8") as f:
            f.write(text)
    sink: dict = {}
    for p in data["projects"]:
        write(os.path.join(PROJECTS, p["id"]), project_page(p, pins, data, sink))
        write(os.path.join("arena", p["id"]), redirect(f"../../{PROJECTS}/{p['id']}/", f"{p['name']} — Colony Arena"))
    write(PROJECTS, projects_index(data))
    write("arena", redirect(f"../{PROJECTS}/", "Projects — Colony Arena"))
    write("references", references_page(sink))
    print(f"render_hub.py: hub, pipeline page, {len(data['projects'])} project pages, the references page "
          f"({len(sink)} works) and the /arena/ redirects in {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
