# Roadmap

Which release each piece of work serves, and what each release must show to
ship. Releases are cut on the maintainer's request only (swarm-routing/.github
CONTRIBUTING "Cutting a release"); the org-wide view is the
[org ROADMAP](https://github.com/swarm-routing/.github/blob/main/ROADMAP.md).
A version's scope is the set of issues labelled `release:vX.Y.Z`; the release
workflow's ladder gate refuses a bump whose version has no row here.

Pages deploys every merge to `main`; a release tags one of those commits, so
the site's source has a citable, verifiable version (maintainer decision on
[swarm-routing/.github#636](https://github.com/swarm-routing/.github/issues/636),
2026-11-17).

## Release ladder

| Release | Theme | Exit criteria |
|---|---|---|
| v0.1.0 | first tagged release | `release.yml` on `reusable-release.yml`, `.cz.toml` and `CITATION.cff` in place; `pages.yml` green on `main` (build, parity, crawls, smokes with axe) and the live smoke green; a dry run green; no open issue labelled `release:v0.1.0`; the maintainer asks for it |

## Non-goals

- No release per deploy: every merge to `main` already reaches Pages.
