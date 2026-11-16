# RCAPA: does not apply to swarm-routing/swarm-routing.github.io's own changes

An **RCAPA** (root cause analysis with corrective and preventive actions) is
required for a regression in a **published library**: a version another
project consumes (a swarm-core or ns3-tools release through its lock or PyPI,
a protocol core's vcpkg port), and for every upstream ns-3 bug. The rule and
its decision table are in [CONTRIBUTING.md, "RCAPA"](https://github.com/swarm-routing/.github/blob/main/CONTRIBUTING.md#rcapa) ([ADR-0003](https://github.com/swarm-routing/.github/blob/main/docs/adr/0003-rcapa-for-ns3-bugs-and-released-regressions.md)).

**RCAPA does not apply to this repository's own changes**, because
nothing consumes it at a version. What it publishes is the Pages deploy of
https://swarm-routing.github.io from `main`. A broken page, game or link is
an ordinary `bug` issue, fixed by the next deploy.

**Where RCAPA applies instead:** the site builds AntHocNet at the commit `protocols.lock` pins; a defect in
AntHocNet's core shown by the game is AntHocNet's (its `docs/rcapa/README.md`
says when that is an RCAPA). An ns-3 bug is an `NS3-NNN` in
swarm-routing/ns3-tools.

The "open RCAPA" badge in the README counts this repository's open issues
labelled `rcapa`, so it reads 0 here.
