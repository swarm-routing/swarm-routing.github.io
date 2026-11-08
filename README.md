# swarm-routing.github.io

**Colony Arena**, the swarm-routing organisation's site:
<https://swarm-routing.github.io/>.

- `/` — the colony map of every org project, the public repositories' package
  structure, the roadmap as a quest log, and the architecture as diagrams;
- `/arena/<project>/` — a space per project: what it does, UML diagrams,
  package structure, quests;
- `/AntHocNet/` — AntHocNet's game, with its docs at `/AntHocNet/docs/` and
  API at `/AntHocNet/api/`;
- `/pipeline/` — how the site runs and ships: the compile, the parity proof,
  and the package-and-deploy pipeline as diagrams.

Every simulation runs a protocol's original C++ `core/`, compiled to
WebAssembly with Emscripten from its repository at the commit pinned in
[`protocols.lock`](protocols.lock). Nothing is vendored or rewritten in
JavaScript, and a native-vs-WebAssembly parity gate checks it byte for byte
([ADR-0001](docs/adr/0001-the-site-builds-protocols-from-pinned-commits.md);
the compile, the proof and the deploy step by step:
[docs/pipeline.md](docs/pipeline.md)).
Build: `tools/build-site.sh` (see [AGENTS.md](AGENTS.md)). Licence: GPL-2.0-only,
`tools/` MIT OR GPL-2.0-only ([LICENSING.md](LICENSING.md)).
