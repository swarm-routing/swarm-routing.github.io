---
name: release-sync
description: Work a `[release-sync] <repo> <tag>` issue in swarm-routing.github.io — bring the Colony Arena site's hand-kept facts about one org repository (site/hub/projects.json: tagline, summary, facts, package tree, links, sources; its repos row; its diagrams) up to a release, citing the repository at the tag, and close the issue by PR. Use when such an issue is open, when an org repository has released and its project page at /projects/<id>/ may be out of date, or when asked to sync the site with a release. Also how to bump protocols.lock by hand.
---

# release-sync

A release of any public org repository reaches the site in four ways (epic
#120, `.github/workflows/release-sync.yml`): the Pages rebuild (citation,
references, DOIs), the `bot/hub-data` PR (statuses, quests), the `bot/lock`
PR for a protocol pinned in `protocols.lock`, and one `[release-sync] <repo>
<tag>` issue for what needs judgement. This skill works that issue. The first
three need nobody: do not redo them by hand.

## 1. Start from the issue

Read the issue: it was written by `tools/release_sync.py` and holds the
release, the previous one, which of the files the facts come from changed
(AGENTS.md, README, CITATION.cff, references, fidelity, roadmap, LICENSING,
CHANGELOG), the top-level entries added or removed, AGENTS.md's status
paragraph before and after, and the changelog section. If it is stale or you
want it again:

```bash
python3 tools/release_sync.py body swarm-routing/<repo> <tag>   # --prev <tag> to compare with another release
```

The script reads; it never edits. Read its summary, not raw diffs (AntHocNet
ADR-0014). Open a file at the tag only where the summary says it changed:
`gh api repos/swarm-routing/<repo>/contents/<path>?ref=<tag> --jq .content | base64 -d`.
Where the GitHub API is out of reach (a cloud session whose `gh` serves search
only), the issue body is the same summary, and a tree-only clone serves the
files: `git clone --depth 1 --branch <tag> --filter=blob:none --no-checkout
https://github.com/swarm-routing/<repo>`, then `git ls-tree` and `git show HEAD:<path>`.

Several tickets open for one repository: work the newest, which covers every
release since the page's sources were last read, and close the older ones as
not planned with a comment naming it (a renamed repository's tickets carry
its old name). Several repositories: work each ticket on its own branch.

## 2. Change only what the release changed

In `site/hub/projects.json`, the project entry (`id` = the page at
`/projects/<id>/`) and the `repos` row of that repository:

| Field | Source at the tag |
|-------|-------------------|
| `tagline`, `summary` | AGENTS.md "What this repo is", README's opening |
| `facts` | AGENTS.md (module names, licence split, what it promotes), `docs/fidelity.md` |
| `tree` | the top-level tree and AGENTS.md's layout block: a path is `present` only if it exists at the tag |
| `links`, `sources` | the repository, its epics, its papers (by `https://doi.org/` link, read from the record, never typed) |
| `repos` row: `role`, `packages`, `licence` | AGENTS.md, `LICENSING.md` |

Rules (AGENTS.md "Golden rules"):

- never a status, a quest, a release number or a benchmark number: those are
  generated (`data/hub.json`, rule 12);
- every sentence traceable to the repository at the tag; say so in the PR
  with the file and line;
- only public repositories (`render_hub.py` refuses others);
- a change in the repository's structure may change its diagram in
  `tools/render_hub.py` / `tools/diagrams.py`: change it there, never draw it
  by hand;
- a sentence that names another repository's release (a lock such as
  `swarm-core.lock`, `swarm-adapter-ns3.lock`, `ns3-tools.lock`) goes stale
  when that lock moves, on this page or on the page of the repository it
  names: read the locks at the tag (`git show HEAD:<lock>`) and fix both pages
  when one moved to another repository's release.

When nothing on the page needs to change, say what you checked in a comment
on the issue and close it as completed. That is a valid outcome.

## 3. Check

```bash
python3 tools/render_hub.py --self-test && python3 tools/check_hub.py --self-test
SKIP_ANTHOCNET=1 tools/build-site.sh build/hub   # hub + project pages, python3 alone
python3 tools/check_tokens.py
# the hub smoke, as AGENTS.md "Build & verify" (pinned playwright-core + axe)
node test/hub-smoke.mjs build/hub
```

Look at `build/hub/projects/<id>/index.html` in a browser (day and night) for
the changed sections.

## 4. Close by PR

Branch `claude/<topic>`, a lowercase Conventional Commit title such as
`docs(hub): the <repo> <tag> release on its project page` (the subject must
start lowercase, and many repository names do not: ARA, BeeAdHoc, HOPNET,
`title / title` fails on `docs(hub): ARA v0.2.0 ...`), a body that lists each changed
field with its source (file and line at the tag), and `Closes #<issue>`. Enable
auto-merge; the merge queue squashes after the required checks.

Open several such PRs about an hour apart. CodeRabbit reviews one PR per hour
on this repository's plan; a PR opened inside that hour gets "Review limit
reached" instead of a review, and its required `review / coderabbit` check
still passes, so it merges unreviewed. Push every branch at once if you like,
open the PRs one by one, and read each review's threads (fix or answer, then
resolve) before opening the next.

## By hand: bump protocols.lock

The `bot/lock` PR does this on a release. To do it yourself:

```bash
python3 tools/lock.py bump <name> --to <tag>   # one protocol, to a tag; refuses to move backwards
python3 tools/lock.py bump --all               # each entry to its latest release, skipping one that is behind
```

Then a PR `chore(lock): bump <name> to <tag>`; the full Pages gate (build,
parity, crawls, smokes with axe) decides it.
