# Prototypes: Colony Arena, the next version

Storyboards for the epic "Colony Arena for researchers: a game that leads to
evidence". They show a direction; they are **not** the shipped site and
nothing in `site/` or the build reads them. Open a file straight from disk
(no server, no build), or look at the pictures in `img/`.

| Prototype | What it proposes | Picture |
|-----------|------------------|---------|
| [`game.html`](game.html) | The game page: one Play button over the running world, ants you can see (scout, returner, worker with a crumb, repair ant), a trail that glows with the pheromone, a narrator ("The Daily Pheromone"), one progress system, a level-end card that leads to the measured result, the ns-3 kit and the paper. Phones stay phones. | `img/game-start.png`, `img/game-play.png`, `img/game-night.png`, `img/game-win.png`, `img/game-map.png`, `img/game-phone.png` |
| [`experiment.html`](experiment.html) | Experiment mode: one parameter, 20 seeds, the paired difference with its 95 % confidence interval, a CSV, a link that reproduces it, the ns-3 command. | `img/experiment.png` |
| [`duel.html`](duel.html) | Duel mode: two protocols on the same world and seed, side by side. | `img/duel.png` |
| [`project.html`](project.html) | A project page at `/projects/<id>/` (today `/arena/<id>/`): a "Cite this project" block and the references with DOI links. | `img/project.png` |

`game.html` takes `#play`, `#play+night`, `#play+detour`, `#play+win` and
`#play+map`; `duel.html` takes `#cut`; `experiment.html` takes `#night`.

## What is real and what is not

- **No protocol runs in `game.html` or `duel.html`.** `scene.js` plays ants
  along paths the page lists; the counters count the animation. Golden rule
  10 stands: the shipped page draws the events of the protocol's own `core/`
  compiled to WebAssembly.
- **Every number in `experiment.html` is mock data** from a seeded generator
  in the page, and the page and its CSV say so. The parameter names and the
  ns-3 attribute prefix are the shipped bench's (`config-fields.json`).
- **The level-end card shows no number.** It is filled at build time from
  `swarm-routing/benchmarks` (golden rule 12), and stays empty until a
  released run covers the cell.
- **`project.html` shows AntHocNet's own citation data.** A script read the
  fields from `swarm-routing/AntHocNet` `CITATION.cff` and the 20 entries
  from its `docs/references.bib` (with this repository's `tools/bib.py`) at
  commit `9eaa325760777deedcc802683134bf6de171d68d`; none was typed. The
  version DOI is left empty: the shipped page reads it from Zenodo.

`proto.css` holds the tokens: the hub's warm set (`site/hub/arena.css`), day
and night. Licence: GPL-2.0-only, as the rest of `docs/`.
