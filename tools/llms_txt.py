#!/usr/bin/env python3
# Copyright (c) 2026 Daniel Joppi (https://github.com/swarm-routing)
# SPDX-License-Identifier: MIT OR GPL-2.0-only
"""Write the site's llms.txt and llms-full.txt (https://llmstxt.org; #234).

Generated from the data tools/render_hub.py reads, never typed: the facts of
site/hub/projects.json (tagline, summary, facts, links, package tree, sources)
and the status data/hub.json gives each repository (repo_status, the hub's
rule); each site page's title and description, and the file's summary, are
read from the pages render_hub.py wrote to <out>, so it runs after it. Only public repositories: a project whose repository projects.json
does not list as public is refused, as render_hub.py refuses it.
  <out>/llms.txt       the index: the site's pages, every project page with
                       its tagline and status, swarm-core's ports, the
                       benchmark and marker schemas, AntHocNet's docs and API
  <out>/llms-full.txt  the same, with each project's page as Markdown: its
                       summary, facts, package tree, quests (its epics,
                       data/hub.json), links and sources. Its citation and
                       references are fetched from the repository at build
                       time; they stay on the page, which the entry links
Deterministic: the order of projects.json, no clock; the only date is the
issue data's own (data/hub.json asOf). Stdlib only, no network.

Usage: python3 tools/llms_txt.py <out-dir>
       python3 tools/llms_txt.py --self-test
"""
from __future__ import annotations

import html
import json
import os
import re
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import render_hub as rh

SITE = "https://swarm-routing.github.io"
PAGES = ["/", f"/{rh.PROJECTS}/", "/references/", "/images/", "/pipeline/"]  # the hub first: its description is the summary
PORT = re.compile(r"`(I[A-Z][A-Za-z]+)`")
SCHEMA = re.compile(r"schema|contract", re.IGNORECASE)
TITLE = re.compile(r"<title>([^<]*)</title>")
DESC = re.compile(r'<meta name="description" content="([^"]*)">')


def pages(out: str) -> list[tuple[str, str, str]]:
    """Each site page's (title, url, description), from the page render_hub.py wrote."""
    got = []
    for path in PAGES:
        f = os.path.join(out, path.strip("/"), "index.html")
        try:
            with open(f, encoding="utf-8") as fh:
                text = fh.read()
        except OSError as e:
            raise SystemExit(f"llms_txt.py: {e}; run tools/render_hub.py {out} first") from e
        t, d = TITLE.search(text), DESC.search(text)
        if not (t and d):
            raise SystemExit(f"llms_txt.py: {f} has no <title> or no description")
        got.append((html.unescape(t.group(1)), SITE + path, html.unescape(d.group(1))))
    return got


def url(link: str) -> str:
    """A site path made absolute; any other link as it is."""
    return SITE + link if link.startswith("/") else link


def absolute(md: str) -> str:
    """Markdown with every site-relative link target made absolute."""
    return re.sub(r"\]\((/[^)\s]*)\)", lambda m: f"]({SITE}{m.group(1)})", md)


def one_line(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def load(hubdata: dict | None = None) -> dict:
    """projects.json with each project's name and generated status, as render_hub.py's main() sees it."""
    with open(os.path.join(rh.HUB, "projects.json"), encoding="utf-8") as f:
        data = json.load(f)
    for p in data["projects"]:
        p.setdefault("name", p["id"].replace("org-commons", "Org commons"))
    rh.check_groups(data)
    rh.apply_status(data, rh.load_hub() if hubdata is None else hubdata)
    return data


def public(data) -> None:
    pub = {r["repo"] for r in data["repos"] if r.get("visibility") == "public"}
    for p in data["projects"]:
        if p["repo"].split("/", 1)[1] not in pub:
            raise SystemExit(f"llms_txt.py: refusing {p['repo']}: not a public repository in projects.json")


def by_id(data, pid: str):
    return next((p for p in data["projects"] if p["id"] == pid), None)


def status(p, data) -> str:
    label = rh.STATUS[p["status"]][0]
    if p["status"] == "unknown":
        return label
    return f"{label}: {p['statusText']} (from its issues, {data['hub'].get('asOf')})"


def ports(data) -> tuple[list[str], list[str]]:
    """swarm-core's ports as its summary in projects.json names them: (released, planned)."""
    p = by_id(data, "swarm-core")
    have: list[str] = []
    plan: list[str] = []
    for para in (p or {}).get("summary", []):
        into = plan if para.startswith("Planned") else have
        for name in PORT.findall(para):
            if name not in have and name not in plan:
                into.append(name)
    return have, plan


def core_tree(data) -> str:
    """swarm-core's core/ at its latest release (data/hub.json), else main."""
    p = by_id(data, "swarm-core")
    rel = p["gen"]["release"] if p else None
    return f"{rh.GH}/swarm-core/tree/{rel['tag'] if rel else 'main'}/core"


def schemas(data) -> list[tuple[str, str, str]]:
    """The schema and contract entries of benchmarks and sim-tools, each URL once: (title, url, note)."""
    out = []
    for pid in ("benchmarks", "sim-tools"):
        p = by_id(data, pid)
        if not p:
            continue
        for row in p.get("tree", []):
            if SCHEMA.search(row[0]):
                out.append((f"{pid} {row[0]}", f"https://github.com/{p['repo']}/tree/main/{row[0].rstrip('/')}",
                            f"{row[1]} ({row[3]})"))
        for label, link in p.get("links", []) + p.get("sources", []):
            if SCHEMA.search(label) and url(link) not in (u for _, u, _ in out):
                out.append((f"{pid}: {label}", url(link), ""))
    return out


def anthocnet_docs(data) -> list[tuple[str, str]]:
    """Every link into /AntHocNet/ the projects carry, once, in the order met."""
    seen: dict[str, str] = {}
    for p in data["projects"]:
        for label, link in p.get("links", []) + p.get("sources", []):
            if link.startswith("/AntHocNet/") and link not in seen:
                seen[link] = label
    return [(label, url(link)) for link, label in seen.items()]


def item(title: str, link: str, note: str = "") -> str:
    return f"- [{title}]({link})" + (f": {one_line(note)}" if note else "")


def head(data) -> list[str]:
    asof = data["hub"].get("asOf")
    return [
        "# Colony Arena",
        "",
        f"> {data['pages'][0][2]}",
        "",
        "Generated by tools/llms_txt.py from site/hub/projects.json and data/hub.json"
        + (f" (issue data as of {asof})" if asof else " (no issue data: every status reads 'status not available')")
        + "; every project is a public repository under https://github.com/swarm-routing. "
        "A project's page is /projects/<id>/.",
    ]


def common(data) -> list[str]:
    """The sections both files share, after the project list."""
    lines = ["", "## swarm-core ports", ""]
    have, plan = ports(data)
    lines += [item(n, core_tree(data), "released port") for n in have]
    lines += [item(n, f"{SITE}/{rh.PROJECTS}/swarm-core/", "planned port (swarm-core's epic)") for n in plan]
    lines += ["", "## Benchmark and marker schemas", ""]
    lines += [item(t, u, n) for t, u, n in schemas(data)]
    lines += ["", "## AntHocNet docs and API", ""]
    lines += [item(t, u) for t, u in anthocnet_docs(data)]
    return lines


def project_item(p, data) -> str:
    return item(p["name"], f"{SITE}/{rh.PROJECTS}/{p['id']}/", f"{p['tagline']} Status: {status(p, data)}.")


def index(data) -> str:
    lines = head(data) + ["", "## Site", ""] + [item(t, u, n) for t, u, n in data["pages"]]
    for region in rh.REGIONS:
        ps = [p for p in data["projects"] if p["group"] == region]
        if ps:
            lines += ["", f"## {region}", ""] + [project_item(p, data) for p in ps]
    lines += common(data)
    lines += ["", "## Optional", "",
              item("llms-full.txt", f"{SITE}/llms-full.txt", "every project page as Markdown: summary, facts, package tree, quests, links"),
              item("Site source", f"{rh.GH}/{rh.SITE_REPO}", "how this site is built")]
    return "\n".join(lines) + "\n"


def full(data) -> str:
    lines = head(data) + ["", "## Site", ""] + [item(t, u, n) for t, u, n in data["pages"]]
    lines += common(data)
    for region in rh.REGIONS:
        for p in (p for p in data["projects"] if p["group"] == region):
            lines += ["", f"## {p['name']}", "",
                      f"Page: [/{rh.PROJECTS}/{p['id']}/]({SITE}/{rh.PROJECTS}/{p['id']}/)  ",
                      f"Repository: [{p['repo']}](https://github.com/{p['repo']})  ",
                      f"Region: {region} · kind: {p['kind']}  ",
                      f"Status: {status(p, data)}", "", absolute(p["tagline"])]
            lines += ["", *(x for para in p.get("summary", []) for x in (absolute(para), ""))]
            if p.get("facts"):
                lines += ["### Facts", ""] + [f"- {k}: {one_line(v)}" for k, v in p["facts"]] + [""]
            if p.get("tree"):
                lines += ["### Package structure", ""]
                lines += [f"- `{r[0]}`: {one_line(r[1])} ({r[2]}, {r[3]})" for r in p["tree"]] + [""]
            if p.get("links"):
                lines += ["### Links", ""] + [item(t, url(u)) for t, u in p["links"]] + [""]
            if p.get("sources"):
                lines += ["### Sources", ""] + [item(t, url(u)) for t, u in p["sources"]] + [""]
            if p["gen"]["epics"]:
                lines += ["### Quests (its epics)", ""]
                lines += [item(rh.epic_title(e["title"]), e["url"],
                               f"{e['status']}, {e['completed']}/{e['total']} sub-issues closed")
                          for e in p["gen"]["epics"]] + [""]
            lines += [f"How to cite it and its references: [its page]({SITE}/{rh.PROJECTS}/{p['id']}/)", ""]
            while lines[-1] == "":
                lines.pop()
    return "\n".join(lines) + "\n"


def write(out: str, data) -> None:
    public(data)
    data["pages"] = pages(out)
    os.makedirs(out, exist_ok=True)
    for name, text in (("llms.txt", index(data)), ("llms-full.txt", full(data))):
        with open(os.path.join(out, name), "w", encoding="utf-8", newline="\n") as f:
            f.write(text)


def fake_pages(out: str) -> None:
    """The pages render_hub.py would write, as far as pages() reads them."""
    for path in PAGES:
        os.makedirs(os.path.join(out, path.strip("/")), exist_ok=True)
        with open(os.path.join(out, path.strip("/"), "index.html"), "w", encoding="utf-8") as f:
            f.write(f'<title>T {path} &amp; co</title><meta name="description" content="D {path} &#x27;q&#x27;">')


def self_test() -> None:
    tmp = tempfile.TemporaryDirectory()
    fake_pages(tmp.name)

    def load(hubdata=None):
        d = globals()["load"](hubdata)
        d["pages"] = pages(tmp.name)
        return d
    real = load()
    a, b = index(real), full(real)
    assert a == index(load()) and b == full(load()), "not deterministic"
    lines = a.splitlines()
    assert lines[0] == "# Colony Arena" and lines[2] == "> D / 'q'", lines[:3]
    assert f"- [T /pipeline/ & co]({SITE}/pipeline/): D /pipeline/ 'q'" in a
    for p in real["projects"]:
        assert f"]({SITE}/projects/{p['id']}/)" in a, p["id"]
        assert f"## {p['name']}\n" in b and f"]({SITE}/projects/{p['id']}/)" in b, p["id"]
    for proto in ("AntHocNet", "ARA", "BeeAdHoc", "Termite", "HOPNET", "POSANT", "BeeSensor", "Q-Swarm"):
        assert f"- [{proto}]({SITE}/projects/{proto}/)" in a, proto
    have, plan = ports(real)
    assert "IClock" in have and "ITransport" in plan and not set(have) & set(plan), (have, plan)
    sch = [u for _, u, _ in schemas(real)]
    assert any("benchmarks/tree/main/schemas" in u for u in sch) and len(sch) == len(set(sch)), sch
    assert f"]({SITE}/AntHocNet/docs/)" in a and f"]({SITE}/AntHocNet/api/)" in a
    assert "](/" not in a and "](/" not in b, "a site link left relative"
    assert not any(x != x.rstrip() for x in a.splitlines() if not x.endswith("  ")), "trailing space"
    # no issue data: every status reads 'status not available', the build goes on
    bare = load({})
    assert "Status: Status not available." in index(bare) and "no issue data" in index(bare)
    # a generated status and its date
    hub = {"asOf": "2026-11-13", "repos": {"ARA": {"url": f"{rh.GH}/ARA", "release": {"tag": "v0.1.0", "url": "u"},
                                                   "epics": []}}}
    assert "Status: Under construction: v0.1.0 released, no epic yet (from its issues, 2026-11-13)." in index(load(hub))
    hub["repos"]["ARA"]["epics"] = [{"number": 2, "title": "[epic][protocol] ARA core", "url": f"{rh.GH}/ARA/issues/2",
                                     "state": "open", "total": 4, "completed": 1}]
    assert f"- [ARA core]({rh.GH}/ARA/issues/2): In progress, 1/4 sub-issues closed" in full(load(hub))
    # only public repositories
    priv = load({})
    next(r for r in priv["repos"] if r["repo"] == "ARA")["visibility"] = "private"
    with tempfile.TemporaryDirectory() as d:
        try:
            write(d, real)
            raise AssertionError("wrote llms.txt before render_hub.py's pages")
        except SystemExit as e:
            assert "run tools/render_hub.py" in str(e), e
        fake_pages(d)
        try:
            write(d, priv)
            raise AssertionError("wrote llms.txt with a private repository")
        except SystemExit as e:
            assert "refusing swarm-routing/ARA" in str(e), e
        assert not [n for n in os.listdir(d) if n.endswith(".txt")], os.listdir(d)
        write(d, real)
        assert sorted(n for n in os.listdir(d) if n.endswith(".txt")) == ["llms-full.txt", "llms.txt"]
    tmp.cleanup()
    assert absolute("[x](/projects/a/) [y](https://e.org/)") == f"[x]({SITE}/projects/a/) [y](https://e.org/)"
    print("llms_txt.py self-test: ok")


def main(argv) -> int:
    if argv == ["--self-test"]:
        self_test()
        return 0
    if len(argv) != 1:
        print(__doc__, file=sys.stderr)
        return 2
    data = load()
    write(argv[0], data)
    print(f"llms_txt.py: llms.txt and llms-full.txt ({len(data['projects'])} projects) in {argv[0]}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
