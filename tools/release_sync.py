#!/usr/bin/env python3
# Copyright (c) 2026 Daniel Joppi (https://github.com/swarm-routing)
# SPDX-License-Identifier: MIT OR GPL-2.0-only
"""What an org release changed that the site's hand-kept facts may need (#122).

A release of a public org repository reaches the site three ways (epic #120):
the Pages rebuild (citation, references, DOIs), data/hub.json (statuses,
quests), and, for what needs judgement, one `[release-sync] <repo> <tag>`
issue. This script writes that issue's body; release-sync.yml opens the issue
and the release-sync skill (.claude/skills/release-sync/) works it. It reads
and prints; it never edits a file or writes to GitHub.

  python3 tools/release_sync.py body <owner/repo> <tag> [--prev <tag>]
      the issue body: the release, the files the site's facts come from that
      changed between the previous release and this one (with the AGENTS.md
      status and the changelog section), and the checklist; --prev defaults
      to the release before <tag>
  python3 tools/release_sync.py title <owner/repo> <tag>
  python3 tools/release_sync.py recent [--days N]
      `<owner/repo> <tag>` for every release of a public repository
      published in the last N days (default 14), oldest first: the weekly
      backstop's candidates (release-sync.yml opens the ones with no issue yet)
  python3 tools/release_sync.py --self-test

Only the repositories site/hub/projects.json marks public are read (exit 3
for any other, so the workflow skips it). Any failed request exits 1 and
prints nothing on stdout. A token in GH_TOKEN or GITHUB_TOKEN is sent when
set. Stdlib only.
"""

from __future__ import annotations

import base64
import datetime
import json
import os
import re
import sys
import urllib.error
import urllib.request

ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
PROJECTS = os.path.join(ROOT, "site", "hub", "projects.json")
LOCK = os.path.join(ROOT, "protocols.lock")
ORG = "swarm-routing"
SITE = "https://swarm-routing.github.io"
TAG = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]*$")
# The files a project page's hand-kept facts are written from (projects.json
# cites AGENTS.md "What this repo is"), and the ones the build reads itself.
WATCHED = (
    "AGENTS.md",
    "README.md",
    "CITATION.cff",
    "docs/references.bib",
    "docs/fidelity.md",
    "docs/roadmap.md",
    "LICENSING.md",
    "CHANGELOG.md",
)
REBUILT = {"CITATION.cff", "docs/references.bib"}  # the build reads these at its pin or main
MAX_LINES = 40
COMPARE_CAP = 300  # GitHub lists at most 300 files in a compare


class Gone(Exception):
    """A 404: the file or ref does not exist."""


def _get(url: str):
    headers = {
        "User-Agent": "release-sync",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    req = urllib.request.Request(url, headers=headers)
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            body = r.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        if e.code == 404:
            raise Gone(url) from None
        raise SystemExit(f"release_sync.py: GET {url}: HTTP {e.code}") from None
    except (urllib.error.URLError, OSError, ValueError) as e:
        raise SystemExit(f"release_sync.py: GET {url}: {e}") from None
    return json.loads(body)


class GitHub:
    """The two reads the script makes; the self-test swaps in a fake."""

    def api(self, path: str):
        return _get("https://api.github.com/" + path)

    def raw(self, repo: str, ref: str, path: str) -> str | None:
        """A file at a ref through the contents API (one host, one token), or None."""
        try:
            got = self.api(f"repos/{repo}/contents/{path}?ref={ref}")
        except Gone:
            return None
        if not isinstance(got, dict) or got.get("encoding") != "base64":
            return None
        return base64.b64decode(got.get("content", "")).decode("utf-8", "replace")


def public(projects: dict) -> dict[str, list[str]]:
    """{owner/repo: [project ids]} for every repository projects.json marks public."""
    ids: dict[str, list[str]] = {}
    for p in projects["projects"]:
        ids.setdefault(p["repo"], []).append(p["id"])
    out = {}
    for r in projects["repos"]:
        if r.get("visibility") == "public":
            full = f"{ORG}/{r['repo']}"
            out[full] = ids.get(full, [])
    return out


def releases(gh, repo: str) -> list[dict]:
    """Published releases, newest first (no drafts, no pre-releases)."""
    rel = gh.api(f"repos/{repo}/releases?per_page=100")
    rel = [r for r in rel if not r.get("draft") and not r.get("prerelease")]
    return sorted(rel, key=lambda r: r.get("published_at") or "", reverse=True)


def previous(rels: list[dict], tag: str) -> str | None:
    tags = [r["tag_name"] for r in rels]
    if tag not in tags:
        return None
    i = tags.index(tag)
    return tags[i + 1] if i + 1 < len(tags) else None


def status_paragraph(agents: str | None) -> str | None:
    """AGENTS.md's `**Status: ...**` paragraph (the line projects.json cites), or None."""
    if not agents:
        return None
    m = re.search(r"^\*\*Status:.*?(?=\n\s*\n)", agents, re.M | re.S)
    return " ".join(m.group(0).split()) if m else None


def changelog_section(text: str | None, tag: str) -> list[str]:
    """The CHANGELOG.md section whose heading names the tag's version, capped."""
    if not text:
        return []
    ver = tag.lstrip("v")
    lines = text.splitlines()
    start = next(
        (
            i
            for i, ln in enumerate(lines)
            if ln.startswith("#") and re.search(rf"(?<![\d.]){re.escape(ver)}(?![\d.])", ln)
        ),
        None,
    )
    if start is None:
        return []
    level = len(lines[start]) - len(lines[start].lstrip("#"))
    out = []
    for line in lines[start + 1 :]:
        if line.startswith("#") and len(line) - len(line.lstrip("#")) <= level:
            break
        out.append(line)
    out = [ln for ln in out if ln.strip()]
    if len(out) > MAX_LINES:
        out = out[:MAX_LINES] + [f"… ({len(out) - MAX_LINES} more lines in CHANGELOG.md)"]
    return out


def top_level(gh, repo: str, ref: str) -> set[str]:
    tree = gh.api(f"repos/{repo}/git/trees/{ref}")
    return {t["path"] + ("/" if t["type"] == "tree" else "") for t in tree.get("tree", [])}


def locked(repo: str, path: str = LOCK) -> list[str]:
    names = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            parts = line.split("#", 1)[0].split()
            if len(parts) == 4 and parts[1] == repo:
                names.append(parts[0])
    return names


def title(repo: str, tag: str) -> str:
    return f"[release-sync] {repo.split('/', 1)[1]} {tag}"


def body(
    gh, projects: dict, repo: str, tag: str, prev: str | None = None, lock_path: str = LOCK
) -> str:
    ids = public(projects)[repo]
    rels = releases(gh, repo)
    rel = next((r for r in rels if r["tag_name"] == tag), None)
    if rel is None:
        raise SystemExit(f"release_sync.py: {repo} has no published release {tag}")
    prev = prev or previous(rels, tag)
    name = repo.split("/", 1)[1]
    out = [
        f"A release of `{repo}` reached the site: [{tag}]({rel['html_url']}), "
        f"published {(rel.get('published_at') or '')[:10]}"
        + (
            f", after {prev} ([compare](https://github.com/{repo}/compare/{prev}...{tag}))."
            if prev
            else " (its first release)."
        ),
        "",
        "Part of #120. Written by `tools/release_sync.py`; work it with the `release-sync` "
        "skill (`.claude/skills/release-sync/SKILL.md`).",
        "",
    ]

    out += [
        "## Done without you",
        "",
        '- the Pages rebuild this release triggered: "Cite this project" and References '
        "(`CITATION.cff`, `docs/references.bib`), release and DOI",
        "- `data/hub.json` (status chip, quests, colony level): its `bot/hub-data` PR",
    ]
    for n in locked(repo, lock_path):
        out.append(
            f"- `protocols.lock` entry `{n}`: its `bot/lock` PR to {tag} (the full gate decides it)"
        )
    out.append("")

    out += ["## What changed in the files the site's facts come from", ""]
    if prev:
        cmp = gh.api(f"repos/{repo}/compare/{prev}...{tag}")
        files = {f["filename"]: f for f in cmp.get("files", [])}
        prev_names = {
            f.get("previous_filename"): f
            for f in cmp.get("files", [])
            if f.get("previous_filename")
        }
        rows = [(p, files[p]) for p in WATCHED if p in files]
        # a watched file renamed away is a change to it too
        rows += [
            (p, {**prev_names[p], "status": f"renamed to {prev_names[p]['filename']}"})
            for p in WATCHED
            if p in prev_names and p not in files
        ]
        capped = len(files) >= COMPARE_CAP
        if capped:
            out.append(
                f"**Incomplete:** the compare API lists at most {COMPARE_CAP} files and this "
                "release changed at least that many; check the watched files by hand.\n"
            )
        if rows:
            out += ["| File | Change | Rebuilt by the site |", "|---|---|---|"]
            for p, f in rows:
                out.append(
                    f"| `{p}` | {f['status']}, +{f.get('additions', 0)} −{f.get('deletions', 0)} "
                    f"| {'yes' if p in REBUILT else 'no: check by hand'} |"
                )
        else:
            out.append(
                f"None of {', '.join('`' + p + '`' for p in WATCHED)} "
                + ("is among the files listed." if capped else "changed.")
            )
        out.append(
            f"\n{cmp.get('total_commits', len(cmp.get('commits', [])))} commits, "
            + (
                f"at least {len(files)} files changed (the listing is capped)."
                if capped
                else f"{len(files)} files changed in all."
            )
        )
        before, after = top_level(gh, repo, prev), top_level(gh, repo, tag)
        added, removed = sorted(after - before), sorted(before - after)
        if added or removed:
            out.append(
                "\nTop-level entries: "
                + "; ".join(
                    x
                    for x in (
                        ("added " + ", ".join(f"`{a}`" for a in added)) if added else "",
                        ("removed " + ", ".join(f"`{r}`" for r in removed)) if removed else "",
                    )
                    if x
                )
                + " (the project's package tree)."
            )
        old, new = (status_paragraph(gh.raw(repo, t, "AGENTS.md")) for t in (prev, tag))
        if old != new:
            out += [
                "",
                "AGENTS.md status, before:",
                "",
                f"> {old or '(none)'}",
                "",
                "after:",
                "",
                f"> {new or '(none)'}",
            ]
        else:
            out.append("\nAGENTS.md's status paragraph did not change.")
    else:
        out.append("No previous release to compare with: review every fact.")
    notes = changelog_section(gh.raw(repo, tag, "CHANGELOG.md"), tag)
    if notes:
        out += [
            "",
            f"<details><summary>CHANGELOG.md for {tag}</summary>",
            "",
            *notes,
            "",
            "</details>",
        ]
    out.append("")

    out += ["## Review", ""]
    if ids:
        for pid in ids:
            out += [
                f"In `site/hub/projects.json`, project `{pid}` ({SITE}/projects/{pid}/):",
                "",
                "- [ ] `tagline`, `summary`",
                "- [ ] `facts`",
                "- [ ] `tree` (the package tree)",
                "- [ ] `links`, `sources`",
            ]
    else:
        out.append(
            f"`{repo}` has no project entry in `site/hub/projects.json`; only its `repos` row."
        )
    out += [
        f"- [ ] its `repos` row `{name}`: `role`, `packages`, `licence`",
        "- [ ] its diagrams in `tools/render_hub.py` / `tools/diagrams.py`, if the structure changed",
        f"- [ ] after the redeploy, {SITE}/projects/{ids[0] if ids else name}/ shows {tag}'s citation "
        "and references",
        "",
        "Every fact cites the repository's AGENTS.md (or README) at the tag; never a status, a quest "
        "or a number (golden rule 12). Close with a PR that says `Closes #<this>`, or, when nothing "
        "needs to change, a comment saying what was checked.",
    ]
    return "\n".join(out) + "\n"


def recent(gh, projects: dict, days: int, today: datetime.date | None = None) -> list[str]:
    today = today or datetime.datetime.now(datetime.timezone.utc).date()
    out = []
    for repo in sorted(public(projects), key=str.lower):
        # every release in the window, oldest first: two releases between weekly
        # runs whose events were both missed each get their ticket
        for rel in reversed(releases(gh, repo)):
            if rel.get("published_at"):
                when = datetime.date.fromisoformat(rel["published_at"][:10])
                if (today - when).days <= days:
                    out.append(f"{repo} {rel['tag_name']}")
    return out


class Fake(GitHub):
    def __init__(self):
        self.files = {
            ("v1", "AGENTS.md"): "# A\n\n**Status: core only.** More.\n\nRest.\n",
            ("v2", "AGENTS.md"): "# A\n\n**Status: core and\nns3.** More.\n\nRest.\n",
            (
                "v2",
                "CHANGELOG.md",
            ): "# Changelog\n\n## v2 (2026-11-10)\n\n- feat: ns3\n\n## v1\n\n- old\n",
        }

    def api(self, path):
        if path.startswith("repos/swarm-routing/X/releases"):
            return [
                {
                    "tag_name": "v1",
                    "draft": False,
                    "prerelease": False,
                    "published_at": "2026-10-01T00:00:00Z",
                    "html_url": "u1",
                },
                {
                    "tag_name": "v3-rc",
                    "draft": False,
                    "prerelease": True,
                    "published_at": "2026-11-12T00:00:00Z",
                    "html_url": "u3",
                },
                {
                    "tag_name": "v2",
                    "draft": False,
                    "prerelease": False,
                    "published_at": "2026-11-10T00:00:00Z",
                    "html_url": "u2",
                },
            ]
        if path.startswith("repos/swarm-routing/Y/releases"):
            return []
        if path == "repos/swarm-routing/X/compare/v1...v2":
            return {
                "total_commits": 7,
                "files": [
                    {"filename": "AGENTS.md", "status": "modified", "additions": 2, "deletions": 1},
                    {
                        "filename": "CITATION.cff",
                        "status": "modified",
                        "additions": 1,
                        "deletions": 1,
                    },
                    {"filename": "ns3/a.cc", "status": "added", "additions": 9, "deletions": 0},
                    {
                        "filename": "docs/refs.bib",
                        "previous_filename": "docs/references.bib",
                        "status": "renamed",
                        "additions": 0,
                        "deletions": 0,
                    },
                ],
            }
        if path == "repos/swarm-routing/X/git/trees/v1":
            return {
                "tree": [{"path": "core", "type": "tree"}, {"path": "AGENTS.md", "type": "blob"}]
            }
        if path == "repos/swarm-routing/X/git/trees/v2":
            return {
                "tree": [
                    {"path": "core", "type": "tree"},
                    {"path": "ns3", "type": "tree"},
                    {"path": "AGENTS.md", "type": "blob"},
                ]
            }
        raise AssertionError(f"unexpected GET {path}")

    def raw(self, repo, ref, path):
        return self.files.get((ref, path))


def self_test() -> None:
    import tempfile

    projects = {
        "projects": [{"id": "X", "repo": "swarm-routing/X"}],
        "repos": [
            {"repo": "X", "visibility": "public"},
            {"repo": "Y", "visibility": "public"},
            {"repo": "Z", "visibility": "private"},
        ],
    }
    assert set(public(projects)) == {"swarm-routing/X", "swarm-routing/Y"}, (
        "a private repo is listed"
    )
    gh = Fake()
    with tempfile.TemporaryDirectory() as d:
        lock = os.path.join(d, "lock")
        with open(lock, "w") as f:
            f.write("X swarm-routing/X " + "a" * 40 + " v1\n")
        b = body(gh, projects, "swarm-routing/X", "v2", lock_path=lock)
    assert "after v1 ([compare](https://github.com/swarm-routing/X/compare/v1...v2))" in b, b
    assert "`bot/lock` PR to v2" in b, "the lock entry is not named"
    assert "| `AGENTS.md` | modified, +2 −1 | no: check by hand |" in b, b
    assert "| `CITATION.cff` | modified, +1 −1 | yes |" in b, b
    assert "ns3/a.cc" not in b, "an unwatched file is listed"
    assert "| `docs/references.bib` | renamed to docs/refs.bib, +0 −0 |" in b, (
        "a rename away is missed"
    )
    assert "Incomplete" not in b
    assert "added `ns3/`" in b, "the new top-level directory is missing"
    assert "> **Status: core only.** More." in b and "> **Status: core and ns3.** More." in b, b
    assert "- feat: ns3" in b and "- old" not in b, "the changelog section is wrong"
    assert "project `X` (https://swarm-routing.github.io/projects/X/)" in b, b
    assert "v3-rc" not in b, "a pre-release was used"
    assert title("swarm-routing/X", "v2") == "[release-sync] X v2"
    assert previous(releases(gh, "swarm-routing/X"), "v1") is None
    assert recent(gh, projects, 14, datetime.date(2026, 11, 13)) == ["swarm-routing/X v2"]
    assert recent(gh, projects, 60, datetime.date(2026, 11, 13)) == [
        "swarm-routing/X v1",
        "swarm-routing/X v2",
    ], "an older release in the window is dropped"
    assert recent(gh, projects, 1, datetime.date(2026, 11, 13)) == []
    assert changelog_section("## v2.10.0\n\n- x\n## v2.1.0\n- y\n", "v2.1.0") == ["- y"], (
        "2.1.0 matched 2.10.0"
    )
    assert status_paragraph("no status here\n\n") is None
    # a compare at GitHub's 300-file cap is reported as incomplete, never as "unchanged"
    capped = Fake()
    real = capped.api
    capped.api = lambda path: (
        {
            "total_commits": 9,
            "files": [{"filename": f"f{i}", "status": "added"} for i in range(300)],
        }
        if path == "repos/swarm-routing/X/compare/v1...v2"
        else real(path)
    )
    with tempfile.TemporaryDirectory() as d:
        lock = os.path.join(d, "lock")
        open(lock, "w").close()
        c = body(capped, projects, "swarm-routing/X", "v2", lock_path=lock)
    assert "Incomplete" in c and "is among the files listed" in c and "at least 300 files" in c, c
    print("release_sync.py self-test: ok")


def main(argv: list[str]) -> int:
    if argv == ["--self-test"]:
        self_test()
        return 0
    with open(PROJECTS, encoding="utf-8") as f:
        projects = json.load(f)
    if argv[:1] == ["recent"]:
        days = int(argv[2]) if argv[1:2] == ["--days"] and len(argv) == 3 else 14
        if len(argv) not in (1, 3):
            print(__doc__, file=sys.stderr)
            return 2
        print("\n".join(recent(GitHub(), projects, days)))
        return 0
    if len(argv) in (3, 5) and argv[0] in ("body", "title"):
        repo, tag = argv[1], argv[2]
        prev = argv[4] if len(argv) == 5 and argv[3] == "--prev" else None
        if len(argv) == 5 and (argv[3] != "--prev" or not TAG.match(prev)):
            print(__doc__, file=sys.stderr)
            return 2
        if repo not in public(projects) or not TAG.match(tag):
            print(
                f"release_sync.py: {repo} {tag}: not a public org repository the site lists, "
                "or a bad tag; skipped",
                file=sys.stderr,
            )
            return 3
        print(
            title(repo, tag) if argv[0] == "title" else body(GitHub(), projects, repo, tag, prev),
            end="\n" if argv[0] == "title" else "",
        )
        return 0
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
