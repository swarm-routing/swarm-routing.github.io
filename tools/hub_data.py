#!/usr/bin/env python3
# Copyright (c) 2026 Daniel Joppi (https://github.com/swarm-routing)
# SPDX-License-Identifier: MIT OR GPL-2.0-only
"""Write data/hub.json: what the issues say about each public repository (#104).

For every repository site/hub/projects.json lists as public, reads from the
GitHub REST API:
  repos/<org>/<repo>                              it must be public there too
  repos/<org>/<repo>/issues?labels=epic&state=all its epics and their sub-issue
                                                  counts (sub_issues_summary)
  repos/<org>/<repo>/releases                     its latest release (not a
                                                  draft, not a pre-release)
The epics are the source swarm-routing/.github's tools/epics/epics.py reads,
and an epic's status is derived the same way (epic_status below), never typed.
tools/render_hub.py reads the file at build time, so the Pages build makes no
API call for it; a build without the file still succeeds.

The file is deterministic: repositories sorted by name, epics by number, keys
sorted, and one date, `asOf` (UTC). When nothing but the date would change the
file is left alone, so `asOf` is the day the issues were last seen to differ.
Any failed request, or a repository the API says is not public, exits non-zero
and writes nothing.

Usage: python3 tools/hub_data.py [--out data/hub.json] [--as-of YYYY-MM-DD] [--check]
       python3 tools/hub_data.py --self-test
--check writes nothing and exits 1 when the file is stale. A token in
GH_TOKEN or GITHUB_TOKEN is sent when set (60 requests an hour without one;
a run makes three per repository). Stdlib only.
"""
from __future__ import annotations

import datetime
import json
import os
import re
import sys
import tempfile
import urllib.error
import urllib.request

ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
PROJECTS = os.path.join(ROOT, "site", "hub", "projects.json")
OUT = os.path.join(ROOT, "data", "hub.json")
ORG = "swarm-routing"
API = "https://api.github.com/"
NAME = re.compile(r"^[A-Za-z0-9._-]+$")


def api_get(path: str):
    """One GET of the REST API, as JSON; SystemExit on any failure."""
    req = urllib.request.Request(API + path, headers={
        "Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "hub-data"})
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, ValueError) as e:
        raise SystemExit(f"hub_data.py: GET {path}: {e}; nothing written") from None


def pages(get, path: str) -> list:
    out, page = [], 1
    while True:
        batch = get(f"{path}{'&' if '?' in path else '?'}per_page=100&page={page}")
        if not isinstance(batch, list):
            raise SystemExit(f"hub_data.py: GET {path}: expected a list; nothing written")
        out += batch
        if len(batch) < 100:
            return out
        page += 1


def epic_of(issue: dict) -> dict:
    s = issue.get("sub_issues_summary") or {}
    return {"number": issue["number"], "title": issue["title"], "url": issue["html_url"],
            "state": issue["state"], "state_reason": issue.get("state_reason"),
            "closed": (issue.get("closed_at") or "")[:10] or None,
            "total": s.get("total", 0), "completed": s.get("completed", 0)}


def epic_status(e: dict) -> str:
    """As swarm-routing/.github tools/epics/epics.py `status`."""
    if e["state"] == "closed":
        return "Dropped" if e.get("state_reason") == "not_planned" else "Done"
    return "In progress" if e["completed"] else "Planned"


def public_repos(projects: dict) -> list[str]:
    """The repositories projects.json marks public, sorted; others are never read."""
    names = sorted({r["repo"] for r in projects["repos"] if r.get("visibility") == "public"}, key=str.lower)
    bad = [n for n in names if not NAME.match(n)]
    if bad:
        raise SystemExit(f"hub_data.py: bad repository names {bad}; nothing written")
    return names


def collect(projects: dict, get=api_get) -> dict:
    """{name: {url, release, epics}} for every public repository."""
    repos = {}
    for name in public_repos(projects):
        meta = get(f"repos/{ORG}/{name}")
        if meta.get("private") is not False or meta.get("visibility", "public") != "public":
            raise SystemExit(f"hub_data.py: {ORG}/{name} is not public on GitHub, but projects.json "
                             "lists it as public; nothing written")
        issues = pages(get, f"repos/{ORG}/{name}/issues?labels=epic&state=all")
        epics = sorted((epic_of(i) for i in issues if "pull_request" not in i), key=lambda e: e["number"])
        rel = next((r for r in pages(get, f"repos/{ORG}/{name}/releases")
                    if not r.get("draft") and not r.get("prerelease")), None)
        repos[name] = {"url": meta["html_url"], "epics": epics,
                       "release": {"tag": rel["tag_name"], "url": rel["html_url"]} if rel else None}
    return repos


def render(repos: dict, as_of: str) -> str:
    doc = {"asOf": as_of, "org": ORG, "repos": repos,
           "note": "Generated by tools/hub_data.py from each public repository's issues labelled `epic` "
                   "(with their sub-issue counts) and its latest release; never edit by hand."}
    return json.dumps(doc, indent=1, sort_keys=True, ensure_ascii=False) + "\n"


def refresh(out: str, as_of: str, check: bool, get=api_get, projects_path: str = PROJECTS) -> int:
    with open(projects_path, encoding="utf-8") as f:
        projects = json.load(f)
    repos = collect(projects, get)  # raises before anything is written
    old = None
    if os.path.exists(out):
        with open(out, encoding="utf-8") as f:
            try:
                old = json.load(f)
            except ValueError:
                old = None
    n = sum(len(r["epics"]) for r in repos.values())
    what = f"{len(repos)} repositories, {n} epics"
    if old is not None and old.get("repos") == repos:
        print(f"hub_data.py: {out}: up to date ({what}; unchanged since {old.get('asOf')})")
        return 0
    if check:
        print(f"hub_data.py: {out}: stale (run tools/hub_data.py to refresh)")
        return 1
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    tmp = out + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(render(repos, as_of))
    os.replace(tmp, out)
    print(f"hub_data.py: {out}: written ({what}, as of {as_of})")
    return 0


# --- self-test -----------------------------------------------------------------


def self_test() -> None:
    def issue(n, title, state="open", done=0, total=0, reason=None, closed=None, pr=False):
        i = {"number": n, "title": title, "html_url": f"https://github.com/{ORG}/A/issues/{n}", "state": state,
             "state_reason": reason, "closed_at": closed,
             "sub_issues_summary": {"total": total, "completed": done, "percent_completed": 0}}
        if pr:
            i["pull_request"] = {}
        return i

    many = [issue(n, f"e{n}") for n in range(200, 80, -1)]  # 120: two pages
    api = {
        f"repos/{ORG}/A": {"private": False, "html_url": f"https://github.com/{ORG}/A"},
        f"repos/{ORG}/B": {"private": False, "visibility": "public", "html_url": f"https://github.com/{ORG}/B"},
        f"repos/{ORG}/A/issues?labels=epic&state=all&per_page=100&page=1": [
            issue(9, "[epic] later", total=2), issue(3, "[epic] going", done=1, total=2),
            issue(1, "[epic] shipped", "closed", 4, 4, "completed", "2026-10-01T00:00:00Z"),
            issue(2, "[epic] abandoned", "closed", 0, 1, "not_planned", "2026-10-05T00:00:00Z"),
            issue(7, "a pull request labelled epic", pr=True)],
        f"repos/{ORG}/A/releases?per_page=100&page=1": [
            {"tag_name": "v2.0.0-rc1", "html_url": "u-rc", "prerelease": True, "draft": False},
            {"tag_name": "v1.2.0", "html_url": "u-12", "prerelease": False, "draft": False},
            {"tag_name": "v1.1.0", "html_url": "u-11", "prerelease": False, "draft": False}],
        f"repos/{ORG}/B/issues?labels=epic&state=all&per_page=100&page=1": many[:100],
        f"repos/{ORG}/B/issues?labels=epic&state=all&per_page=100&page=2": many[100:],
        f"repos/{ORG}/B/releases?per_page=100&page=1": [],
    }
    asked = []

    def fake(path):
        asked.append(path)
        if path not in api:
            raise SystemExit(f"hub_data.py: GET {path}: HTTP 404; nothing written")
        return api[path]

    projects = {"repos": [{"repo": "B", "visibility": "public"}, {"repo": "A", "visibility": "public"},
                          {"repo": "Secret", "visibility": "private"}, {"repo": "NoWord"}]}
    with tempfile.TemporaryDirectory() as d:
        pj, out = os.path.join(d, "projects.json"), os.path.join(d, "data", "hub.json")
        with open(pj, "w") as f:
            json.dump(projects, f)
        assert refresh(out, "2026-11-13", False, fake, pj) == 0
        assert not any("Secret" in p or "NoWord" in p for p in asked), asked  # only public repositories are read
        with open(out, encoding="utf-8") as f:
            text = f.read()
        got = json.loads(text)
        assert got["asOf"] == "2026-11-13" and list(got["repos"]) == ["A", "B"], got
        a = got["repos"]["A"]
        assert [e["number"] for e in a["epics"]] == [1, 2, 3, 9], a  # sorted, the pull request dropped
        assert [epic_status(e) for e in a["epics"]] == ["Done", "Dropped", "In progress", "Planned"], a
        assert a["epics"][0]["closed"] == "2026-10-01" and a["epics"][2] == {
            "number": 3, "title": "[epic] going", "url": f"https://github.com/{ORG}/A/issues/3", "state": "open",
            "state_reason": None, "closed": None, "total": 2, "completed": 1}, a["epics"]
        assert a["release"] == {"tag": "v1.2.0", "url": "u-12"}, a  # newest that is neither draft nor pre-release
        b = got["repos"]["B"]
        assert len(b["epics"]) == 120 and b["epics"][0]["number"] == 81 and b["release"] is None, b
        # No timestamp but asOf, and the same answers give the same bytes.
        assert not re.search(r"\d\dT\d\d:\d\d", text), "a timestamp in the data file"
        assert render(collect(projects, fake), "2026-11-13") == text
        # Another day, the same issues: the file and its date stay.
        assert refresh(out, "2026-11-20", False, fake, pj) == 0
        with open(out, encoding="utf-8") as f:
            assert f.read() == text
        assert refresh(out, "2026-11-20", True, fake, pj) == 0
        # A change is written with the new date; --check reports it and writes nothing.
        api[f"repos/{ORG}/A/issues?labels=epic&state=all&per_page=100&page=1"][1]["sub_issues_summary"]["completed"] = 2
        assert refresh(out, "2026-11-20", True, fake, pj) == 1
        with open(out, encoding="utf-8") as f:
            assert f.read() == text
        assert refresh(out, "2026-11-20", False, fake, pj) == 0
        with open(out, encoding="utf-8") as f:
            new = json.load(f)
        assert new["asOf"] == "2026-11-20" and new["repos"]["A"]["epics"][2]["completed"] == 2, new
        # A failed request (here the last one of the run) leaves the file as it was.
        with open(out, encoding="utf-8") as f:
            before = f.read()
        del api[f"repos/{ORG}/B/releases?per_page=100&page=1"]
        api[f"repos/{ORG}/A/issues?labels=epic&state=all&per_page=100&page=1"].pop()
        try:
            refresh(out, "2026-11-21", False, fake, pj)
            raise AssertionError("a failed request did not stop the run")
        except SystemExit as e:
            assert "nothing written" in str(e), e
        with open(out, encoding="utf-8") as f:
            assert f.read() == before
        assert not os.path.exists(out + ".tmp")
        # With no file yet, a failure creates none.
        fresh = os.path.join(d, "none", "hub.json")
        try:
            refresh(fresh, "2026-11-21", False, fake, pj)
            raise AssertionError("a failed request did not stop the run")
        except SystemExit:
            pass
        assert not os.path.exists(fresh)
        # A repository GitHub says is private is refused, whatever projects.json says.
        api[f"repos/{ORG}/B/releases?per_page=100&page=1"] = []
        api[f"repos/{ORG}/A"]["private"] = True
        try:
            refresh(out, "2026-11-21", False, fake, pj)
            raise AssertionError("a private repository was read")
        except SystemExit as e:
            assert "not public" in str(e), e
        with open(out, encoding="utf-8") as f:
            assert f.read() == before
    # The real fetcher turns a network failure into the same refusal.
    real, urllib.request.urlopen = urllib.request.urlopen, lambda *a, **k: (_ for _ in ()).throw(OSError("unreachable"))
    try:
        api_get("repos/x/y")
        raise AssertionError("api_get swallowed a failure")
    except SystemExit as e:
        assert "unreachable" in str(e) and "nothing written" in str(e), e
    finally:
        urllib.request.urlopen = real
    print("hub_data.py self-test: ok")


def main(argv: list[str]) -> int:
    if argv == ["--self-test"]:
        self_test()
        return 0
    out, as_of, check = OUT, datetime.datetime.now(datetime.timezone.utc).date().isoformat(), False
    it = iter(argv)
    for a in it:
        if a == "--check":
            check = True
        elif a in ("--out", "--as-of"):
            v = next(it, None)
            if v is None:
                print(__doc__, file=sys.stderr)
                return 2
            if a == "--out":
                out = v
            else:
                as_of = v
        else:
            print(__doc__, file=sys.stderr)
            return 2
    if not re.match(r"^\d{4}-\d\d-\d\d$", as_of):
        print(f"hub_data.py: --as-of {as_of!r} is not a YYYY-MM-DD date", file=sys.stderr)
        return 2
    return refresh(out, as_of, check)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
