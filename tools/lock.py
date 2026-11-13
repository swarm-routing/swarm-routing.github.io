#!/usr/bin/env python3
# Copyright (c) 2026 Daniel Joppi (https://github.com/swarm-routing)
# SPDX-License-Identifier: MIT OR GPL-2.0-only
"""Read protocols.lock (ADR-0001): the protocol commits the site builds from.

Usage:  python3 tools/lock.py <name> repo|commit|tag   one field
        python3 tools/lock.py --check                  validate the file
        python3 tools/lock.py bump <name> [--to <tag>]  move <name> to a release (#121)
        python3 tools/lock.py bump --all               move every entry to its latest release
        python3 tools/lock.py --self-test

bump resolves the tag to its commit with `git ls-remote` (the peeled commit of
an annotated tag) and rewrites that entry's line only; without --to it takes
the repository's latest release (not a draft, not a pre-release) from the
GitHub REST API (a token in GH_TOKEN or GITHUB_TOKEN is sent when set). An
entry already at the tag is left alone (with --all, also one whose latest
release is behind its pin: reported as skipped), and an entry is never moved backwards:
the new commit must contain the pinned one (the REST API's compare says
`ahead`), else bump refuses and writes nothing (a protocol's latest release
can be older than a pin taken from its main, as AntHocNet's v2.6.1 is). It prints one line per entry, and
`changed: <name> <tag>` for each one it moved. release-sync.yml runs it and
opens the bot/lock PR; by hand it is the same command, then a PR.
Stdlib only.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request

LOCK = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "protocols.lock")
FIELDS = ("repo", "commit", "tag")
NAME = re.compile(r"^[A-Za-z][A-Za-z0-9._-]*$")
REPO = re.compile(r"^[A-Za-z0-9-]+/[A-Za-z0-9._-]+$")
SHA = re.compile(r"^[0-9a-f]{40}$")
TAG = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]*$")


def read(path: str = LOCK) -> dict[str, dict[str, str]]:
    """Every entry, keyed by name; raises ValueError on a malformed line."""
    out: dict[str, dict[str, str]] = {}
    with open(path, encoding="utf-8") as f:
        for n, line in enumerate(f, 1):
            line = line.split("#", 1)[0].strip()
            if not line:
                continue
            parts = line.split()
            if len(parts) != 4:
                raise ValueError(f"line {n}: expected 4 fields, got {len(parts)}")
            name, repo, commit, tag = parts
            if not NAME.match(name):
                raise ValueError(f"line {n}: bad name {name!r}")
            if not REPO.match(repo):
                raise ValueError(f"line {n}: bad repo {repo!r}")
            if not SHA.match(commit):
                raise ValueError(f"line {n}: commit must be a full 40-char SHA, got {commit!r}")
            if name in out:
                raise ValueError(f"line {n}: duplicate name {name!r}")
            out[name] = {"repo": repo, "commit": commit, "tag": tag}
    return out


def ls_remote(repo: str, tag: str) -> str:
    """The commit a tag points to (peeled when annotated); ValueError if absent."""
    if not REPO.match(repo) or not TAG.match(tag):
        raise ValueError(f"bad repo or tag: {repo!r} {tag!r}")
    ref = f"refs/tags/{tag}"
    out = subprocess.run(["git", "ls-remote", f"https://github.com/{repo}.git", ref, ref + "^{}"],
                         capture_output=True, text=True, timeout=60, check=False)
    if out.returncode != 0:
        raise ValueError(f"git ls-remote {repo} {tag}: {out.stderr.strip()}")
    refs = dict(reversed(line.split("\t", 1)) for line in out.stdout.splitlines() if "\t" in line)
    commit = refs.get(ref + "^{}") or refs.get(ref)
    if not commit or not SHA.match(commit):
        raise ValueError(f"{repo} has no tag {tag!r}")
    return commit


def latest_release(repo: str) -> str:
    """The tag of the repository's latest release (GitHub's: no draft, no pre-release)."""
    tag = api_json(f"repos/{repo}/releases/latest").get("tag_name", "")
    if not TAG.match(tag):
        raise ValueError(f"{repo}: latest release has a bad tag {tag!r}")
    return tag


def api_json(path: str) -> dict:
    req = urllib.request.Request("https://api.github.com/" + path, headers={
        "Accept": "application/vnd.github+json", "User-Agent": "lock-bump"})
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise ValueError(f"GET {path}: HTTP {e.code}") from None
    except (urllib.error.URLError, OSError, ValueError) as e:
        raise ValueError(f"GET {path}: {e}") from None


def forward(repo: str, old: str, new: str) -> bool:
    """True when commit `new` contains commit `old` (the move goes forward)."""
    return api_json(f"repos/{repo}/compare/{old}...{new}").get("status") in ("ahead", "identical")


def bump(names: list[str], to: str | None, path: str = LOCK,
         resolve=ls_remote, latest=latest_release, ahead=forward, strict: bool = True) -> list[str]:
    """Move each named entry to `to` (else its latest release); return the names moved.

    Rewrites only the entries' own lines, so comments and order stay. Raises
    ValueError before writing anything when a name, tag or commit is wrong.
    """
    entries = read(path)
    moves: dict[str, tuple[str, str]] = {}
    for name in names:
        if name not in entries:
            raise ValueError(f"no entry {name!r}")
        e = entries[name]
        tag = to or latest(e["repo"])
        if not TAG.match(tag):
            raise ValueError(f"bad tag {tag!r}")
        commit = resolve(e["repo"], tag)
        if (commit, tag) == (e["commit"], e["tag"]):
            print(f"{name}: already at {tag} ({commit[:12]})")
            continue
        if not ahead(e["repo"], e["commit"], commit):
            if not strict:  # --all: report it and move the others
                print(f"{name}: skipped, {tag} ({commit[:12]}) is behind the pinned {e['commit'][:12]}")
                continue
            raise ValueError(f"{name}: {tag} ({commit[:12]}) does not contain the pinned "
                             f"{e['commit'][:12]}; a bump never moves backwards")
        print(f"{name}: {e['tag']} {e['commit'][:12]} -> {tag} {commit[:12]}")
        moves[name] = (commit, tag)
    if moves:
        with open(path, encoding="utf-8") as f:
            lines = f.read().splitlines(keepends=True)
        for i, line in enumerate(lines):
            parts = line.split("#", 1)[0].split()
            if len(parts) == 4 and parts[0] in moves:
                commit, tag = moves[parts[0]]
                tail = line[len(line.rstrip("\n")):]
                comment = line.rstrip("\n").split("#", 1)[1] if "#" in line else None
                lines[i] = " ".join((parts[0], parts[1], commit, tag)) + (f"  #{comment}" if comment else "") + tail
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write("".join(lines))
        read(tmp)  # still valid before it replaces the file
        os.replace(tmp, path)
    return sorted(moves)


def self_test() -> None:
    good = "# c\nA o/r " + "a" * 40 + " v1\n\nB o/s " + "b" * 40 + " -  # trailing\n"
    bad = ["A o/r abc v1\n", "A o/r " + "a" * 40 + "\n", "A bad " + "a" * 40 + " -\n",
           ("A o/r " + "a" * 40 + " -\n") * 2]
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "lock")
        with open(p, "w") as f:
            f.write(good)
        got = read(p)
        assert got["B"] == {"repo": "o/s", "commit": "b" * 40, "tag": "-"}, got
        for text in bad:
            with open(p, "w") as f:
                f.write(text)
            try:
                read(p)
            except ValueError:
                continue
            raise AssertionError(f"accepted {text!r}")
        # bump: a fake remote and a fake release list
        tags = {("o/r", "v2"): "c" * 40, ("o/s", "v9"): "d" * 40}
        resolve = lambda repo, tag: tags[(repo, tag)] if (repo, tag) in tags else (_ for _ in ()).throw(ValueError("no tag"))  # noqa: E731
        latest = lambda repo: {"o/r": "v2", "o/s": "v9"}[repo]  # noqa: E731
        behind = {"e" * 40}  # a tag whose commit is older than the pin
        tags[("o/r", "v0")] = "e" * 40
        ahead = lambda repo, old, new: new not in behind  # noqa: E731
        with open(p, "w") as f:
            f.write(good)
        assert bump(["A"], "v2", p, resolve, latest, ahead) == ["A"]
        got = read(p)
        assert got["A"] == {"repo": "o/r", "commit": "c" * 40, "tag": "v2"}, got
        assert got["B"]["commit"] == "b" * 40, "an entry not named moved"
        text = open(p).read()
        assert text.startswith("# c\n") and "\n\nB o/s" in text and "# trailing" in text, text
        assert bump(["A"], "v2", p, resolve, latest, ahead) == [], "an entry at its tag moved again"
        assert bump(sorted(read(p)), None, p, resolve, latest, ahead) == ["B"]  # --all: latest release
        assert read(p)["B"] == {"repo": "o/s", "commit": "d" * 40, "tag": "v9"}
        tags[("o/s", "v9")] = "e" * 40  # B's latest release now behind its pin: --all skips it
        assert bump(sorted(read(p)), None, p, resolve, latest, ahead, strict=False) == []
        tags[("o/s", "v9")] = "d" * 40
        before = open(p).read()
        for names, to in ((["Z"], "v2"), (["A"], "v3"), (["A"], "bad tag"), (["A"], "v0")):
            try:
                bump(names, to, p, resolve, latest, ahead)
            except ValueError:
                assert open(p).read() == before, "a failed bump wrote the file"
                continue
            raise AssertionError(f"bump {names} {to} accepted")
    read()  # the real file parses
    print("lock.py self-test: ok")


def main(argv: list[str]) -> int:
    if argv == ["--self-test"]:
        self_test()
        return 0
    if argv == ["--check"]:
        print(f"protocols.lock: {len(read())} entries ok")
        return 0
    if argv[:1] == ["bump"]:
        rest = argv[1:]
        to = None
        if len(rest) >= 2 and rest[-2] == "--to":
            to, rest = rest[-1], rest[:-2]
        strict = True
        if rest == ["--all"] and to is None:
            names, strict = sorted(read()), False
        elif len(rest) == 1 and not rest[0].startswith("-"):
            names = rest
        else:
            print(__doc__, file=sys.stderr)
            return 2
        try:
            moved = bump(names, to, strict=strict)
        except ValueError as e:
            print(f"lock.py bump: {e}; nothing written", file=sys.stderr)
            return 1
        for name in moved:
            e = read()[name]
            print(f"changed: {name} {e['tag']}")
        return 0
    if len(argv) == 2 and argv[1] in FIELDS:
        entries = read()
        if argv[0] not in entries:
            print(f"lock.py: no entry {argv[0]!r}", file=sys.stderr)
            return 1
        print(entries[argv[0]][argv[1]])
        return 0
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
