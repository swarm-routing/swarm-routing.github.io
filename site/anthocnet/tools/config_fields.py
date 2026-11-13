#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
# Copyright (C) 2026 Daniel Henrique Joppi
"""Field metadata for the tuning bench (#638), generated so it cannot drift.

The browser adapter exposes a few Config fields (setConfig in
web/src/bindings.cpp). For each one this joins:

  * config_dump (core/tests/config_dump.cpp, AntHocNet#793) -- its default:
    the value the compiler evaluated for core::Config{}, printed as JSON, so
    an initialiser written as an expression, a constant or a conversion
    reads as the number it becomes, not as its source text;
  * core/include/anthocnet/core/config.h -- its doc comment only (the
    trailing `///<` brief, else the first sentence of the `///` block),
    which the compiler does not keep;
  * docs/configuration.md section 3.1 -- unit, ns-3 attribute and source,
    the source reduced to provenance badges (paper / measured / repo choice).

config_dump's output comes from $CONFIG_DUMP when it is set (the program, or
a file holding its JSON); otherwise the core is configured and config_dump
built in core/build-config-dump/ (git-ignored, incremental, so a changed
config.h is always rebuilt) and run. That needs cmake and a C++ compiler,
which every job running this script already has for the core.

Which attributes are TimeValues still comes from the ns-3 source
(time_attrs): it is a type, not a default, and the alternatives are a
hand-kept table that could drift, or --PrintAttributes, which needs an ns-3
build that the site build does not have.

Usage:
  config_fields.py json  [OUT]    write the bench's data (default: stdout)
  config_fields.py check          exit 1 if an exposed field lacks a doc
                                  comment, a table row or an ns-3 attribute
  config_fields.py ns3-args       print one --ns3::anthocnet::RoutingProtocol::
                                  <Attr>=<value> per field, each moved off its
                                  default the way the bench would write it, so
                                  CI can run them through anthocnet-compare
"""

import json
import os
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
BINDINGS = REPO / "web/src/bindings.cpp"
CONFIG_H = REPO / "core/include/anthocnet/core/config.h"
CONFIG_MD = REPO / "docs/configuration.md"
NS3_PROTOCOL = REPO / "ns3/anthocnet/model/anthocnet-routing-protocol.cc"
CORE = REPO / "core"
DUMP_BUILD = CORE / "build-config-dump"
PREFIX = "--ns3::anthocnet::RoutingProtocol::"


def time_attrs() -> set[str]:
    """ns-3 attributes declared with a TimeValue: their flags take "250ms".
    The rest of the seconds-valued fields (HopTime) are DoubleValues."""
    src = NS3_PROTOCOL.read_text(encoding="utf-8")
    out = set()
    for m in re.finditer(
        r'\.AddAttribute\(\s*"(\w+)"(.*?)(?=\.AddAttribute\(|\Z)', src, re.DOTALL
    ):
        if "TimeValue(" in m.group(2):
            out.add(m.group(1))
    return out


def exposed() -> list[str]:
    src = BINDINGS.read_text(encoding="utf-8")
    body = src[src.index("void setConfig(") : src.index("double getConfig(")]
    return re.findall(r'key == "(\w+)"', body)


def config_dump() -> dict:
    """core::Config{} as config_dump prints it: field -> compiled default."""
    given = os.environ.get("CONFIG_DUMP")
    if given:
        path = Path(given)
        if not os.access(path, os.X_OK):
            return json.loads(path.read_text(encoding="utf-8"))
        exe = str(path.resolve())
    else:
        for cmd in (
            [
                "cmake",
                "-S",
                str(CORE),
                "-B",
                str(DUMP_BUILD),
                "-DCMAKE_BUILD_TYPE=Release",
            ],
            ["cmake", "--build", str(DUMP_BUILD), "--target", "config_dump"],
        ):
            r = subprocess.run(cmd, capture_output=True, text=True, check=False)
            if r.returncode:
                sys.stderr.write(r.stdout + r.stderr)
                sys.exit(
                    f"config_fields.py: building config_dump failed: {' '.join(cmd)}"
                )
        exe = str(DUMP_BUILD / "tests" / "config_dump")
    return json.loads(
        subprocess.run([exe], capture_output=True, text=True, check=True).stdout
    )


def header_docs() -> dict[str, str]:
    """Each Config field's doc comment. Only the comments are read from
    config.h; the defaults come from config_dump."""
    out, block = {}, []
    for line in CONFIG_H.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if s.startswith("///") and not s.startswith("///<"):
            block.append(s[3:].strip())
            continue
        m = re.match(
            r"(?:bool|double|int|unsigned|uint\w+|std::size_t|size_t)\s+(\w+)\s*(?:=[^;]*|\{[^;]*\})?;\s*(?:///<\s*(.*))?$",
            s,
        )
        if m:
            brief = (m.group(2) or "").strip()
            if not brief and block:
                text = " ".join(x for x in block if x)
                brief = re.split(r"(?<=[.!?])\s", text, maxsplit=1)[0]
            out[m.group(1)] = brief
        block = [] if not s.startswith("///") else block
    return out


def table_rows() -> dict[str, dict]:
    md = CONFIG_MD.read_text(encoding="utf-8")
    sec = md[md.index("### 3.1") : md.index("### 3.2")]
    rows = {}
    for line in sec.splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 6 or not cells[0].startswith("`"):
            continue
        field = cells[0].strip("`")
        attr = cells[3].strip("`")
        rows[field] = {
            "unit": cells[2],
            "attr": attr if re.fullmatch(r"[A-Z]\w+", attr) else "",
            "source": cells[4],
        }
    return rows


def badges(source: str) -> list[str]:
    # The table's source cell leads with what the value rests on ("**Thesis
    # ...**", "`[1] §3.3`", "`repo choice` -- ...", "**`measured -- #248`**");
    # later text discusses it, and may cite a source to say it is *absent*.
    head = source[:48].lower()
    out = []
    if "thesis" in head or "[1]" in head:
        out.append("paper")
    if "measured" in head or "adopted on" in source.lower():
        out.append("measured")
    if "repo choice" in source[:160].lower():
        out.append("repo")
    return out or ["unrecorded"]


def build() -> tuple[list[dict], list[str]]:
    dump, docs, rows, timed = config_dump(), header_docs(), table_rows(), time_attrs()
    fields, errors = [], []
    for key in exposed():
        d, doc, r = dump.get(key), docs.get(key), rows.get(key)
        if d is None:
            errors.append(f"{key}: not a field in config_dump's output")
        if not doc:
            errors.append(f"{key}: no doc comment in config.h")
        if not r:
            errors.append(f"{key}: no row in docs/configuration.md section 3.1")
        elif not r["attr"]:
            errors.append(
                f"{key}: no ns-3 attribute in docs/configuration.md section 3.1"
            )
        if d is None or not doc or not r:
            continue
        kind = (
            "bool"
            if isinstance(d, bool)
            else "time"
            if r["attr"] in timed
            else "number"
        )
        default = d if kind == "bool" else float(d)
        fields.append(
            {
                "key": key,
                "attr": r["attr"],
                "kind": kind,
                "default": default,
                "unit": r["unit"],
                "doc": doc,
                "provenance": badges(r["source"]),
            }
        )
    return fields, errors


def ns3_value(f: dict, v) -> str:
    if f["kind"] == "bool":
        return "true" if v else "false"
    if f["kind"] == "time":
        return f"{round(v * 1000)}ms"
    return f"{v:g}"


def main() -> int:
    mode = sys.argv[1] if len(sys.argv) > 1 else "json"
    fields, errors = build()
    if mode == "check":
        for e in errors:
            print("FAIL " + e)
        if not errors:
            print(
                f"ok: {len(fields)} exposed Config fields each have a doc comment, a table row and an ns-3 attribute"
            )
        return 1 if errors else 0
    if errors:
        print("\n".join(errors), file=sys.stderr)
        return 1
    if mode == "ns3-args":
        moved = {
            "bool": lambda d: not d,
            "time": lambda d: d * 2,
            "number": lambda d: d / 2,
        }
        print(
            " ".join(
                f"{PREFIX}{f['attr']}={ns3_value(f, moved[f['kind']](f['default']))}"
                for f in fields
            )
        )
        return 0
    text = (
        json.dumps({"prefix": PREFIX, "fields": fields}, indent=1, ensure_ascii=False)
        + "\n"
    )
    if len(sys.argv) > 2:
        Path(sys.argv[2]).write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
