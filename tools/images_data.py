#!/usr/bin/env python3
# Copyright (c) 2026 Daniel Joppi (https://github.com/swarm-routing)
# SPDX-License-Identifier: MIT OR GPL-2.0-only
"""Write data/images.json: the org's container images and their tags, read
from the registry (the /images/ page).

For every package in PACKAGES, reads ghcr.io's public registry API with an
anonymous pull token (no secret: the packages are public, and a package that
is not answers DENIED, which stops the run):
  /token?scope=repository:<org>/<name>:pull     the anonymous token
  /v2/<org>/<name>/tags/list                    every tag (Link: next pages)
  /v2/<org>/<name>/manifests/<tag>              each rolling tag's digest
  /v2/<org>/<name>/manifests/<digest>           an index's linux/amd64 image
  /v2/<org>/<name>/blobs/<config digest>        its labels and creation time
A rolling tag is every tag but the immutable pins (`<tag>-<sha7>`,
`sha-<sha7>`) and the signatures (`sha256-...`); the tags that share a
digest are one image (one row). An image's pin is its most specific rolling
tag plus the first seven characters of its `org.opencontainers.image.revision`
label, when that tag exists; earlier builds (the other commits its tags were
pinned at) are counted, not listed. Release,
profile and base come from the image's labels (`org.opencontainers.image.version`,
`io.github.swarm-routing.ns3.profile`, `.ns3.base`), else from its tag. Title
and description come from the index's annotations or the image's labels, the
package's description from its newest image, else the first paragraph of its
repository's README (fetched only then). Sizes are the compressed layers of
the linux/amd64 image, dates the day the image was created (UTC).

tools/render_hub.py reads the file at build time, so the Pages build makes no
registry call; a build without the file says the data is not available.

The file is deterministic: packages in PACKAGES order, images by release
(newest first), base and profile, keys sorted, and one date, `asOf` (UTC).
When nothing but the date would change, the file is left alone. Any failed
request exits non-zero and writes nothing.

Which packages are listed is a choice, made here: the images people pull.
The org also publishes run- and PR-scoped candidates, build caches,
per-commit campaign images and frozen predecessors; NOT_LISTED names them
and why, and the page says so.

Usage: python3 tools/images_data.py [--out data/images.json] [--as-of YYYY-MM-DD] [--check]
       python3 tools/images_data.py --self-test
--check writes nothing and exits 1 when the file is stale. Stdlib only.
"""
from __future__ import annotations

import datetime
import json
import os
import re
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request

ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
OUT = os.path.join(ROOT, "data", "images.json")
ORG = "swarm-routing"
REGISTRY = "ghcr.io"
GH = "https://github.com/swarm-routing"
RAW = "https://raw.githubusercontent.com/swarm-routing"
IMAGE_BUILD = f"{GH}/.github/blob/main/.github/workflows/reusable-ns3-image.yml"

# The packages the page lists, in its order: name, the repository that
# builds it, how its versions read (the ns-3 release the pipeline supports
# vs older ones built on demand, sim-containers golden rule 16; or a
# repository's releases), and the guide to choosing a tag.
PACKAGES = [
    {"name": "ns3-dev", "repo": "sim-containers", "versions": "ns-3",
     "guide": ["Which image", f"{GH}/sim-containers#which-image"]},
    {"name": "ns3-tools", "repo": "sim-tools", "versions": "release",
     "guide": ["How release images are built", IMAGE_BUILD]},
    {"name": "swarm-adapter-ns3", "repo": "swarm-adapter-ns3", "versions": "release",
     "guide": ["How release images are built", IMAGE_BUILD]},
    {"name": "anthocnet", "repo": "AntHocNet", "versions": "release",
     "guide": ["Container images", f"{GH}/AntHocNet/blob/main/docker/README.md"]},
    {"name": "ci-tools", "repo": ".github", "versions": "build",
     "guide": ["The image rule (ADR-0002)", f"{GH}/.github/blob/main/docs/adr/0002-pipelines-are-go.md#the-image-rule"]},
]
# Public org packages the page does not list, and why (the page shows this list).
NOT_LISTED = [
    {"name": "ns3-dev-ci", "why": "sim-containers' candidates: each run's images, tested by digest before "
                                  "their tags are copied to ns3-dev; deleted daily"},
    {"name": "ns3-dev-cache", "why": "sim-containers' buildx cache, one scope per release, base and profile; "
                                     "not a runnable image"},
    {"name": "ns3-tools-dev", "why": "sim-tools' campaign images, one per plan and commit; deleted after two "
                                     "days unless a committed file pins one"},
    {"name": "anthocnet-dev", "why": "AntHocNet's per-commit benchmark images"},
    {"name": "anthocnet-ns3-campaign", "why": "AntHocNet's campaign images, one per plan and commit"},
    {"name": "ns3-tools-ns3-campaign", "why": "frozen: the campaign image's name before ns3-tools-dev"},
    {"name": "ci-tools-dev", "why": "swarm-routing/.github's pull-request and merge-queue builds of ci-tools"},
    {"name": "ns3-swarm-core", "why": "frozen: swarm-adapter-ns3's images under the repository's old name "
                                      "(up to v1.0.0); still pullable, never rebuilt"},
    {"name": "ns3-tools-ns3", "why": "frozen: ns3-tools' first image name (v0.1.0); still pullable, never rebuilt"},
    {"name": "anthocnet-ns3", "why": "frozen: AntHocNet's images from before the org (ns-3 3.36 to 3.48); "
                                     "still pullable, never rebuilt"},
]
INDEX = ("application/vnd.oci.image.index.v1+json", "application/vnd.docker.distribution.manifest.list.v2+json")
IMAGE = ("application/vnd.oci.image.manifest.v1+json", "application/vnd.docker.distribution.manifest.v2+json")
PIN = re.compile(r"(?:^|-)(?:sha-)?[0-9a-f]{7}$")
VERSION = re.compile(r"^v?\d+(?:\.\d+)+")
PROFILES = ["default", "debug", "sanitized", "optimized"]
BASES = ["ubuntu", "debian", "slim", "alpine"]
L = "org.opencontainers.image."
NS3 = "io.github.swarm-routing.ns3."
FROM = "io.github.swarm-routing.ns3-dev.digest"


class Registry:
    """The anonymous registry API: get(name, path) -> (headers, body)."""

    def __init__(self) -> None:
        self.tokens: dict[str, str] = {}

    def _open(self, url: str, headers: dict):
        req = urllib.request.Request(url, headers={"User-Agent": "images-data", **headers})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return {k.lower(): v for k, v in r.headers.items()}, r.read()
        except (urllib.error.URLError, OSError, ValueError) as e:
            raise SystemExit(f"images_data.py: GET {url}: {e}; nothing written") from None

    def get(self, name: str, path: str):
        if name not in self.tokens:
            _, body = self._open(f"https://{REGISTRY}/token?scope=repository:{ORG}/{name}:pull", {})
            try:
                self.tokens[name] = json.loads(body)["token"]
            except (ValueError, KeyError):
                raise SystemExit(f"images_data.py: no pull token for {ORG}/{name}; nothing written") from None
        accept = ",".join(INDEX + IMAGE) if path.startswith("manifests/") else "*/*"
        return self._open(f"https://{REGISTRY}/v2/{ORG}/{name}/{path}",
                          {"Authorization": f"Bearer {self.tokens[name]}", "Accept": accept})


def as_json(name: str, path: str, body: bytes):
    try:
        return json.loads(body)
    except ValueError:
        raise SystemExit(f"images_data.py: {name} {path}: not JSON; nothing written") from None


def all_tags(get, name: str) -> list[str]:
    tags, path = [], "tags/list?n=1000"
    while path:
        headers, body = get(name, path)
        tags += as_json(name, path, body).get("tags") or []
        m = re.search(r"<([^>]+)>;\s*rel=\"?next\"?", headers.get("link", ""))
        path = None
        if m:
            nxt = urllib.parse.urlsplit(m.group(1))
            path = nxt.path.split(f"/{name}/", 1)[-1] + (f"?{nxt.query}" if nxt.query else "")
    return tags


def readme_paragraph(text: str) -> str:
    """The README's first paragraph of prose: after the title and the badges,
    markdown links and emphasis reduced to their text."""
    text = re.sub(r"<!--.*?-->", "", text, flags=re.DOTALL)
    for para in re.split(r"\n\s*\n", text):
        p = para.strip()
        if not p or p.startswith(("#", "|", "[!", "![", "<", "```", ">")):
            continue
        p = re.sub(r"!?\[([^\]]*)\]\([^)]*\)", r"\1", p)
        p = re.sub(r"(\*\*|__|\*|`)", "", p)
        return " ".join(p.split())
    return ""


def fetch_readme(repo: str) -> str:
    url = f"{RAW}/{repo}/main/README.md"
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "images-data"}), timeout=30) as r:
            return r.read().decode("utf-8", "replace")
    except (urllib.error.URLError, OSError, ValueError) as e:
        raise SystemExit(f"images_data.py: GET {url}: {e}; nothing written") from None


def image_of(get, name: str, digest: str) -> dict:
    """One image (by digest): its annotations, labels, creation day and size."""
    _, body = get(name, f"manifests/{digest}")
    m = as_json(name, digest, body)
    notes = dict(m.get("annotations") or {})
    if m.get("mediaType") in INDEX or "manifests" in m:
        amd = [x for x in m.get("manifests", []) if (x.get("platform") or {}).get("os") == "linux"
               and (x.get("platform") or {}).get("architecture") == "amd64"]
        if not amd:
            raise SystemExit(f"images_data.py: {name}@{digest}: no linux/amd64 image; nothing written")
        _, body = get(name, f"manifests/{amd[0]['digest']}")
        m = as_json(name, amd[0]["digest"], body)
        notes = {**(m.get("annotations") or {}), **notes}  # the index's annotations win
    if "config" not in m or "layers" not in m:
        raise SystemExit(f"images_data.py: {name}@{digest}: not an image manifest; nothing written")
    _, body = get(name, f"blobs/{m['config']['digest']}")
    cfg = as_json(name, "config", body)
    labels = (cfg.get("config") or {}).get("Labels") or {}
    return {"labels": labels, "notes": notes, "created": (cfg.get("created") or "")[:10] or None,
            "size": sum(int(x.get("size", 0)) for x in m["layers"])}


def word(tag: str, words: list[str]) -> str | None:
    parts = tag.split("-")
    return next((w for w in words if w in parts), None)


def row_of(pkg: dict, digest: str, tags: list[str], img: dict, alltags: set[str]) -> dict:
    rolling = sorted(t for t in tags if t == "latest" or t.startswith("latest-"))
    named = sorted((t for t in tags if t not in rolling), key=lambda t: (len(t), t))
    lab, notes = img["labels"], img["notes"]
    canon = named[0] if named else (rolling[0] if rolling else digest)
    m = VERSION.match(canon) or VERSION.match(lab.get(L + "version", ""))
    rev = (lab.get(L + "revision") or "")[:7]
    roots = named or ["sha"]
    pins = sorted((f"{t}-{rev}" for t in roots if rev and f"{t}-{rev}" in alltags), key=lambda t: (-len(t), t))
    # earlier builds of this image: the distinct commits its tags were pinned at, this one's aside
    older = {t[-7:] for t in alltags if PIN.search(t) and t[-7:] != rev
             and any(t.startswith(r + "-") and PIN.fullmatch(t[len(r):]) for r in roots)}
    return {
        "digest": digest, "tags": named, "rolling": rolling, "pin": pins[0] if pins else None, "olderPins": len(older),
        "version": m.group(0) if m else None,
        "profile": lab.get(NS3 + "profile") or word(canon, PROFILES),
        "base": lab.get(NS3 + "base") or word(canon, BASES),
        "title": notes.get(L + "title") or lab.get(L + "title"),
        "description": notes.get(L + "description") or lab.get(L + "description"),
        "revision": lab.get(L + "revision") or None, "from": lab.get(FROM) or None,
        "created": img["created"], "size": img["size"]}


def vkey(v: str | None):
    return [int(x) for x in re.findall(r"\d+", v or "")]


def ordered(rows: list[dict]) -> list[dict]:
    """Newest release first (3.49 above 3.9, v1.0.1 above v1.0), then base and profile in their order."""
    def within(r):
        base = BASES.index(r["base"]) if r["base"] in BASES else len(BASES)
        prof = PROFILES.index(r["profile"]) if r["profile"] in PROFILES else len(PROFILES)
        return (base, r["base"] or "", prof, r["profile"] or "", r["digest"])
    return sorted(sorted(rows, key=within), key=lambda r: vkey(r["version"]), reverse=True)  # stable


def collect_package(pkg: dict, get, readme=fetch_readme) -> dict:
    name = pkg["name"]
    alltags = all_tags(get, name)
    tagset = set(alltags)
    by_digest: dict[str, list[str]] = {}
    for t in sorted(alltags):
        if t.startswith("sha256-") or PIN.search(t):
            continue
        headers, _ = get(name, f"manifests/{t}")
        d = headers.get("docker-content-digest")
        if not d or not d.startswith("sha256:"):
            raise SystemExit(f"images_data.py: {name}:{t}: no digest; nothing written")
        by_digest.setdefault(d, []).append(t)
    if not by_digest:
        raise SystemExit(f"images_data.py: {name}: no tag to list; nothing written")
    rows = ordered([row_of(pkg, d, ts, image_of(get, name, d), tagset) for d, ts in by_digest.items()])
    newest = next((r for r in rows if "latest" in r["rolling"]), None) or next((r for r in rows if r["rolling"]), rows[0])
    about, source = newest["description"], "label"
    if not about:
        about, source = readme_paragraph(readme(pkg["repo"])), "readme"
    return {"name": name, "image": f"{REGISTRY}/{ORG}/{name}", "repo": pkg["repo"], "versions": pkg["versions"],
            "guide": pkg["guide"], "package": f"{GH}/{pkg['repo']}/pkgs/container/{name}",
            "about": about or None, "aboutFrom": source if about else None,
            "current": newest["version"], "images": rows}


def collect(get, readme=fetch_readme) -> list[dict]:
    return [collect_package(p, get, readme) for p in PACKAGES]


def render(packages: list[dict], as_of: str) -> str:
    doc = {"asOf": as_of, "registry": REGISTRY, "org": ORG, "packages": packages, "notListed": NOT_LISTED,
           "note": "Generated by tools/images_data.py from the ghcr.io registry API (anonymous pulls: tags, "
                   "manifests, image labels); never edit by hand."}
    return json.dumps(doc, indent=1, sort_keys=True, ensure_ascii=False) + "\n"


def refresh(out: str, as_of: str, check: bool, get=None, readme=fetch_readme) -> int:
    packages = collect(get or Registry().get, readme)  # raises before anything is written
    old = None
    if os.path.exists(out):
        with open(out, encoding="utf-8") as f:
            try:
                old = json.load(f)
            except ValueError:
                old = None
    what = f"{len(packages)} packages, {sum(len(p['images']) for p in packages)} images"
    if old is not None and old.get("packages") == packages and old.get("notListed") == NOT_LISTED:
        print(f"images_data.py: {out}: up to date ({what}; unchanged since {old.get('asOf')})")
        return 0
    if check:
        print(f"images_data.py: {out}: stale (run tools/images_data.py to refresh)")
        return 1
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    tmp = out + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(render(packages, as_of))
    os.replace(tmp, out)
    print(f"images_data.py: {out}: written ({what}, as of {as_of})")
    return 0


# --- self-test -----------------------------------------------------------------


def self_test() -> None:  # noqa: C901 (one scenario, checked step by step)
    global PACKAGES
    D = {k: "sha256:" + k * 64 for k in "abcdef0129"}

    def index(img):
        return {"mediaType": INDEX[0], "manifests": [
            {"digest": img, "platform": {"os": "linux", "architecture": "amd64"}},
            {"digest": D["9"], "platform": {"os": "unknown", "architecture": "unknown"}}],
            "annotations": {L + "description": "from the index"}}

    def image(cfg, *sizes):
        return {"mediaType": IMAGE[0], "config": {"digest": cfg}, "layers": [{"size": s} for s in sizes]}

    def config(created, **labels):
        return {"created": created, "config": {"Labels": {k.replace("_", "."): v for k, v in labels.items()}}}

    tags = {
        "dev": ["3.49", "3.49-default", "3.49-debug", "3.49-debug-abc1234", "3.49-debug-0000000", "3.49-debug-1111111",
                "3.49-slim-debug", "latest", "latest-debug", "latest-slim-debug", "sha256-" + "f" * 64,
                "3.48-debug", "3.48-debug-2222222", "3.9-debug"],
        "tools": ["v1.0.0-debug", "v1.1.0-debug", "latest-debug", "latest"],
        "ci": ["latest", "sha-abc1234", "sha-0000000"],
    }
    digests = {("dev", "3.49"): D["a"], ("dev", "3.49-default"): D["a"], ("dev", "latest"): D["a"],
               ("dev", "3.49-debug"): D["b"], ("dev", "latest-debug"): D["b"],
               ("dev", "3.49-slim-debug"): D["c"], ("dev", "latest-slim-debug"): D["c"],
               ("dev", "3.48-debug"): D["d"], ("dev", "3.9-debug"): D["e"],
               ("tools", "v1.0.0-debug"): D["d"], ("tools", "v1.1.0-debug"): D["e"],
               ("tools", "latest-debug"): D["e"], ("tools", "latest"): D["e"], ("ci", "latest"): D["f"]}
    blobs = {
        ("dev", D["a"]): index("sha256:ia"), ("dev", "sha256:ia"): image("sha256:ca", 100, 23),
        ("dev", "sha256:ca"): config("2026-11-23T03:54:51Z", **{L + "version": "3.49", NS3 + "profile": "default",
                                     NS3 + "base": "ubuntu", L + "description": "ns-3 with a warm build"}),
        ("dev", D["b"]): image("sha256:cb", 200),
        ("dev", "sha256:cb"): config("2026-11-23T04:00:00Z", **{L + "version": "3.49", NS3 + "profile": "debug",
                                     NS3 + "base": "ubuntu", L + "revision": "abc1234" + "0" * 33,
                                     L + "title": "ns3-dev debug"}),
        ("dev", D["c"]): image("sha256:cc", 50),
        ("dev", "sha256:cc"): config("2026-11-22T00:00:00Z"),  # no labels: the tag says it
        ("dev", D["d"]): image("sha256:cd", 7), ("dev", "sha256:cd"): config("2026-11-01T00:00:00Z"),
        ("dev", D["e"]): image("sha256:ce", 8), ("dev", "sha256:ce"): config(None),
        ("tools", D["d"]): image("sha256:td", 1), ("tools", "sha256:td"): config("2026-11-10T00:00:00Z"),
        ("tools", D["e"]): image("sha256:te", 2), ("tools", "sha256:te"): config("2026-11-20T00:00:00Z", **{
            NS3 + "profile": "debug", FROM: D["b"], L + "version": "v1.1.0-debug"}),
        ("ci", D["f"]): image("sha256:cf", 3),
        ("ci", "sha256:cf"): config("2026-11-23T00:00:00Z", **{L + "revision": "abc1234def"}),
    }
    asked = []

    def fake(name, path):
        asked.append((name, path))
        if path.startswith("tags/list"):
            t = tags[name]
            if name == "dev" and "last=" not in path:  # two pages, as the registry's Link header gives them
                return {"link": f'</v2/{ORG}/{name}/tags/list?n=1000&last={t[7]}>; rel="next"'}, json.dumps(
                    {"tags": t[:8]}).encode()
            return {}, json.dumps({"tags": t[8:] if name == "dev" else t}).encode()
        ref = path.split("/", 1)[1]
        if (name, ref) in digests:
            return {"docker-content-digest": digests[(name, ref)]}, b"{}"
        key = (name, ref)
        if key not in blobs:
            raise SystemExit(f"images_data.py: GET {name}/{path}: HTTP 404; nothing written")
        return {}, json.dumps(blobs[key]).encode()

    readmes = {"r-dev": "# x\n\n<!-- org-sync:begin badges -->\n| a | b |\n<!-- org-sync:end badges -->\n\n"
                        "Pre-built **ns-3** images: [`ghcr.io/x`](https://x) (public).\nSecond line.\n\n## Next\n",
               "r-tools": "# t\n\nTools.\n", "r-ci": ""}
    saved = PACKAGES
    PACKAGES = [{"name": "dev", "repo": "r-dev", "versions": "ns-3", "guide": ["Which", "u"]},
                {"name": "tools", "repo": "r-tools", "versions": "release", "guide": ["G", "v"]},
                {"name": "ci", "repo": "r-ci", "versions": "build", "guide": ["H", "w"]}]
    try:
        with tempfile.TemporaryDirectory() as d:
            out = os.path.join(d, "data", "images.json")
            assert refresh(out, "2026-11-24", False, fake, readmes.__getitem__) == 0
            with open(out, encoding="utf-8") as f:
                text = f.read()
            got = json.loads(text)
            assert got["asOf"] == "2026-11-24" and [p["name"] for p in got["packages"]] == ["dev", "tools", "ci"], got
            dev, tools, ci = got["packages"]
            # signatures and pins are never asked for; each rolling tag once; each image's blobs once
            manifests = [(n, p) for n, p in asked if p.startswith("manifests/")]
            assert not any("sha256-" in p or "abc1234" in p or "0000000" in p for _, p in manifests), manifests
            assert len(manifests) == len(set(manifests)), manifests
            # one row per digest, newest release first, then base, then profile; 3.49 sorts above 3.9
            assert [r["tags"] for r in dev["images"]] == [
                ["3.49", "3.49-default"], ["3.49-debug"], ["3.49-slim-debug"], ["3.48-debug"], ["3.9-debug"]], dev["images"]
            a, b, c, dd, e = dev["images"]
            assert a["rolling"] == ["latest"] and b["rolling"] == ["latest-debug"] and dd["rolling"] == [], dev
            assert dev["current"] == "3.49" and dev["about"] == "from the index" and dev["aboutFrom"] == "label"
            assert a["size"] == 123 and a["created"] == "2026-11-23" and a["description"] == "from the index", a
            assert (a["profile"], a["base"]) == ("default", "ubuntu") and a["pin"] is None, a
            # the pin is the tag plus the revision's seven characters; the other pins of that tag are counted
            assert b["pin"] == "3.49-debug-abc1234" and b["olderPins"] == 2 and b["title"] == "ns3-dev debug", b
            assert (c["profile"], c["base"], c["version"]) == ("debug", "slim", "3.49"), c  # read from the tag
            assert dd["olderPins"] == 1 and dd["pin"] is None and e["created"] is None, (dd, e)
            assert tools["current"] == "v1.1.0" and [r["version"] for r in tools["images"]] == ["v1.1.0", "v1.0.0"], tools
            assert tools["images"][0]["from"] == D["b"] and tools["images"][0]["rolling"] == ["latest", "latest-debug"]
            # no description label on the newest image: the README's first paragraph
            assert (tools["about"], tools["aboutFrom"]) == ("Tools.", "readme"), tools
            assert ci["images"][0]["tags"] == [] and ci["images"][0]["pin"] == "sha-abc1234", ci
            assert ci["images"][0]["olderPins"] == 1 and ci["current"] is None, ci
            assert got["notListed"] == NOT_LISTED and got["packages"][0]["package"].endswith("/r-dev/pkgs/container/dev")
            assert not re.search(r"\d\dT\d\d:\d\d", text), "a timestamp in the data file"
            # Another day, the same registry: the file and its date stay; --check agrees.
            assert refresh(out, "2026-11-25", False, fake, readmes.__getitem__) == 0
            with open(out, encoding="utf-8") as f:
                assert f.read() == text
            assert refresh(out, "2026-11-25", True, fake, readmes.__getitem__) == 0
            # A rolling tag moves: --check reports it and writes nothing; a run writes it with the new date.
            digests[("dev", "latest-debug")] = D["d"]
            assert refresh(out, "2026-11-25", True, fake, readmes.__getitem__) == 1
            with open(out, encoding="utf-8") as f:
                assert f.read() == text
            assert refresh(out, "2026-11-25", False, fake, readmes.__getitem__) == 0
            with open(out, encoding="utf-8") as f:
                new = json.load(f)
            assert new["asOf"] == "2026-11-25" and new["packages"][0]["images"][3]["rolling"] == ["latest-debug"], new
            with open(out, encoding="utf-8") as f:
                before = f.read()
            # A failed request (a blob gone) leaves the file as it was, and creates none where there was none.
            del blobs[("ci", "sha256:cf")]
            for target in (out, os.path.join(d, "none", "images.json")):
                try:
                    refresh(target, "2026-11-26", False, fake, readmes.__getitem__)
                    raise AssertionError("a failed request did not stop the run")
                except SystemExit as e:
                    assert "nothing written" in str(e), e
            with open(out, encoding="utf-8") as f:
                assert f.read() == before
            assert not os.path.exists(os.path.join(d, "none")) and not os.path.exists(out + ".tmp")
            # An image without a linux/amd64 build is refused.
            blobs[("ci", "sha256:cf")] = config("2026-11-23T00:00:00Z")
            blobs[("dev", D["a"])]["manifests"].pop(0)
            try:
                refresh(out, "2026-11-26", False, fake, readmes.__getitem__)
                raise AssertionError("an index without linux/amd64 was accepted")
            except SystemExit as e:
                assert "linux/amd64" in str(e), e
            blobs[("dev", D["a"])] = index("sha256:ia")
            # No description anywhere: the README's first paragraph, its markdown reduced to text.
            blobs[("dev", "sha256:ca")]["config"]["Labels"].pop(L + "description")
            digests[("dev", "latest")] = D["c"]  # the newest image has no label either
            blobs[("dev", D["a"])]["annotations"] = {}
            pkg = collect_package(PACKAGES[0], fake, readmes.__getitem__)
            assert pkg["about"] == "Pre-built ns-3 images: ghcr.io/x (public). Second line." and pkg["aboutFrom"] == "readme", pkg
    finally:
        PACKAGES = saved
    assert readme_paragraph("# t\n\n[![b](x)](y)\n\n") == ""
    # a version that prefixes another sorts below it; base and profile stay in their order
    rs = [{"version": v, "base": b, "profile": p, "digest": d} for v, b, p, d in (
        ("v1.0", "ubuntu", "debug", "1"), ("v1.0.1", "ubuntu", "optimized", "2"), ("v1.0.1", "ubuntu", "debug", "3"),
        ("v1.0.1", "alpine", "debug", "4"), (None, None, None, "5"))]
    assert [r["digest"] for r in ordered(rs)] == ["3", "2", "4", "1", "5"], ordered(rs)
    assert PIN.search("3.49-debug-fb7596b") and PIN.search("sha-8971dec") and not PIN.search("v1.1.0-debug")
    assert not PIN.search("3.49-default") and not PIN.search("latest-debug")
    assert len({p["name"] for p in PACKAGES} | {p["name"] for p in NOT_LISTED}) == len(PACKAGES) + len(NOT_LISTED)
    # The real fetcher turns a network failure into the same refusal.
    real, urllib.request.urlopen = urllib.request.urlopen, lambda *a, **k: (_ for _ in ()).throw(OSError("unreachable"))
    try:
        Registry().get("ns3-dev", "tags/list")
        raise AssertionError("Registry.get swallowed a failure")
    except SystemExit as e:
        assert "unreachable" in str(e) and "nothing written" in str(e), e
    finally:
        urllib.request.urlopen = real
    print("images_data.py self-test: ok")


def main(argv: list[str]) -> int:
    if argv == ["--self-test"]:
        self_test()
        return 0
    out, as_of, check = OUT, datetime.datetime.now(datetime.timezone.utc).date().isoformat(), False
    it = iter(argv)
    for a in it:
        if a == "--check":
            check = True
        elif a in ("--out", "--as-of"):
            v = next(it, None)
            if v is None:
                print(__doc__, file=sys.stderr)
                return 2
            if a == "--out":
                out = v
            else:
                as_of = v
        else:
            print(__doc__, file=sys.stderr)
            return 2
    if not re.match(r"^\d{4}-\d\d-\d\d$", as_of):
        print(f"images_data.py: --as-of {as_of!r} is not a YYYY-MM-DD date", file=sys.stderr)
        return 2
    return refresh(out, as_of, check)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
