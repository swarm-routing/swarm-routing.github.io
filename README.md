# swarm-routing.github.io

**Colony Arena**, the swarm-routing organisation's site:
<https://swarm-routing.github.io/>.

- `/` — the colony map of every org project, the public repositories' package
  structure, the roadmap as a quest log, and the architecture as diagrams;
- `/arena/<project>/` — a space per project: what it does, UML diagrams,
  package structure, quests;
- `/AntHocNet/` — AntHocNet's game, with its docs at `/AntHocNet/docs/` and
  API at `/AntHocNet/api/`.

Every simulation runs a protocol's own `core/`, built from its repository at
the commit pinned in [`protocols.lock`](protocols.lock); nothing is vendored
([ADR-0001](docs/adr/0001-the-site-builds-protocols-from-pinned-commits.md)).
Build: `tools/build-site.sh` (see [AGENTS.md](AGENTS.md)). Licence: GPL-2.0-only,
`tools/` MIT OR GPL-2.0-only ([LICENSING.md](LICENSING.md)).
