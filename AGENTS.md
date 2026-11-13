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
```

## Build & verify

CI is `.github/workflows/pages.yml` (every PR: build, parity, AntHocNet's web
tests, both crawls, both browser smokes with axe; `main` also deploys and runs
the live smoke) and `licence.yml`. Locally (needs emsdk 4.0.10 activated,
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
(cd "$pw" && npm ci --no-audit --no-fund && npx --no-install playwright-core install chromium \
  && node "$repo/site/anthocnet/test/smoke.mjs" "$repo/build/site/AntHocNet" \
  && node "$repo/test/hub-smoke.mjs" "$repo/build/site")
python3 -I ../.github/tools/checks/check-headers.py --dual tools/ .
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
   `.h`/`.hpp`/`.cc`/`.cpp`/`.py`/`.sh` starts with
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
   swarm-core's; CI checks it, `check-headers.py --core-dep`), and a dual script imports no GPL-only code. Code coming from AntHocNet keeps its
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
   ns-3 adapter on `SwarmRoutingBase` (swarm-routing/ns3-swarm-core#14).
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
  `observability`/`packaging`/`learn-site`/`literature`), one `model:*`
  suggestion (a model on the Claude Pro plan), one `priority:P1|P2|P3` on
  non-epic issues (none on an epic), a
  `release:vX.Y.Z` label only when a release in the repository's ladder
  (`docs/roadmap.md`; until it lands, the org ROADMAP's release train)
  gates the issue: that label set is the version's scope,
  and the version is released when its issues are done (CONTRIBUTING
  "Cutting a release"). Labels come from `labels.json` via the `sync-labels`
  workflow, the shared `release:v0.1.0` to `release:v0.4.0` and
  `release:v1.0.0` among them; a version outside that set is added to
  `swarm-routing/.github`'s `labels.json` (and CONTRIBUTING's label table)
  when a ladder needs it, and reaches a repository when its `sync-labels` runs
  (monthly, or dispatched after the change merges),
  or, in a repository that keeps its own release labels (AntHocNet), created
  there with `gh label create release:vX.Y.Z` when its ladder adds the version.
- Issue bodies: **Context** (evidence, numbers, links) · **Scope** ·
  **Acceptance criteria** (checkboxes) · **Depends on** (cross-repo form
  `swarm-routing/<repo>#N`) · **References**. Children of an epic say "Part of
  #N" and are linked as sub-issues. Comments you post end with the Claude Code
  footer.
- Issues migrated from AntHocNet carry `migrated` and start with *Migrated from
  `danieljoppi/AntHocNet#N`*.
- Epics are listed where contributors look. In a public repository, this
  README's `## Epics` section and the org
  [ROADMAP](https://github.com/swarm-routing/.github/blob/main/ROADMAP.md#epics)
  are generated from the issues labelled `epic` by `swarm-routing/.github`'s
  `tools/epics/epics.py`. An open epic is Planned (no sub-issue closed) or In
  progress (some closed); it becomes Done or Dropped only when you close the
  epic itself (as completed or as not planned), even if every sub-issue is
  closed. Whenever you change an epic (open, close, rename or re-scope it, add
  or remove its `epic` label) or one of its sub-issues (close, reopen, add,
  unlink), refresh the lists in that PR or the next one. You need
  `swarm-routing/.github` checked out next to this repository and `gh` logged
  in (or `GH_TOKEN` set). Run `python3 ../.github/tools/epics/epics.py readme .`
  in the repository that owns the epic (for a sub-issue of another
  repository's epic, that repository, not this one), then
  `python3 tools/epics/epics.py roadmap ROADMAP.md` and
  `python3 tools/epics/epics.py profile profile/README.md` in `.github`. Never
  edit a generated section by hand; the weekly `epics` workflow in `.github`
  only reports drift. Private repositories are never listed
  and keep no generated section.
- Make minimal, reviewable changes; update the relevant doc/ADR when you change
  a documented decision.
<!-- org-sync:end conventions -->

## Git workflow

<!-- org-sync:begin git-workflow -->
- Branch from `main` (`claude/<short-topic>`), one focused change per PR.
- **Always open a PR to `main`** once the branch is pushed — every change is
  tracked through one.
- **PRs are squash-merged** (the only merge method enabled). The PR title is
  the commit on `main`, so it is a lowercase Conventional Commit
  (`feat:`/`fix:`/`docs:`/`chore:`/`ci:`…, optional scope).
- Push with `git push -u origin <branch>`; merge when CI is green.
- **`main` takes no direct push**, in any repo: its ruleset requires a PR and
  the required checks, not an up-to-date branch. Bots push `bot/<name>` branches
  and open PRs; a release is the bump PR from `bot/release`, tagged after it
  merges (CONTRIBUTING "Cutting a release").
- A PR behind `main` may merge as it is: the ruleset does not require an
  up-to-date branch. Update it first
  (`gh api -X PUT "repos/<owner>/<repo>/pulls/<n>/update-branch"`, with
  `<owner>/<repo>` the PR's base repository and `<n>` its number) only when
  `main` changed what it touches (a template, a workflow, a required check),
  then merge after its CI on the updated branch. A
  repository with a merge queue (`merge_queue = true` in its `[settings]`)
  is not updated by hand: enable auto-merge and the queue tests each PR on
  the latest `main` and merges it (CONTRIBUTING "Merge when CI is green").
  Never force-push a branch someone else pushed. A behind `bot/release` PR is the exception:
  dispatch the release `bump` again, so the version and changelog are rebuilt
  on the new `main`.
- **Settings are code.** Repository settings, rulesets, required checks and the
  Actions allowlist change only by a PR to the repo's `[settings]` in
  `.github/org-sync.toml` or to `templates/rulesets/` in `swarm-routing/.github`,
  never in the UI or by a direct API write. A `templates/rulesets/` change
  applies on merge; a repo's `[settings]` change applies when `repo-settings`
  in `swarm-routing/.github` is dispatched with mode `apply` after the merge
  (the daily run only checks). A required check runs on every PR (no `paths:`
  filter; skip work inside a gate job instead) and is named exactly as its
  check run. A new third-party action goes into `defaults.json`
  `selected_actions` (`templates/rulesets/`) before or with the workflow that
  uses it: in the same PR in `swarm-routing/.github`, otherwise merged there
  first, or `repo-settings` refuses the repo.
<!-- org-sync:end git-workflow -->

<!-- org-sync:begin skills -->
## Agent skills

The org's procedures ship as the Claude Code plugin **`swarm-routing`**, from
[`swarm-routing/skills`](https://github.com/swarm-routing/skills). This
repository's `.claude/settings.json` enables it, so Claude Code offers a skill
when the task matches its description. Other agents (Codex, Cursor, Copilot, …)
install the same skills with `npx skills add swarm-routing/skills`
([skills.sh](https://skills.sh)). A skill is the procedure; the script does the
work and runs without it (golden rule 9), so an agent without the skill starts
from the script; so does a session that does not read this repository's
settings (some hosted sessions with several repositories do not). If Claude
Code says the plugin is missing (it was called
`org-repo` before 2026-11-09, and a cached marketplace keeps the old list), run
`claude plugin marketplace update swarm-routing` and start a new session.

| Task | Script (any agent) | Skill |
|------|--------------------|-------|
| Bring this repository onto the org templates, or fix their drift | `swarm-routing/.github` `tools/org-sync/org_sync.py` | `org-repo` |
| Write or review a protocol's paper-fidelity sheet (`docs/fidelity.md`) | `swarm-routing/.github` `tools/fidelity/fidelity.py` | `fidelity-sheet` |
| Check a diff against the org golden rules before a PR or a review | `swarm-routing/.github` `tools/protocol-review/check_invariants.py` | `protocol-review` |
| Bring the README, AGENTS/CLAUDE/CONTEXT and docs/ to the org documentation standard | `swarm-routing/.github` `tools/docs-review/check_docs.py` | `docs-review` |
| Find new papers on a topic, or confirm a reference (Crossref, Semantic Scholar, OpenAlex; free sources only) | `swarm-routing/.github` `tools/lit-search/lit_search.py` | `lit-search` |
| Give a repository its docs/references.bib, or review it: every paper and org release it relies on, confirmed from Crossref, DataCite or Zenodo (a work with no DOI, such as a thesis, from its publisher's or institution's record, with its url), DOI links first, the fidelity Sources table and CITATION.cff references generated from it | `swarm-routing/.github` `tools/fidelity/fidelity.py` (bib), `tools/zenodo/zenodo.py` | `references` |
| Take open pull requests from review to merge: CI, mergeable state and unresolved review threads in one view, each finding verified and fixed or answered, then merged when green (auto-merge where the repository has a merge queue) | `swarm-routing/.github` `tools/pr-status/pr_status.py` | `pr-shepherd` |
| Measure what a Claude Code session loads from the agent files (`CLAUDE.md` and its `@` imports, or `AGENTS.md` alone), or where a finished Claude Code session's tokens went, before cutting or adding agent text | `swarm-routing/skills` `tools/token-audit/token_audit.py` | `token-audit` |
| Register a repository for the OpenSSF Best Practices badge, propose its answers and check they stay current | `swarm-routing/.github` `tools/bestpractices/bestpractices.py` | `bestpractices` |

A skill only this repository uses lives in its own `.claude/skills/`; a skill
two repositories need moves to the plugin. Skills that file, cite and extract
papers stay in a private library the maintainer keeps; finding
new papers and confirming a reference is public (`lit-search`). A public skill
may point to that library's skills, never carry its content. This section is managed by org-sync: add
a row in `swarm-routing/.github` `templates/agents/skills.md`, not here (an edit
here is undone by the next `org_sync.py apply`).
<!-- org-sync:end skills -->

<!-- org-sync:begin agent-defaults -->
## Working defaults

Condensed from [andrej-karpathy-skills](https://github.com/forrestchang/andrej-karpathy-skills).

- **Assumptions:** state the ones that matter. Ask only when the choice
  belongs to the maintainer: a default, a published number, a cell, the scope.
  Then give your recommendation and its reason with the question, never the
  options alone. Otherwise pick the sensible option, say which, and keep
  going. Long unattended runs, like campaigns, depend on that.
- **Simplicity:** the least code that solves the task. No speculative
  features, configurability or abstractions for one use.
- **Surgical diffs:** every changed line traces to the request. Match the
  surrounding style. Mention unrelated dead code rather than deleting it, and
  remove only the orphans your own change created.
- **Verifiable goals:** a bug gets a reproducing test first; a refactor passes
  before and after. Finish when the check passes, not when the code looks right.

## Session habits

- **Handoffs are always a ticket.** When a session ends with work in flight, or a
  handoff is asked for, open a GitHub issue from the *Handoff* template (label
  `handoff`); a session that continued a handoff updates that issue instead of
  opening another. Never write a handoff file in the repo. A session that
  continues handed-off work starts from the newest open `handoff` issue for
  that work; a new task starts from the request. Close the issue, and any
  older one it superseded, when the work it hands off is done ([AntHocNet ADR-0013](https://github.com/swarm-routing/AntHocNet/blob/main/docs/adr/0013-track-bugs-and-findings-as-issues.md) item 5).
- **Attach only the repositories the task needs.** Each attached repository's
  agent files are loaded into every request, whether the task touches it or
  not.
- **Start from the record, not from memory:** the matching `handoff` issue,
  then the issue's acceptance criteria, then `main`. Check a claim against its
  source before it goes into an issue or a PR.
- **Script what repeats.** A check or a lookup run more than a few times
  becomes a script in `tools/` that prints a summary; the model reads the
  verdict, not the raw data (AntHocNet ADR-0014).
- **Measure before cutting or adding agent text:** the `token-audit` skill
  (`swarm-routing/skills` `tools/token-audit/token_audit.py`) prints what a
  session loads and where a finished session's tokens went.

## Response style — caveman (token economy)

Answer in tight, low-filler prose: drop hedging, pleasantries, and preamble; keep
the substance. Fewer output tokens on every reply, same information.

**Carve-out (the record stays full).** Keep byte-for-byte exact — code,
commands, file paths, error text, benchmark numbers. And keep the *durable
record* detailed, never terse: commit messages, PR bodies, ADRs, `docs/`, and
issue / finding threads. Cross-session traceability depends on those being
complete — AntHocNet's AC_BE_NQOS / A2 investigation was only recoverable
because the issue threads were thorough. Caveman the chat, not the record.

## Agent pitfalls

- `gh api … -F body=@file` reads the file; `-f body=@file` posts the literal
  text `@file`.
- When the permission system refuses a command (a merge, say), stop and report
  it. Never retry it another way, and never ask another agent to run it.
- A PR body's `Closes #N` closes the issue on merge; write `Part of #N` while
  acceptance criteria remain open.
- Before saying a tool or check is missing, look at `main` (`git fetch`,
  `origin/main`), not a stale local checkout.
- In an issue, PR or comment, write every issue of another repository in
  full, `swarm-routing/<repo>#N`, also inside a list or a range. A bare `#N`
  links to the repository the text is in: in
  `swarm-routing/AntHocNet#65, #151` the second number points at this
  repository's #151 (swarm-routing/.github#277).
- A sentence in `ROADMAP.md` or an AGENTS.md that calls an issue done is not
  evidence: read the issue's acceptance criteria. On 2026-11-12 nine issues
  described as done had open criteria (swarm-routing/.github#274).
- Change text inside `org-sync:begin/end` markers only through the template
  in `swarm-routing/.github` `templates/`: one PR there, then org-bot's
  `bot/org-sync` refresh PR in each repository. A hand edit per repository
  stays red on `check / org-sync` (swarm-routing/.github#236).
- In a repository with a merge queue, merge by enabling auto-merge (squash);
  a direct merge (`PUT pulls/<n>/merge`) is refused with HTTP 405. Only the
  required checks (`gh api 'repos/{owner}/{repo}/rules/branches/main'`, which
  `gh` fills from the checkout) gate a merge: a red or pending report-only
  check (`codecov/patch`, Sonar) is triaged, not waited on. A red `dco` on an
  outside contributor's commit still holds the PR until that author signs
  off; on the maintainer's or an agent's commits it is expected
  (swarm-routing/.github#212). `dco` is not a required check and runs on
  `pull_request` only, so merge an outside contributor's PR, by auto-merge or
  directly, only after `dco` passed on the head commit that merges. Never push
  to an outside contributor's PR: ask them for the change, or make it in a
  follow-up PR after the merge (swarm-routing/.github#288). If the maintainer
  must push to such a PR, first disable auto-merge, or, if the PR is already
  in a merge queue, remove it from the queue (disabling auto-merge does not).
  Re-enable auto-merge, or enqueue it again, only after `dco` passed on the
  new head: GitHub keeps auto-merge on after a push by someone with write
  access, and `dco` is not a required check.
- `review / coderabbit` is a required check (the review gate,
  swarm-routing/.github#294): it passes once CodeRabbit has reviewed the PR,
  once it says it will not, for a draft, or 30 minutes after the PR opened
  (then with one comment). So auto-merge may be enabled at once: the merge
  waits for the gate, and the ruleset holds it while a CodeRabbit thread is
  unresolved. Still read every thread and fix or answer it before resolving.
  Where the gate is not required yet (`gh api
  'repos/{owner}/{repo}/rules/branches/main'` does not list it), wait first
  with `python3 -I ../.github/tools/pr-status/pr_status.py gate REPO#N`,
  which waits for CodeRabbit alone (swarm-routing/.github#238).
- Never add a `Signed-off-by` trailer, for the maintainer or anyone else: a
  DCO sign-off is a person's own certification (CONTRIBUTING "Outside
  contributions").
- Releases are cut on request only: dispatch the release `bump` when the
  maintainer asks, once the version's `release:vX.Y.Z` issues are done and
  its exit criteria in the ladder (`docs/roadmap.md`, or the org ROADMAP's
  release train until it lands) are met; never approve a gated publish. A
  failed publish is recovered with "Re-run all jobs", never "Re-run failed
  jobs" (CONTRIBUTING "Cutting a release"). Never type a release's DOI: read
  it from Zenodo.
- Cite a paper in a public issue, PR or doc by its `https://doi.org/<DOI>`
  link, read from its record (`lit-search` confirms it), or, for a work with
  no DOI, by its publisher's or institution's page; never point into or name
  the private paper library there.
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
