#!/usr/bin/env python3
# Copyright (c) 2026 Daniel Joppi (https://github.com/swarm-routing)
# SPDX-License-Identifier: MIT OR GPL-2.0-only
"""Read protocols.lock (ADR-0001): the protocol commits the site builds from.

Usage:  python3 tools/lock.py <name> repo|commit|tag   one field
        python3 tools/lock.py --check                  validate the file
        python3 tools/lock.py --self-test
Stdlib only.
"""
from __future__ import annotations

import os
import re
import sys
import tempfile

LOCK = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "protocols.lock")
FIELDS = ("repo", "commit", "tag")
NAME = re.compile(r"^[A-Za-z][A-Za-z0-9._-]*$")
REPO = re.compile(r"^[A-Za-z0-9-]+/[A-Za-z0-9._-]+$")
SHA = re.compile(r"^[0-9a-f]{40}$")


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
    read()  # the real file parses
    print("lock.py self-test: ok")


def main(argv: list[str]) -> int:
    if argv == ["--self-test"]:
        self_test()
        return 0
    if argv == ["--check"]:
        print(f"protocols.lock: {len(read())} entries ok")
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
