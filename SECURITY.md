# Security Policy

`swarm-routing/swarm-routing.github.io` is the org's static website (Colony Arena), served by GitHub Pages. This document records its
security posture honestly; it promises nothing the code does not do. The
org-wide policy is [swarm-routing/.github SECURITY.md](https://github.com/swarm-routing/.github/blob/main/SECURITY.md).

## Trust boundary

<!-- Which input is untrusted, the only code that parses it, and what that
code guarantees. A protocol: its wire-format decoder (org invariant 3). A
tool: the parsers of files it reads. If nothing parses untrusted input, say
so in one line. -->
None beyond static content served by GitHub Pages. The simulations run each
protocol's own `core/` compiled to WebAssembly in the visitor's browser
(golden rule 10), from the commits pinned in `protocols.lock`; leaderboard
data will be regenerated from swarm-routing/benchmarks by a script (golden
rule 12).

**Report privately:** script injection through site content or leaderboard
data, a third-party script loaded from somewhere it should not be, or a
deploy that does not match `main`.

## Known, by-design limitations (out of scope)

- A simulation in the browser is a teaching model, not a security claim about
  any protocol.

<!-- org-sync:begin reporting -->
## Reporting a vulnerability

Report privately through GitHub's private vulnerability reporting: the
repository's **Security** tab, then **Report a vulnerability**. If that is
not available, open an issue that only asks for a private contact, and put
no vulnerability details in it. This is a research project maintained on a
best-effort basis: expect an acknowledgement within a few days, not an SLA.
<!-- org-sync:end reporting -->

## Verifying what it ships

Pages deploys only from `main` through `.github/workflows/pages.yml`; the
run that deployed a version names its commit, and `protocols.lock` names the
protocol commits that version was built from.
