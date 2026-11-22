# AGENTS.md — guide for AI coding agents

Operational guide for LLM agents working in `swarm-routing/swarm-routing.github.io`. Read this
before changing anything. Org-wide conventions:
[`swarm-routing/.github` CONTRIBUTING.md](https://github.com/swarm-routing/.github/blob/main/CONTRIBUTING.md). Shape and rules mirror
[AntHocNet's AGENTS.md](https://github.com/swarm-routing/AntHocNet/blob/main/AGENTS.md), the source repository.

## What this repo is

**Status: serving from `main` (#8, #9, #10; ADR-0001 accepted, #7).** The org's only Pages site, "Colony Arena": the hub at `/` (a gamified colony map of every org project, the public repositories' package structure, the epics in progress as a quest log, the org architecture as diagrams), a page per project at `/projects/<id>/` (what it does, UML sequence/package/class diagrams, its package structure, its quests, how to cite it, its references with DOI links; `/projects/` lists them, `/references/` lists every work once, and `/arena/<id>/`, the address until #102, redirects), a `/pipeline/` page (the browser runs AntHocNet's original C++ `core/` compiled to WebAssembly, the parity proof, and the package-and-deploy pipeline as diagrams), and AntHocNet's game, docs and API at `/AntHocNet/{,docs/,api/}`, built from `swarm-routing/AntHocNet` at the commit pinned in `protocols.lock`. AntHocNet's CI fetches `site/anthocnet/` as a git-ignored `web/` (`tools/checks/fetch-site-web.sh`, AntHocNet#850), so a `core/` PR there still runs parity against this adapter.

```
protocols.lock        protocol -> repo, 40-char commit, tag (ADR-0001); bump by PR only (release-sync.yml's bot/lock PR, or tools/lock.py bump)
site/anthocnet/       AntHocNet's web/ (adapter src, game, shell, tests), moved as-is; overlaid onto the pinned checkout as its web/
site/hub/             projects.json (the hand-kept facts per project and the public repos: no status, no quests), arena.css, arena.js
site/anthocnet/shell/ the site shell, for every page of the site (#97): tokens.css (the one token file: every colour, radius, font and shadow, day and night), topbar.html (the one top bar; inject.py fills it for the game, docs and API, render_hub.py for the hub), shell.css, theme.js (the one day/night choice, `arena-theme`), shell.js
tools/build-site.sh   the one build: fetch the pin, overlay, AntHocNet's web/build-pages.sh, render the hub, crawl
tools/render_hub.py   hub + /projects/<id>/ + /references/ + /pipeline/ pages and the /arena/ redirects; tools/diagrams.py: the SVG diagram library (UML package, sequence, class; hexagon; pipeline; org graph)
tools/bib.py          the docs/references.bib reader, vendored from swarm-routing/.github tools/fidelity/bib.py (commit in its header)
docs/references.bib   the works this site relies on (the AntHocNet paper its game implements, AntHocNet's release)
tools/lock.py         reads/validates protocols.lock, `bump` moves an entry to a release (never backwards); tools/check_hub.py: crawls the hub pages and compares every page's top bar
tools/check_tokens.py fails on a colour literal, a radius or a font stack outside shell/tokens.css, and on night blocks that differ (#97)
tools/stamp_build.py  the build marker (#28): stamps every page with the site commit; the live smoke requires it
test/hub-smoke.mjs    the hub, /pipeline/ and every project space in Chromium, day and night, axe
.claude/skills/learn-site/  the procedure for the game: parity, smokes, README figures (moved from AntHocNet, #850)
.claude/skills/release-sync/  works a `[release-sync] <repo> <tag>` issue: the hand-kept facts brought up to a release (#122)
docs/adr/             ADR-0001: how the site consumes protocol code
docs/pipeline.md      the compile (core/ -> WebAssembly), the parity proof, package and deploy, step by step
data/                 hub.json: each public repository's epics, sub-issue counts and latest release, written by tools/hub_data.py (#104);
                      (planned, #12) leaderboard data pulled from swarm-routing/benchmarks (never typed by hand)
tools/hub_data.py     writes data/hub.json from the GitHub API (`--self-test` against a fake API; `--check`)
tools/release_sync.py what a release changed in the files the facts come from: the [release-sync] issue's body (#122)
tools/bot_pr.sh       opens or updates one bot/ PR from a change (release-sync.yml)
.github/workflows/release-sync.yml  on an org release (repository_dispatch org-release) and weekly: redeploy, bot/hub-data, bot/lock, the ticket (#120)
.github/workflows/release.yml  the site's own releases through swarm-routing/.github's reusable-release.yml, on the maintainer's request only; .cz.toml, CITATION.cff, `make dist` (the source tree), docs/roadmap.md (the ladder) (swarm-routing/.github#636)
```

## Build & verify

The step-by-step version for people (prerequisites, every command, the CI
map, troubleshooting) is [`docs/development.md`](docs/development.md).

CI is `.github/workflows/pages.yml` (every PR: shellcheck, build, parity,
AntHocNet's web tests, both crawls, both browser smokes with axe, in the
required build job; ruff and tools/'s self-tests under coverage, report-only,
to Codecov; `main` also deploys and runs the live smoke) and `licence.yml`. Locally (needs emsdk 4.0.10 activated,
AntHocNet's pinned mkdocs-material, doxygen, Node 22):

```bash
tools/build-site.sh build/site                 # fetches AntHocNet at the pin; AHN_SRC=<checkout> to reuse one
SKIP_ANTHOCNET=1 tools/build-site.sh build/hub # hub + project spaces only, python3 alone
python3 tools/lock.py --self-test && python3 tools/check_hub.py --self-test && python3 tools/stamp_build.py --self-test
python3 tools/hub_data.py --self-test && python3 tools/hub_data.py --check   # the generator; is data/hub.json what the issues say today?
python3 tools/release_sync.py --self-test && python3 tools/release_sync.py body swarm-routing/ns3-tools v0.2.0   # a release's ticket, read-only
python3 site/anthocnet/shell/inject.py --self-test && python3 tools/check_tokens.py --self-test && python3 tools/check_tokens.py   # the one top bar, the one token file
(cd build/src/AntHocNet && web/test/parity.sh 120 "1 2 7 42")   # native vs WASM, byte-identical
# browsers: the pinned playwright-core + axe-core resolve from the working directory, as in CI
repo=$PWD; pw=$(mktemp -d)
cp site/anthocnet/test/browser-tools/package.json site/anthocnet/test/browser-tools/package-lock.json "$pw/"
(cd "$pw" && npm ci --ignore-scripts --no-audit --no-fund && npx --no-install playwright-core install chromium \
  && node "$repo/site/anthocnet/test/smoke.mjs" "$repo/build/site/AntHocNet" \
  && node "$repo/test/hub-smoke.mjs" "$repo/build/site")
make headers   # licence headers: the Go gate CI runs (swarm-routing/.github tools/checks/check-headers.sh: docker, or go)
```

Each project page's "Cite this project" and References sections are read at
build time from that public repository's `CITATION.cff` and
`docs/references.bib` (at the `protocols.lock` pin, else `main`;
`render_hub.py` fetches raw.githubusercontent.com, and a missing, empty or
unreachable file shows no section and never fails the build). No citation
field, reference or DOI is typed here (#103). Every repository links its page
at `/projects/<id>/`: the address changes only with `swarm-routing/.github`
(org-sync's badge, each `[settings] homepage`; swarm-routing/.github#361).
Facts on the hub come from two places (#104). What the issues say is
generated, never typed: each project's status chip, the map's lock, its
quests (its repository's epics with their sub-issue counts), the quest log
(the epics in progress) and the colony level (closed sub-issues over all
sub-issues) are computed by `render_hub.py` (`repo_status`: the rule) from
`data/hub.json`, which `python3 tools/hub_data.py` writes from each public
repository's `epic` issues and latest release (the source and the states of
`swarm-routing/.github` `tools/epics/epics.py`; never edit the file by hand;
a failed request writes nothing). The build makes no API call for it: with
no file, or a repository missing from it, that status reads "status not
available" and the build succeeds. To change a status, change the issues,
then re-run `tools/hub_data.py` in a PR, or let `release-sync.yml` do it (weekly and on every org release, in the `bot/hub-data` PR, #108). What an issue cannot say (place,
glyph, tagline, summary, links, facts, package tree, sources) changes in
`site/hub/projects.json` (cite the repository's AGENTS.md; never a status, a
quest or a benchmark number, rule 12; only public repositories:
`render_hub.py` refuses others and `hub_data.py` never reads them). A change to the game is a
change to `site/anthocnet/`; a newer AntHocNet core, docs or API is a
`protocols.lock` bump PR.

Releases elsewhere in the org reach the site without a hand step (epic #120):
every release sends `org-release` (`repository_dispatch`, from
swarm-routing/.github's `reusable-release.yml` and AntHocNet's
`release.yml`), and `.github/workflows/release-sync.yml` redeploys Pages
(citation, references, DOIs), opens the `bot/hub-data` PR when the hub data
changed, opens the `bot/lock` PR when the repository is pinned in
`protocols.lock` (`tools/lock.py bump`: to the tag's commit, never backwards;
the full gate decides it), and opens one `[release-sync] <repo> <tag>` issue (never rewritten once it exists),
written by `tools/release_sync.py`, for the facts that need judgement; work it
with the `release-sync` skill (`.claude/skills/release-sync/`). A weekly run
does the same as a backstop (every pin to its latest release, a ticket for any
release of the last 14 days that has none). The PRs need the org bot's token
(`BOT_APP_ID`/`BOT_APP_PRIVATE_KEY`, else `ORG_BOT_TOKEN`): a PR opened with
`GITHUB_TOKEN` would run no checks.

## Golden rules (invariants — do not break)

Org-wide (1–9), then this repo's own.

<!-- org-sync:begin org-rules -->
1. **Licensing per directory, as AntHocNet** ([`LICENSING.md`](LICENSING.md);
   AntHocNet [LICENSING.md](https://github.com/swarm-routing/AntHocNet/blob/main/LICENSING.md),
   [ADR-0028](https://github.com/swarm-routing/AntHocNet/blob/main/docs/adr/0028-core-is-dual-licensed.md)). A
   simulator-free `core/` and the standalone tooling are `MIT OR GPL-2.0-only`;
   ns-3 modules, the site, docs and data are `GPL-2.0-only`. Every original
   `.h`/`.hpp`/`.cc`/`.cpp`/`.go`/`.py`/`.sh` starts with
   `// Copyright (c) 2026 Daniel Joppi (https://github.com/swarm-routing)` +
   `// SPDX-License-Identifier: <MIT OR GPL-2.0-only | GPL-2.0-only>` (`#`
   comments where needed), matching its directory in `LICENSING.md`; an
   outside contributor may add their own `Copyright (c) <year> <Name>` line
   beneath the org line, never replace it, and signs off every commit (DCO,
   CONTRIBUTING "Outside contributions"). CI (`reusable-licence-check.yml`)
   checks the SPDX line, and the org line's place when a header names more
   than one holder; a header with a single, other holder (a replaced org line,
   or third-party code) passes it, so review catches that. A new directory
   gets its row in `LICENSING.md` in the same PR.
2. **The licence boundary only goes one way.** GPL code may use the dual
   parts; dual code never pulls GPL-only code in: a `core/` file includes only
   the C++ standard library, other `core/` files and the dual-licensed `core/`
   of a dependency pinned by commit and declared as the `core-deps` input of
   every workflow that runs the licence check (one calling
   `reusable-licence-check.yml`, or one calling `reusable-ns3-ci.yml`, which
   forwards it; workflow file names differ per repo), each with the same pin,
   with `core-roots` naming the repo's own `core/`
   (without it the check skips core includes; a protocol's `core/` on
   swarm-core's; CI checks it, `check-headers --core-dep`), and a dual script imports no GPL-only code. Code coming from AntHocNet keeps its
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
   shared module is `swarm-core` (`#include "ns3/swarm-core-module.h"`), and
   every protocol builds on it, AntHocNet included: `core/` on its `core/`, the
   ns-3 adapter on `SwarmRoutingBase` (swarm-routing/swarm-adapter-ns3#14).
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
   Every job that runs steps has a `timeout-minutes` cap (a job that only
   calls a reusable workflow cannot take one: the called workflow's jobs carry it), and every apt, npm or installer step
   its own, sized from recent green runs; `apt-get update` runs with
   `--error-on=any` inside a shell retry. Ubuntu mirror outages are the usual
   cause of a red run.
9. **Nothing shipped depends on `.claude/`.** Skills hold procedures; scripts
   that anything shipped needs live in `tools/` (AntHocNet ADR-0014).
<!-- org-sync:end org-rules -->
10. **No routing logic in the site.** A simulation in the browser runs a protocol's own `core/` compiled to WebAssembly; the site only renders (AntHocNet ADR-0021).
11. **Browser simulations stay deterministic**: randomness drawn into named locals, no libm trig in mobility, `-ffp-contract=off`, native-vs-WASM traces byte-identical (AntHocNet golden rule 9).
12. **Leaderboard numbers come from `benchmarks` data**, regenerated by a script, never edited by hand.
13. **The site is GPL-2.0-only, like AntHocNet's `web/`**, so `web/` code may be reused as-is; only `tools/` is dual.

## Conventions

<!-- org-sync:begin conventions -->
- Issues follow the org taxonomy ([CONTRIBUTING.md](https://github.com/swarm-routing/.github/blob/main/CONTRIBUTING.md#issues), from
  [AntHocNet ADR-0013](https://github.com/swarm-routing/AntHocNet/blob/main/docs/adr/0013-track-bugs-and-findings-as-issues.md)): one type label
  (`bug`/`enhancement`/`chore`/`documentation`/`verification`, plus `epic` for
  umbrellas), area label(s) (`protocol`/`adapter`/`ns3`/`benchmark`/
  `observability`/`packaging`/`ci`/`learn-site`/`literature`), one `model:*`
  suggestion (a model on the Claude Pro plan), one `priority:P1|P2|P3` on
  non-epic issues (none on an epic), and a `release:vX.Y.Z` label only when
  a release in the repository's ladder (`docs/roadmap.md`, else the org
  ROADMAP's release train) gates the issue: that label set is the version's
  scope, released when its issues are done (CONTRIBUTING "Cutting a
  release"). Labels come from `.github`'s `labels.json`, applied to every
  repository as soon as it changes (never deleting one); a release version
  it lacks is added there (and to CONTRIBUTING's label table), or, in a
  repository that keeps its own release labels (AntHocNet), created with
  `gh label create release:vX.Y.Z`.
- Issue bodies: **Context** (evidence, numbers, links) · **Scope** ·
  **Acceptance criteria** (checkboxes) · **Depends on** (cross-repo form
  `swarm-routing/<repo>#N`) · **References**. Children of an epic say "Part of
  #N" and are linked as sub-issues. Comments you post end with the Claude Code
  footer.
- Issues migrated from AntHocNet carry `migrated` and start with *Migrated from
  `danieljoppi/AntHocNet#N`*.
- Epics are listed in a public repository's README `## Epics` and the org
  [ROADMAP](https://github.com/swarm-routing/.github/blob/main/ROADMAP.md#epics),
  generated from the `epic` issues by `.github`'s `tools/epics/epics.py`. An
  open epic is Planned (no sub-issue closed) or In progress (some closed); it
  is Done or Dropped only once the epic itself is closed (completed or not
  planned). The lists follow the issues with no hand step: an issue change
  that can move them makes the org-managed `epics-changed.yml` run org-bot's
  `epics` task, which opens the refresh PRs. Never edit a generated section
  by hand; private repositories keep none.
<!-- org-sync:end conventions -->

## Git workflow

<!-- org-sync:begin git-workflow -->
- Branch from `main` (`claude/<short-topic>`), one focused change per PR.
- **Always open a PR to `main`** once the branch is pushed — every change is
  tracked through one.
- **PRs are squash-merged** (the only merge method enabled). The PR title is
  the commit on `main`: a lowercase Conventional Commit, `type(scope)!:
  subject`, type one of `feat fix docs style refactor perf test build ci
  chore revert`, subject starting lowercase.
- Push with `git push -u origin <branch>`; merge when CI is green.
- **`main` takes no direct push**, in any repo: its ruleset requires a PR and
  the required checks, not an up-to-date branch. Bots push `bot/<name>`
  branches and open PRs; a release is the bump PR from `bot/release`, tagged
  after it merges (CONTRIBUTING "Cutting a release").
- A PR behind `main` may merge as it is. Update it
  (`gh api -X PUT "repos/<owner>/<repo>/pulls/<n>/update-branch"`, the PR's
  base repository) only when `main` changed what it touches (a template, a
  workflow, a required check), then merge after its CI. Never update a
  merge-queue PR by hand: enable auto-merge and the queue tests it on the
  latest `main` (CONTRIBUTING "Merge when CI is green"). Never force-push a
  branch someone else pushed. A behind `bot/release` PR: dispatch the release
  `bump` again.
- **Settings are code.** Settings, rulesets, required checks and the Actions
  allowlist change only by a PR to the repo's `[settings]` in
  `.github/org-sync.toml` or to `templates/rulesets/` in
  `swarm-routing/.github`, never in the UI or by a direct API write. A
  rulesets change applies on merge, a `[settings]` change on its push through
  the org-managed `settings-apply.yml` (swarm-routing/.github#569). A required
  check runs on every PR (no `paths:` filter; skip work inside a gate job) and
  is named exactly as its check run. A new third-party action goes into
  `defaults.json` `selected_actions` (`templates/rulesets/`) in swarm-routing/.github
  before or with the workflow that uses it, or `repo-settings` refuses the repo.
<!-- org-sync:end git-workflow -->

<!-- org-sync:begin skills -->
## Agent skills

The org's procedures ship as the Claude Code plugin **`swarm-routing`**
([`swarm-routing/skills`](https://github.com/swarm-routing/skills)), which this
repository's `.claude/settings.json` enables; other agents install the same
skills with `npx skills add swarm-routing/skills` ([skills.sh](https://skills.sh)).
A skill is the procedure; its script does the work without it (golden rule 9),
so an agent without the skill, or a session that does not read this
repository's settings, starts from the script. Plugin missing (it was
`org-repo` before 2026-11-09)? Run `claude plugin marketplace update
swarm-routing` and start a new session.

| Task | Script (any agent) | Skill |
|------|--------------------|-------|
| Bring this repository onto the org templates, or fix their drift | `swarm-routing/.github` `tools/org-sync/org_sync.py` | `org-repo` |
| Write or review a protocol's paper-fidelity sheet (`docs/fidelity.md`) | `swarm-routing/.github` `tools/fidelity/fidelity.py` | `fidelity-sheet` |
| Check a diff against the org golden rules before a PR or a review | `swarm-routing/.github` `tools/protocol-review/check_invariants.py` | `protocol-review` |
| Bring the README, AGENTS/CLAUDE/CONTEXT and docs/ to the org standard | `swarm-routing/.github` `tools/docs-review/check_docs.py` | `docs-review` |
| Find new papers on a topic, or confirm a reference (free sources only) | `swarm-routing/.github` `tools/lit-search/lit_search.py` | `lit-search` |
| Give a repository its docs/references.bib, or review it (every paper and org release it relies on, confirmed from its record) | `swarm-routing/.github` `tools/fidelity/fidelity.py` (bib), `tools/zenodo/zenodo.py` | `references` |
| Take open pull requests from review to merge (CI, review threads, merge) | `swarm-routing/.github` `tools/pr-status/pr_status.py` | `pr-shepherd` |
| Measure what a session loads from the agent files, or where a finished session's tokens went | `swarm-routing/skills` `tools/token-audit/token_audit.py` | `token-audit` |
| Register a repository for the OpenSSF Best Practices badge, or check its answers | `swarm-routing/.github` `cmd/bestpractices` (Go) | `bestpractices` |
| Check or bump the release a repository builds on (`swarm-core.lock`, `ns3-tools.lock`) | `swarm-routing/.github` `tools/checks/release_lock.py`, `tools/checks/check-swarm-core-pin.py` | `dependency-bump` |
| Cut a release on the maintainer's request, and its aftercare | `swarm-routing/.github` `tools/release/release_check.py`, `tools/zenodo/zenodo.py` | `release` |
| Record a reviewed SonarQube Cloud false positive or accepted finding | `swarm-routing/.github` `tools/sonar-triage/sonar_triage.py` | `sonar-triage` |

A skill only this repository uses lives in its own `.claude/skills/`; one two
repositories need moves to the plugin. Skills that file, cite and extract
papers stay in the maintainer's private library; a public skill may point to
them, never carry their content.
<!-- org-sync:end skills -->

<!-- org-sync:begin agent-defaults -->
## Working defaults

Condensed from [andrej-karpathy-skills](https://github.com/forrestchang/andrej-karpathy-skills).

- **Assumptions:** state the ones that matter. Ask only when the choice
  belongs to the maintainer (a default, a published number, a cell, the
  scope), with your recommendation and its reason, never the options alone.
  Otherwise pick the sensible option, say which, and keep going: long
  unattended runs, like campaigns, depend on that.
- **Simplicity:** the least code that solves the task. No speculative
  features, configurability or abstractions for one use.
- **Surgical diffs:** every changed line traces to the request. Match the
  surrounding style. Mention unrelated dead code rather than deleting it, and
  remove only the orphans your own change created. Update the doc or ADR of a
  documented decision you change.
- **Verifiable goals:** a bug gets a reproducing test first; a refactor passes
  before and after. Finish when the check passes, not when the code looks right.

## Session habits

- **Handoffs are always a ticket**: work in flight at a session's end, or a
  handoff asked for, is an issue from the *Handoff* template (label
  `handoff`), never a file in the repo; a session continuing a handoff
  updates that issue. Continued work starts from the newest open `handoff`
  issue for it, a new task from the request; close the issue, and any older
  one it superseded, when its work is done ([AntHocNet ADR-0013](https://github.com/swarm-routing/AntHocNet/blob/main/docs/adr/0013-track-bugs-and-findings-as-issues.md) item 5).
- **Attach only the repositories the task needs**: every request loads each
  attached repository's agent files.
- **Start from the record, not from memory:** the matching `handoff` issue,
  then the issue's acceptance criteria, then `main`. Check a claim against its
  source before it goes into an issue or a PR.
- **Script what repeats**: a check or lookup run more than a few times
  becomes a script in `tools/` that prints a summary; read the verdict, not
  the raw data (AntHocNet ADR-0014).
- **Automate what can be automated** (org CONTRIBUTING invariant 8): a step
  stays manual only when no API or permission exists for it, or the
  maintainer reserves the decision; list it in swarm-routing/.github#568.
- **Measure before cutting or adding agent text** with the `token-audit`
  skill (`swarm-routing/skills` `tools/token-audit/token_audit.py`). MCP
  servers, plugins, token habits and the long form of each pitfall below:
  [`docs/agents.md`](https://github.com/swarm-routing/.github/blob/main/docs/agents.md)
  in swarm-routing/.github (ADR-0005).

## Response style — caveman (token economy)

Answer in tight, low-filler prose: no hedging, pleasantries or preamble; same
information, fewer output tokens. **The record stays full:** code, commands,
paths, error text and benchmark numbers byte-for-byte, and commit messages,
PR bodies, ADRs, `docs/` and issue threads detailed (AntHocNet's AC_BE_NQOS /
A2 investigation was recoverable only from thorough threads). Caveman the
chat, not the record.

## Agent pitfalls

- **Before every push, run `make check`** (none: the "Build & verify"
  commands; `make pre-push TITLE='…'` where it exists) **and check the PR
  title** (Git workflow): a skipped step costs a CI round
  (swarm-routing/.github#586).
- `gh api … -F body=@file` reads the file; `-f body=@file` posts the literal
  text `@file`.
- When the permission system refuses a command (a merge, say), stop and report
  it. Never retry it another way, and never ask another agent to run it.
- Edit files with the editor tools, never a shell heredoc or `sed -i`, and
  touch one repository per command (swarm-routing/.github#578).
- Stage files by name, never `git add -A`; keep build output in `.gitignore`
  (swarm-routing/.github#644).
- A Go test reads only files under `cmd/` or `internal/` (`testdata/`)
  (swarm-routing/.github#587).
- Clean up only your own directory, never a shared one
  (swarm-routing/.github#644).
- Search an output the harness saved to a file (`grep`, `head`, `sed -n`),
  never read it whole; wait on a PR with `pr_status.py wait` or `wait
  --merged`, not by subscribing to its activity (swarm-routing/.github#794).
- A PR body's `Closes #N` closes the issue on merge; write `Part of #N` while
  acceptance criteria remain open.
- Before saying a tool or check is missing, look at `main` (`git fetch`,
  `origin/main`), not a stale local checkout.
- Write another repository's issue in full, `swarm-routing/<repo>#N`, also in
  a list or range: a bare `#N` links to the repository the text is in
  (swarm-routing/.github#277). An ns-3 item is its GitLab URL (or link text
  `nsnam/ns-3-dev#N`); text bound for ns-3's GitLab names ours by full GitHub
  URL (CONTRIBUTING "ns-3 bugs (RCAPA)").
- An issue called done in `ROADMAP.md` or an AGENTS.md is not evidence: read
  its acceptance criteria (swarm-routing/.github#274).
- Change text inside `org-sync:begin/end` markers only through
  `swarm-routing/.github` `templates/`, then org-bot's refresh PRs; never add
  such commits to an unrelated PR (swarm-routing/.github#236).
- With a merge queue, merge by enabling auto-merge (squash); a direct merge is
  refused (HTTP 405). Only the required checks (`gh api
  'repos/{owner}/{repo}/rules/branches/main'`) gate a merge; a report-only
  check (`codecov/patch`, Sonar) is triaged, not waited on. Merge an outside
  contributor's PR only after `dco` passed on its head, and never push to it
  (swarm-routing/.github#288; CONTRIBUTING "Merge when CI is green").
- `review / coderabbit` is required (swarm-routing/.github#294), so
  auto-merge may be enabled at once; still fix or answer every CodeRabbit
  thread before resolving it, and call a PR thread-free only after
  `pulls/N/comments` and the reviews show none. Where the gate is not
  required yet, wait with `pr_status.py gate REPO#N`
  (swarm-routing/.github#238).
- Never add a `Signed-off-by` trailer, for the maintainer or anyone else
  (CONTRIBUTING "Outside contributions").
- Never delete a stale branch or ask the maintainer to: org-bot's daily
  `branch-sweep` does (swarm-routing/.github#595).
- Releases are cut on request only, once the version's `release:vX.Y.Z`
  issues and its ladder exit criteria are done; never approve a gated publish;
  recover a failed publish with "Re-run all jobs"; read a DOI from Zenodo,
  never type it; never dispatch the site's `release-sync.yml` by hand
  (swarm-routing/.github#571; CONTRIBUTING "Cutting a release").
- Cite a paper by its `https://doi.org/<DOI>` link, read from its record
  (`lit-search`), or a DOI-less work by its publisher's page; never point into
  or name the private paper library.
- Never dismiss a security alert or handle a leaked secret: both are the
  maintainer's; review `security-autofix.yml`'s PRs like any other
  (swarm-routing/.github#629; CONTRIBUTING "Security alerts").
- An ns-3 bug, or its investigation, gets an RCAPA ticket in
  swarm-routing/sim-tools first (`NS3-NNN`), then its doc and register row;
  every workaround links the ID, and upstream reports go out only through
  swarm-routing/ns3-upstream-report. A regression in a published library
  version gets one in that library's repository (`<PREFIX>-NNN`), open until a
  release carries the fix; the pins and `git tag --contains` decide, never
  memory (CONTRIBUTING "RCAPA", "ns-3 bugs (RCAPA)").
<!-- org-sync:end agent-defaults -->

## Where to look

| You want to… | Go to |
|--------------|-------|
| The game and its adapter | `site/anthocnet/` (AntHocNet's `web/`, README there), AntHocNet `docs/learn-campaign.md`, the `learn-site` skill (`.claude/skills/learn-site/`) |
| How the site consumes protocol code | `docs/adr/0001-the-site-builds-protocols-from-pinned-commits.md`, `protocols.lock`, `tools/build-site.sh` |
| How the core is compiled to WebAssembly, proven identical, packaged and deployed | `docs/pipeline.md` (the record), `/pipeline/` (`pipeline_page()` in `tools/render_hub.py`; keep the two in step) |
| The hub's facts, map and diagrams | `site/hub/projects.json`, `tools/render_hub.py`, `tools/diagrams.py` |
| Sync the site with a release of another org repository | `.github/workflows/release-sync.yml` (epic #120); the `[release-sync]` issue and the `release-sync` skill (`.claude/skills/release-sync/`); `tools/lock.py bump`, `tools/release_sync.py` |
| A project's status, quests, or the colony level | the repository's issues, then `tools/hub_data.py` → `data/hub.json`; the rule: `repo_status` in `tools/render_hub.py` |
| The plan: site only here, cores built from pinned protocol commits | epic #3 (decision 2026-11-03); children #7 ADR, #8 scaffold, #9 game move, #10 docs/API, #11 cutover, #12 leaderboard, #13 second protocol; AntHocNet's half swarm-routing/AntHocNet#850 |
| Learn-site issues migrated from AntHocNet | #21 campaign epic (AntHocNet#562; children #22, #23), #24 mesh smoke flake (#751) |
| The org's invariants, labels, issue shape | [`swarm-routing/.github` CONTRIBUTING.md](https://github.com/swarm-routing/.github/blob/main/CONTRIBUTING.md) |
| The reference implementation and its history | [`swarm-routing/AntHocNet`](https://github.com/swarm-routing/AntHocNet) (`AGENTS.md`, `CONTEXT.md`, `docs/adr/`) |
| Pick up open work | this repo's issues — highest open `priority:P*` first; newest open `handoff` issue for work in flight |
