# 0001. The site builds each protocol from its own repository at a pinned commit

- **Status:** accepted (maintainer, 2026-11-08, #7)
- **Date:** 2026-11-08
- **Issue:** #7 (epic #3; implemented by #8, #9, #10)

## Context

The maintainer decided on 2026-11-03 (#3) that the org's only Pages site is
this repository and that every simulation runs a protocol's own `core/`, built
from that protocol's repository at a pinned commit, with nothing vendored.
AntHocNet's `web/` coupled the two in one tree: `web/CMakeLists.txt` compiles
`../core` to WebAssembly, `web/test/parity.sh` diffs native vs WASM decision
traces on every AntHocNet PR, `web/build-pages.sh` assembles the game, the
mkdocs docs (whose hooks import `web/shell/inject.py`) and the Doxygen API, and
`tools/checks/check-site-links.py` requires a nest chamber for every public
core class.

On 2026-11-08 at about 00:06 UTC AntHocNet's Pages was disabled before this
site could serve `/AntHocNet/` (#15): the game, docs and API have answered 404
since. Whatever is decided has to bring those paths back without moving
AntHocNet's docs or core.

## Decision

1. **Pinned refs.** `protocols.lock` at the repo root has one line per
   protocol: `<name> <owner/repo> <40-char commit> <tag or ->`. `<name>` is
   its site path (`/<name>/`). It changes only by PR, and a bump PR runs the
   full gate below. `tools/lock.py` reads and validates it (no short SHAs,
   no duplicates). A bot that opens bump PRs on each protocol release is
   optional and not built yet.
2. **Fetch and build: overlay, not copy.** CI checks the protocol repository
   out at the pinned commit (`actions/checkout` with `ref:` the SHA; locally
   `git fetch --depth 1` of the SHA), replaces its `web/` with this
   repository's `site/<protocol>/`, and runs that tree's own build
   (`web/build-pages.sh`). The protocol's `core/`, `docs/`, `api/`,
   `results/` and pinned toolchain (emsdk via its
   `.github/actions/setup-emsdk`, mkdocs-material via its `requirements/`)
   come from the pinned commit; only the browser adapter and the site come
   from here. `tools/build-site.sh` is the one definition, used by CI and
   locally; it refuses a checkout that is not at the pinned commit.
3. **Browser binding ABI.** The binding (`bindings.cpp`, the JS ABI) is
   adapter code, GPL-2.0-only, and lives here with the rest of the adapter
   (`site/anthocnet/src/`), next to the JavaScript that calls it. A protocol
   exposes only its public `core/` headers; the binding is the adapter's
   contract, versioned with the site.
4. **The shared browser simulator** (world, mobility with `detSin`/`detCos`,
   radio, scenarios: today `site/anthocnet/src/sim.cpp`, `scenarios.cpp`)
   stays inside AntHocNet's adapter for now and is extracted into a
   protocol-neutral `site/sim/` when the second protocol needs it (#13), the
   same rule swarm-core applies to shared code: promote on the second user.
5. **Parity across repositories.** `parity.sh` and the native trace runner
   move with the adapter (`site/anthocnet/test/`). This repository's
   `pages.yml` runs parity on every PR against the pinned core, so a bump
   cannot ship a WASM break. Golden rule 9 must also hold on every AntHocNet
   `core/` PR, before a bump: AntHocNet's CI keeps its parity gate by checking
   this repository out at `main` and running the same overlay against the
   PR's `core/`. Implemented by AntHocNet#852 (2026-11-08): AntHocNet's
   `tools/checks/fetch-site-web.sh` copies this repository's `site/anthocnet/`
   at `main` into a git-ignored `web/`, and its `ci-web.yml` parity and Pages
   jobs run against that.
6. **Cross-repo site checks.** The core-class → nest-chamber rule of
   `check-site-links.py` runs here, at bump time, inside the overlay (it reads
   the pinned `core/` and this `site/anthocnet/site/js/nest-data.js`); in
   AntHocNet it becomes warn-only once `web/` leaves (AntHocNet#850).
7. **URL layout.**
   - `/` — the Colony Arena hub (map, public repositories, quest log, how it is built);
   - `/arena/<id>/` — each org project's space (what it does, diagrams,
     package structure, quests), generated from `site/hub/projects.json`;
   - `/<Protocol>/` — a protocol's own published artefact when it has one:
     `/AntHocNet/` (game), `/AntHocNet/docs/`, `/AntHocNet/api/`; the next
     protocol in the browser takes `/<Repo>/` the same way, so its URL is
     the one GitHub would give its project Pages;
   - `/404.html` — AntHocNet's 404 (root-absolute `/AntHocNet/` links, its
     top bar), because GitHub serves one 404 for the whole org site and
     AntHocNet's live smoke checks it; revisit when a second protocol ships.
   AntHocNet's service worker and `manifest.webmanifest` stay scoped to
   `/AntHocNet/` (relative paths, unchanged), and the old-URL redirects
   (`site-redirects.sh`, #558) keep working under that base.
   Only public repositories appear anywhere on the site.
8. **Licensing.** The site is GPL-2.0-only (golden rule 13), so AntHocNet's
   `web/` moves here as-is. A dual-licensed `core/` built into a GPL artefact
   is fine (rule 2): the artefact is GPL-2.0 and each core file keeps its
   notice. `tools/` here is `MIT OR GPL-2.0-only` and imports no GPL code.

## Consequences

- `/AntHocNet/{,docs/,api/}` come back from this repository as soon as its
  Pages source is GitHub Actions and `pages.yml` deploys `main`, with no change
  to AntHocNet (its docs, API and core are read at the pin).
- A change to AntHocNet's docs or core reaches the site only through a lock
  bump PR, which runs parity, AntHocNet's web tests, both crawls and both
  browser smokes. The site can lag AntHocNet's `main` by design.
- The overlay depends on AntHocNet's tree keeping the paths `web/` expects
  (`core/`, `docs/`, `mkdocs.yml`, `api/Doxyfile`, `results/replay/`,
  `tools/checks/check-site.py`). A pinned commit that breaks one fails the
  bump PR, not the live site.
- One copy of `web/` exists: this repository's `site/anthocnet/`, the one
  served. AntHocNet#852 removed AntHocNet's on 2026-11-08 and AntHocNet's CI
  fetches it from here. Changes to the game land here; the learn-site issues
  migrated here with it (#9: #21–#24).
