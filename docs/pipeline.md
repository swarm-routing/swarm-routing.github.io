# The pipeline: the original core, compiled, packaged and deployed

Every simulation on this site runs the protocol's own C++ routing code: the
same `core/` that the ns-3 module and the benchmarks run, compiled to
WebAssembly from the protocol's repository at the commit pinned in
[`protocols.lock`](../protocols.lock). Nothing is rewritten in JavaScript and
nothing is vendored. This page is the written record of how that works; the
site shows the same pipeline as diagrams at
[`/pipeline/`](https://swarm-routing.github.io/pipeline/), rendered by
`tools/render_hub.py`. The decision behind it is
[ADR-0001](adr/0001-the-site-builds-protocols-from-pinned-commits.md).

AntHocNet is the one protocol in the browser today, so the paths below are its.
A second protocol follows the same steps under `site/<protocol>/` (#13).

## 1. What the browser runs

| Part | Where it comes from | What it does |
|------|---------------------|--------------|
| The routing core | AntHocNet `core/src/{pheromone_table,pheromone_engine,ant_history,ant_message_codec,ant_router_logic,link_metric_registry}.cpp` and `core/include/`, at the pinned commit, unmodified | every routing decision: ants, pheromone, next-hop choice, the wire codec |
| The browser adapter | this repository, `site/anthocnet/src/` (`sim.cpp`, `scenarios.cpp`, `bindings.cpp`) | the world, mobility and radio, the built-in scenarios, the Embind binding; it moves packets and carries out the core's decisions |
| The game | this repository, `site/anthocnet/site/` | draws what the WebAssembly module reports; no routing logic (AntHocNet ADR-0021, golden rule 10 here) |

The build is `site/anthocnet/CMakeLists.txt`. It compiles the core sources
and the adapter, as C++23 in Release mode with `-ffp-contract=off` and no
fast-math, into one static library, `ahn_web`. That library is linked three
ways:

- `anthocnet`: Emscripten only, with `--bind -sMODULARIZE=1 -sEXPORT_ES6=1
  -sEXPORT_NAME=createAntHocNet -sENVIRONMENT=web,worker,node
  -sALLOW_MEMORY_GROWTH=1 -sFILESYSTEM=0`. It produces `anthocnet.wasm` and its
  ES-module loader `anthocnet.js`.
- `ahn-web-trace`: the parity trace runner, built both natively and to
  WebAssembly (under node).
- `ahn-web-features`: the scenario link-rule checks, built both ways.

The compiler is Emscripten at the protocol's own pin: emsdk `4.0.10`, from
AntHocNet's `.github/actions/setup-emsdk`.

The game's `site/js/engine.js` does `import createAntHocNet from
'../anthocnet.js'`. The assembly step rewrites that import to
`anthocnet.js?v=<first 12 hex of sha256(anthocnet.wasm)>`, and the loader's
`.wasm` URL the same way. A new core therefore always reaches the browser past
the service worker and the HTTP caches.

## 2. Proof that it is the same code

Running the core's code is checked, not just claimed.
`site/anthocnet/test/parity.sh` builds the trace runner and the feature checks
twice, natively and with `emcmake`, then:

- runs the scenario features' link-rule checks in both builds; their outputs
  must be identical;
- for each seed (default `1 2 7 42`), runs every built-in scenario for 120
  simulated seconds in both builds. Each trace records every ant and data
  transmission, reception, route change, queue and drop, with its simulated
  time. The native and WebAssembly traces must be byte-identical;
- requires every scenario to deliver traffic, because a trace that delivers
  nothing proves nothing.

The comparison is only possible because the browser simulation is
deterministic (golden rule 11):
- randomness is drawn into named locals, since argument evaluation order
  differs between compilers;
- mobility uses arithmetic `detSin`/`detCos`, never libm trigonometry;
- floating-point contraction is off, since one fused multiply-add on one side
  changes the last bit.

Parity runs:
- on every pull request here, against the pinned core (`pages.yml`);
- on every pull request to AntHocNet, against that pull request's `core/`.
  AntHocNet's CI fetches this repository's `site/anthocnet/` at `main` into a
  git-ignored `web/` (`tools/checks/fetch-site-web.sh`) and runs the same
  script.

A `core/` change that breaks parity therefore fails in AntHocNet before it can
be pinned here.

## 3. Package and deploy

One script builds the site, locally and in CI: `tools/build-site.sh`. One
workflow gates and ships it: `.github/workflows/pages.yml`. A newer core
reaches the site only through a `protocols.lock` bump pull request, which runs
every gate before anything is published.

| # | Step | Where | What happens |
|---|------|-------|--------------|
| 1 | Pin | `protocols.lock`, `tools/lock.py` | One line per protocol: `<name> <owner/repo> <40-char commit> <tag or ->`. It changes by pull request only; `lock.py` refuses short SHAs and duplicates. |
| 2 | Fetch | `pages.yml` (`actions/checkout` at the SHA); `tools/build-site.sh` locally | The protocol is checked out at the pinned commit. Its `core/`, `docs/`, `api/`, `results/` and toolchain pins (emsdk, mkdocs-material) come from that checkout. `build-site.sh` refuses a checkout that is not at the pin. |
| 3 | Overlay | `tools/build-site.sh` | `site/anthocnet/` is laid over the checkout as its `web/`. |
| 4 | Compile | `site/anthocnet/CMakeLists.txt`, via `web/build-site.sh` | `emcmake cmake` and `cmake --build --target anthocnet` produce `anthocnet.wasm` and `anthocnet.js` (section 1). |
| 5 | Assemble | `site/anthocnet/build-pages.sh`, then `tools/render_hub.py` | The game with the module, cache-busted by its hash, and the offline manifest; the protocol's mkdocs docs at `docs/` (`mkdocs build --strict`); its Doxygen API at `api/`; all under one top bar (`shell/inject.py`); plus the old-URL redirects. All of it goes to `/AntHocNet/`. Then the hub, every `/arena/<id>/` space and `/pipeline/` are rendered, and AntHocNet's 404 becomes the site's `/404.html`. |
| 6 | Prove | `site/anthocnet/test/parity.sh 120 "1 2 7 42"`, `test/xray.test.mjs` | Native and WebAssembly are byte-identical (section 2), and the native codec decodes the page's ant bytes to the same fields. |
| 7 | Check | `pages.yml` | AntHocNet's web tests: quest parser, translations, Nest coverage (strict here), tuning bench, campaign levels and labs. Both crawls: AntHocNet's `check-site.py` and this repo's `check_hub.py` check every link, asset and anchor, and `check_hub.py` that every page carries the site's one top bar; `check_tokens.py` that no style sheet defines a colour, radius or font outside `shell/tokens.css`. Both browser smokes run with axe in day and night: `site/anthocnet/test/smoke.mjs` and `test/hub-smoke.mjs`. The core coverage badge data is written to `/AntHocNet/badges/coverage.json` (report-only). |
| 8 | Deploy | `actions/upload-pages-artifact`, `actions/deploy-pages` | On `main` only: the assembled tree is the Pages artifact (retention 3 days) and is published. Pull requests run steps 1–7 and stop. |
| 9 | Verify | `site/anthocnet/test/live-smoke.mjs`, `pages.yml` `live-smoke` | The live `engine.js` must import the module this build made; the game must deliver; the docs, API, Workshop and 404 must carry the top bar. The hub, `/pipeline/` and every project space must answer 200. A failure opens, or comments on, one tracking issue. |

The `pages-<ref>` concurrency group allows one deployment at a time and never
cancels a publish that is in flight.

### Reproduce it locally

You need emsdk 4.0.10 activated, AntHocNet's pinned mkdocs-material, doxygen
and Node 22; `AGENTS.md` "Build & verify" has the full list:

```bash
tools/build-site.sh build/site                       # steps 2-5: fetch the pin, overlay, compile, assemble
(cd build/src/AntHocNet && web/test/parity.sh 120 "1 2 7 42")   # step 6
python3 tools/lock.py --self-test && python3 tools/check_hub.py --self-test
SKIP_ANTHOCNET=1 tools/build-site.sh build/hub       # the hub, the project spaces and /pipeline/ only (python3 alone)
```

The browser smokes (step 7) need the pinned `playwright-core` and `axe-core`
from `site/anthocnet/test/browser-tools/`; AGENTS.md has the commands.

## 4. Bumping the core

1. Open a pull request that changes the AntHocNet line in `protocols.lock`
   to the new 40-character commit.
2. Its `pages.yml` run builds that commit and runs steps 1–7. If the new core
   adds or removes a public class, add or remove its chamber in
   `site/anthocnet/site/js/nest-data.js` in the same pull request, because
   the Nest rule is strict here and only warns in AntHocNet.
3. Squash-merge when green. `main` then deploys and verifies (steps 8–9).
