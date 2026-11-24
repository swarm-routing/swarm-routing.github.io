#!/usr/bin/env python3
# Copyright (c) 2026 Daniel Joppi (https://github.com/swarm-routing)
# SPDX-License-Identifier: MIT OR GPL-2.0-only
"""Run every tools/ script's --self-test, for coverage.py.

reusable-python-ci.yml runs each test script as `coverage run <script>`,
with no arguments; the tools here test themselves with `--self-test`. This
runs each of them in a child process, which coverage.py measures too
(`patch = subprocess`), so Codecov sees tools/ as the tests exercise it
(swarm-routing/.github#635). pages.yml's build job runs the same self-tests
directly. Exits non-zero on the first failure.
"""

import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
TOOLS = [
    "lock.py",
    "check_hub.py",
    "stamp_build.py",
    "hub_data.py",
    "images_data.py",
    "release_sync.py",
    "render_hub.py",
    "check_tokens.py",
]


def main():
    for name in TOOLS:
        cmd = [sys.executable, os.path.join(HERE, name), "--self-test"]
        rc = subprocess.run(cmd, cwd=ROOT, check=False).returncode
        if rc:
            print(f"FAIL {name} --self-test (exit {rc})")
            return 1
        print(f"ok   {name} --self-test")
    return 0


if __name__ == "__main__":
    sys.exit(main())
