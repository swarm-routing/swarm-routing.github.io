# AGENTS.md — guide for AI coding agents

Operational guide for LLM agents working in `swarm-routing/swarm-routing.github.io`. Read this
before changing anything. Org-wide conventions:
[`swarm-routing/.github` CONTRIBUTING.md](https://github.com/swarm-routing/.github/blob/main/CONTRIBUTING.md). Shape and rules mirror
[AntHocNet's AGENTS.md](https://github.com/danieljoppi/AntHocNet/blob/main/AGENTS.md), the source repository.

## What this repo is

**Status: serving from `main` (#8, #9, #10; ADR-0001 accepted, #7).** The org's only Pages site, "Colony Arena": the hub at `/` (a gamified colony map of every org project, the public repositories' package structure, the roadmap as a quest log, the org architecture as diagrams), a space per project at `/arena/<id>/` (what it does, UML sequence/package/class diagrams, its package structure, its quests), and AntHocNet's game, docs and API at `/AntHocNet/{,docs/,api/}`, built from `swarm-routing/AntHocNet` at the commit pinned in `protocols.lock`. AntHocNet still has its own `web/` until AntHocNet#850.

```
protocols.lock        protocol -> repo, 40-char commit, tag (ADR-0001); bump by PR only
site/anthocnet/       AntHocNet's web/ (adapter src, game, shell, tests), moved as-is; overlaid onto the pinned checkout as its web/
site/hub/             projects.json (the facts per project and the public repos), arena.css, arena.js
tools/build-site.sh   the one build: fetch the pin, overlay, AntHocNet's web/build-pages.sh, render the hub, crawl
tools/render_hub.py   hub + /arena/<id>/ pages; tools/diagrams.py: the SVG diagram library (UML package, sequence, class; hexagon; pipeline; org graph)
tools/lock.py         reads/validates protocols.lock; tools/check_hub.py: crawls the hub pages
test/hub-smoke.mjs    the hub and every project space in Chromium, day and night, axe
.claude/skills/learn-site/  the procedure for the game: parity, smokes, README figures (moved from AntHocNet, #850)
docs/adr/             ADR-0001: how the site consumes protocol code
data/                 (planned, #12) leaderboard data pulled from swarm-routing/benchmarks (never typed by hand)
```

## Build & verify

CI is `.github/workflows/pages.yml` (every PR: build, parity, AntHocNet's web
tests, both crawls, both browser smokes with axe; `main` also deploys and runs
the live smoke) and `licence.yml`. Locally (needs emsdk 4.0.10 activated,
AntHocNet's pinned mkdocs-material, doxygen, Node 22):

```bash
tools/build-site.sh build/site                 # fetches AntHocNet at the pin; AHN_SRC=<checkout> to reuse one
SKIP_ANTHOCNET=1 tools/build-site.sh build/hub # hub + project spaces only, python3 alone
python3 tools/lock.py --self-test && python3 tools/check_hub.py --self-test
(cd build/src/AntHocNet && web/test/parity.sh 120 "1 2 7 42")   # native vs WASM, byte-identical
# browsers: the pinned playwright-core + axe-core resolve from the working directory, as in CI
repo=$PWD; pw=$(mktemp -d)
cp site/anthocnet/test/browser-tools/package.json site/anthocnet/test/browser-tools/package-lock.json "$pw/"
(cd "$pw" && npm ci --no-audit --no-fund && npx --no-install playwright-core install chromium \
  && node "$repo/site/anthocnet/test/smoke.mjs" "$repo/build/site/AntHocNet" \
  && node "$repo/test/hub-smoke.mjs" "$repo/build/site")
python3 -I ../.github/tools/checks/check-headers.py --dual tools/ .
```

Facts on the hub change in `site/hub/projects.json` (cite the repository's
AGENTS.md or the ROADMAP; never a benchmark number, rule 12; only public
repositories, `render_hub.py` refuses others). A change to the game is a
change to `site/anthocnet/`; a newer AntHocNet core, docs or API is a
`protocols.lock` bump PR.

## Golden rules (invariants — do not break)

Org-wide (1–9), then this repo's own.

1. **Licensing per directory, as AntHocNet** ([`LICENSING.md`](LICENSING.md);
   AntHocNet [LICENSING.md](https://github.com/danieljoppi/AntHocNet/blob/main/LICENSING.md),
   [ADR-0028](https://github.com/danieljoppi/AntHocNet/blob/main/docs/adr/0028-core-is-dual-licensed.md)). A
   simulator-free `core/` and the standalone tooling are `MIT OR GPL-2.0-only`;
   ns-3 modules, the site, docs and data are `GPL-2.0-only`. Every original
   `.h`/`.hpp`/`.cc`/`.cpp`/`.py`/`.sh` starts with
   `// Copyright (c) 2026 Daniel Joppi (https://github.com/swarm-routing)` +
   `// SPDX-License-Identifier: <MIT OR GPL-2.0-only | GPL-2.0-only>` (`#`
   comments where needed), matching its directory in `LICENSING.md`. CI
   (`reusable-licence-check.yml`) checks it. A new directory gets its row in
   `LICENSING.md` in the same PR.
2. **The licence boundary only goes one way.** GPL code may use the dual
   parts; dual code never pulls GPL-only code in: a `core/` file includes only
   the C++ standard library and other `core/` files (CI checks it), and a dual
   script imports no GPL-only code. Code coming from AntHocNet keeps its
   licence: its `core/`/`tools/` (dual) may land in dual or GPL paths here; its
   `ns3/` modules and `web/` (GPL-2.0-only) only in GPL paths. Third-party code
   (AntHocNet's vendored `aomdv`/`gpsr`, IITP RAS) lands only in GPL paths with
   its provenance recorded. Write clean implementations against public ns-3
   interfaces rather than copying ns-3's `src/aodv`/`src/olsr`.
3. **Wire formats are POD + versioned.** Control headers are
   simulator-independent POD structs with bounds-checked little-endian
   readers/writers, a leading version byte, and deterministic roundtrip + fuzz
   tests. Changing a field or its units bumps the version byte.
4. **No contrib module named `core`** (collides with ns-3's `src/core`). The
   shared module is `swarm-core` (`#include "ns3/swarm-core-module.h"`).
5. **Determinism.** A fixed `--seed=<N>` gives byte-identical output. All
   randomness through the simulator's seeded streams or an injected RNG port;
   never libc `rand()`, wall-clock time, or unordered-container iteration order
   in anything that reaches an output.
6. **Comparisons are paired.** Per-seed deltas across >= 20 seeds, emitting the
   canonical `##CONFIG##`, `##RUN##`, `##BENCH##`, `##DIAG##` lines. A
   comparator arm (a protocol we did not design) counts only after its three
   gates: a fidelity sheet from its paper, the per-PR delivery smoke, and an
   anchor reproducing the paper's own trend.
7. **Keep bounded structures bounded** (visited paths, dedup histories, queues
   carry a configured cap).
8. **CI hygiene.** Actions pinned by full commit SHA with a `# vX.Y.Z` comment;
   buildx caches scoped per profile; transient artifacts `retention-days` <= 7.
9. **Nothing shipped depends on `.claude/`.** Skills hold procedures; scripts
   that anything shipped needs live in `tools/` (AntHocNet ADR-0014).
10. **No routing logic in the site.** A simulation in the browser runs a protocol's own `core/` compiled to WebAssembly; the site only renders (AntHocNet ADR-0021).
11. **Browser simulations stay deterministic**: randomness drawn into named locals, no libm trig in mobility, `-ffp-contract=off`, native-vs-WASM traces byte-identical (AntHocNet golden rule 9).
12. **Leaderboard numbers come from `benchmarks` data**, regenerated by a script, never edited by hand.
13. **The site is GPL-2.0-only, like AntHocNet's `web/`**, so `web/` code may be reused as-is; only `tools/` is dual.

## Conventions

- Issues follow the org taxonomy ([CONTRIBUTING.md](https://github.com/swarm-routing/.github/blob/main/CONTRIBUTING.md#issues), from
  [AntHocNet ADR-0013](https://github.com/danieljoppi/AntHocNet/blob/main/docs/adr/0013-track-bugs-and-findings-as-issues.md)): one type label
  (`bug`/`enhancement`/`chore`/`documentation`/`verification`, plus `epic` for
  umbrellas), area label(s) (`protocol`/`adapter`/`ns3`/`benchmark`/
  `observability`/`packaging`/`learn-site`/`literature`), one `model:*`
  recommendation, one `priority:P1|P2|P3` on non-epic issues, a
  `release:vX.Y.Z` label only when a roadmap gates the issue. Labels come from
  `labels.json` via the `sync-labels` workflow.
- Issue bodies: **Context** (evidence, numbers, links) · **Scope** ·
  **Acceptance criteria** (checkboxes) · **Depends on** (cross-repo form
  `swarm-routing/<repo>#N`) · **References**. Children of an epic say "Part of
  #N" and are linked as sub-issues. Comments you post end with the Claude Code
  footer.
- Issues migrated from AntHocNet carry `migrated` and start with *Migrated from
  `danieljoppi/AntHocNet#N`*.
- Make minimal, reviewable changes; update the relevant doc/ADR when you change
  a documented decision.

## Git workflow

- Branch from `main` (`claude/<short-topic>`), one focused change per PR.
- **Always open a PR to `main`** once the branch is pushed — every change is
  tracked through one.
- **PRs are squash-merged** (the only merge method enabled). The PR title is
  the commit on `main`, so it is a lowercase Conventional Commit
  (`feat:`/`fix:`/`docs:`/`chore:`/`ci:`…, optional scope).
- Push with `git push -u origin <branch>`; merge when CI is green.

## Where to look

| You want to… | Go to |
|--------------|-------|
| The game and its adapter | `site/anthocnet/` (AntHocNet's `web/`, README there), AntHocNet `docs/learn-campaign.md`, the `learn-site` skill (`.claude/skills/learn-site/`) |
| How the site consumes protocol code | `docs/adr/0001-the-site-builds-protocols-from-pinned-commits.md`, `protocols.lock`, `tools/build-site.sh` |
| The hub's facts, map and diagrams | `site/hub/projects.json`, `tools/render_hub.py`, `tools/diagrams.py` |
| The plan: site only here, cores built from pinned protocol commits | epic #3 (decision 2026-11-03); children #7 ADR, #8 scaffold, #9 game move, #10 docs/API, #11 cutover, #12 leaderboard, #13 second protocol; AntHocNet's half swarm-routing/AntHocNet#850 |
| Learn-site issues still in AntHocNet (migrate with #9) | swarm-routing/AntHocNet #562, #634, #602, #590, #751, #846 |
| The org's invariants, labels, issue shape | [`swarm-routing/.github` CONTRIBUTING.md](https://github.com/swarm-routing/.github/blob/main/CONTRIBUTING.md) |
| The reference implementation and its history | [`danieljoppi/AntHocNet`](https://github.com/danieljoppi/AntHocNet) (`AGENTS.md`, `CONTEXT.md`, `docs/adr/`) |
| Pick up open work | this repo's issues — highest open `priority:P*` first; newest open `handoff` issue for work in flight |
