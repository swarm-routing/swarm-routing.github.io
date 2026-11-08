#!/usr/bin/env bash
# Copyright (c) 2026 Daniel Joppi (https://github.com/swarm-routing)
# SPDX-License-Identifier: MIT OR GPL-2.0-only
# Assemble the whole org site (ADR-0001) into one Pages artefact:
#   /                  the Colony Arena hub          (site/hub, tools/render_hub.py)
#   /<Project>/        a space per org project       (site/hub/projects.json)
#   /AntHocNet/        AntHocNet's game, /docs/, /api/ (site/anthocnet on the pinned commit)
# AntHocNet's core/, docs/ and API headers come from swarm-routing/AntHocNet at
# the commit in protocols.lock; this repo's site/anthocnet/ is laid over that
# checkout as its web/ and the checkout's own web/build-pages.sh runs. Nothing
# of AntHocNet's is vendored here.
#
# Usage: tools/build-site.sh [out-dir]            (default build/site)
# Env:   AHN_SRC=<dir>  use this AntHocNet checkout instead of fetching the pin
#                       (it must be at the pinned commit; its web/ is replaced)
#        SKIP_ANTHOCNET=1  hub and project spaces only (no emsdk/mkdocs/doxygen)
# Needs: git, python3; for AntHocNet: an activated emsdk, mkdocs-material
#        (AntHocNet requirements/mkdocs-material.txt), doxygen.
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT=$PWD
OUT=$(mkdir -p "${1:-build/site}" && cd "${1:-build/site}" && pwd)
find "$OUT" -mindepth 1 -delete

if [ "${SKIP_ANTHOCNET:-0}" != 1 ]; then
  repo=$(python3 tools/lock.py AntHocNet repo)
  sha=$(python3 tools/lock.py AntHocNet commit)
  src=${AHN_SRC:-$ROOT/build/src/AntHocNet}
  if [ -z "${AHN_SRC:-}" ]; then
    mkdir -p "$src"
    git -C "$src" init -q
    git -C "$src" fetch -q --depth 1 "https://github.com/$repo.git" "$sha"
    git -C "$src" checkout -q --force FETCH_HEAD
  fi
  got=$(git -C "$src" rev-parse HEAD)
  [ "$got" = "$sha" ] || { echo "AntHocNet checkout is at $got, protocols.lock pins $sha" >&2; exit 1; }
  rm -rf "$src/web"
  cp -r site/anthocnet "$src/web"
  (cd "$src" && web/build-pages.sh "$OUT/AntHocNet")
  python3 "$src/tools/checks/check-site.py" "$OUT/AntHocNet"
  # The org site has one 404 page for every path; AntHocNet's carries its top
  # bar and root-absolute /AntHocNet/ links (its live smoke checks both).
  cp "$OUT/AntHocNet/404.html" "$OUT/404.html"
fi

python3 tools/render_hub.py "$OUT"
python3 tools/check_hub.py "$OUT"
touch "$OUT/.nojekyll"
echo "site assembled in $OUT ($(du -sh "$OUT" | cut -f1))"
