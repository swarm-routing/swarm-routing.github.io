# Copyright (c) 2026 Daniel Joppi (https://github.com/swarm-routing)
# SPDX-License-Identifier: MIT OR GPL-2.0-only
# Vendored from swarm-routing/.github tools/fidelity/bib.py at cb02e3573cbf0589756852c28b5a41c376186d61
# (its stable API, unchanged); refresh by copying that file again.
"""BibTeX for docs/references.bib, each repository's one bibliography (#307, #308).

A reader and a deterministic writer for the subset the org writes; no LaTeX,
no macros. Stdlib only. fidelity.py (`bib check|entry|sources`) uses it, and
tools/org-sync does (CITATION.cff references, the README's citing section).

Accepted input:
  - entry types: @article, @inproceedings, @incollection, @book, @phdthesis,
    @mastersthesis, @techreport, @misc, @software (any case); @string,
    @preamble, @comment and every other type are refused
  - values in braces (nested braces kept as written) or double quotes, or a
    bare number (`year = 2002`); a bare word (a macro) or `#` is refused
  - `%` comment lines outside entries and between fields
  - keys are unique (case-insensitive, as BibTeX compares them); a field
    appears once per entry

Stable API (other tools import this module; extend, never break):

  ROLES                       the `keywords` values an entry may carry
  TYPES                       the entry types read and written
  BibError(message, line)     a malformed file; str() names the line
  parse(text) -> [entry]      entry = {"key", "type", "fields", "line"}: type
                              lower-case, field names lower-case, values with
                              the outer delimiter removed and whitespace runs
                              collapsed; "line" is where the entry starts
  load(path) -> [entry]       parse() of a file
  header(text) -> str         the leading `%` comment block of a file, verbatim
  format_entry(entry) -> str  one entry: fields in FIELD_ORDER, then the rest
                              sorted; every value braced; "line" is ignored
  format_file(entries, head="") -> str   head, then the entries sorted by key
  norm_doi(text) -> str       a DOI without its https://doi.org/ or doi: prefix
  doi_link(entry) -> str|None https://doi.org/<doi>, else the url, else None
  roles(entry) -> [str]       its `keywords`, split and lower-cased
  split_authors(value) -> [(family, given)]   "Family, Given and ..." or
                              "Given Family"; a {braced} name is one family name
  corporate(value) -> [bool]  per name of split_authors(value): True for a
                              {braced} whole name (an organization)
  plain(value) -> str         display text: braces dropped, \\& and friends unescaped
  citation(entry) -> str      a one-line Markdown citation (no link)
"""

import re

ROLES = ("implemented", "restates", "compared", "dataset", "tool", "background")
TYPES = (
    "article",
    "inproceedings",
    "incollection",
    "book",
    "phdthesis",
    "mastersthesis",
    "techreport",
    "misc",
    "software",
)
FIELD_ORDER = (
    "author",
    "editor",
    "title",
    "journal",
    "booktitle",
    "series",
    "volume",
    "number",
    "pages",
    "edition",
    "school",
    "institution",
    "organization",
    "publisher",
    "address",
    "month",
    "year",
    "version",
    "doi",
    "url",
    "note",
    "keywords",
)
KEY = re.compile(r"[A-Za-z][A-Za-z0-9_:.-]*")
NAME = re.compile(r"[A-Za-z][A-Za-z0-9_-]*")


class BibError(ValueError):
    def __init__(self, message, line):
        super().__init__(f"line {line}: {message}")
        self.message = message
        self.line = line


class _Reader:
    def __init__(self, text):
        self.s = text
        self.i = 0

    def line(self, i=None):
        return self.s.count("\n", 0, self.i if i is None else i) + 1

    def fail(self, msg, i=None):
        raise BibError(msg, self.line(i))

    def skip(self):
        """Whitespace and `%` comment lines."""
        while self.i < len(self.s):
            c = self.s[self.i]
            if c.isspace():
                self.i += 1
            elif c == "%":
                nl = self.s.find("\n", self.i)
                self.i = len(self.s) if nl < 0 else nl + 1
            else:
                return

    def peek(self):
        return self.s[self.i] if self.i < len(self.s) else ""

    def name(self, what):
        m = NAME.match(self.s, self.i) if what != "key" else KEY.match(self.s, self.i)
        if not m:
            self.fail(f"expected {what}")
        self.i = m.end()
        return m.group(0)

    def braced(self):
        start, depth = self.i, 0
        while self.i < len(self.s):
            c = self.s[self.i]
            if c == "\\":
                self.i += 2
                continue
            if c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    self.i += 1
                    return self.s[start + 1 : self.i - 1]
            self.i += 1
        self.fail("unbalanced braces: a value opened here is never closed", start)

    def quoted(self):
        start, depth = self.i, 0
        self.i += 1
        while self.i < len(self.s):
            c = self.s[self.i]
            if c == "\\":
                self.i += 2
                continue
            if c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth < 0:
                    self.fail("unbalanced braces in a quoted value", start)
            elif c == '"' and depth == 0:
                self.i += 1
                return self.s[start + 1 : self.i - 1]
            self.i += 1
        self.fail("a quoted value opened here is never closed", start)

    def value(self):
        c = self.peek()
        if c == "{":
            raw = self.braced()
        elif c == '"':
            raw = self.quoted()
        elif c.isdigit():
            m = re.compile(r"\d+").match(self.s, self.i)
            self.i = m.end()
            raw = m.group(0)
        elif c:
            self.fail("a bare word is a @string macro, which is not supported: brace the value")
        else:
            self.fail("unexpected end of file in a value")
        self.skip()
        if self.peek() == "#":
            self.fail("`#` concatenation is not supported")
        return re.sub(r"\s+", " ", raw).strip()


def parse(text):
    r = _Reader(text)
    entries, seen = [], {}
    while True:
        r.skip()
        if r.i >= len(r.s):
            return entries
        if r.peek() != "@":
            r.fail("text outside an entry (a comment line starts with %)")
        start = r.i
        r.i += 1
        kind = r.name("an entry type").lower()
        if kind not in TYPES:
            r.fail(f"@{kind} is not supported (one of {', '.join('@' + t for t in TYPES)})", start)
        r.skip()
        if r.peek() != "{":
            r.fail(f"expected {{ after @{kind}")
        r.i += 1
        r.skip()
        key = r.name("key")
        low = key.lower()
        if low in seen:
            r.fail(f"duplicate key {key} (first at line {seen[low]})", start)
        seen[low] = r.line(start)
        r.skip()
        fields = {}
        while True:
            c = r.peek()
            if c == "}":
                r.i += 1
                break
            if c != ",":
                r.fail(f"{key}: expected , or }} after a field")
            r.i += 1
            r.skip()
            if r.peek() == "}":
                r.i += 1
                break
            at = r.i
            field = r.name("a field name").lower()
            r.skip()
            if r.peek() != "=":
                r.fail(f"{key}: expected = after {field}")
            r.i += 1
            r.skip()
            if field in fields:
                r.fail(f"{key}: field {field} given twice", at)
            fields[field] = r.value()
        entries.append({"key": key, "type": kind, "fields": fields, "line": r.line(start)})


def load(path):
    with open(path, encoding="utf-8") as fh:
        return parse(fh.read())


def header(text):
    out = []
    for line in text.splitlines(keepends=True):
        if not line.lstrip().startswith("%"):
            break
        out.append(line)
    return "".join(out)


def format_entry(entry):
    fields = entry["fields"]
    names = [f for f in FIELD_ORDER if f in fields]
    names += sorted(f for f in fields if f not in FIELD_ORDER)
    width = max((len(n) for n in names), default=0)
    lines = [f"@{entry['type']}{{{entry['key']},"]
    for i, n in enumerate(names):
        comma = "," if i < len(names) - 1 else ""
        lines.append(f"  {n.ljust(width)} = {{{fields[n]}}}{comma}")
    lines.append("}")
    return "\n".join(lines) + "\n"


def format_file(entries, head=""):
    body = "\n".join(format_entry(e) for e in sorted(entries, key=lambda e: e["key"].lower()))
    if head and not head.endswith("\n"):
        head += "\n"
    return head + body


def norm_doi(text):
    d = (text or "").strip()
    d = re.sub(r"^(https?://(dx\.)?doi\.org/|doi:\s*)", "", d, flags=re.I)
    return d


def doi_link(entry):
    f = entry["fields"]
    if norm_doi(f.get("doi")):
        return "https://doi.org/" + norm_doi(f["doi"])
    return f.get("url") or None


def roles(entry):
    raw = entry["fields"].get("keywords", "")
    return [k.strip().lower() for k in re.split(r"[,;]", plain(raw)) if k.strip()]


def _split_top(value, sep):
    """Split at sep (a regex) only where brace depth is 0."""
    parts, depth, last = [], 0, 0
    pat = re.compile(sep)
    i = 0
    while i < len(value):
        c = value[i]
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
        elif depth == 0:
            m = pat.match(value, i)
            if m:
                parts.append(value[last:i])
                i = last = m.end()
                continue
        i += 1
    parts.append(value[last:])
    return [p.strip() for p in parts]


def split_authors(value):
    out = []
    for name in _split_top(value or "", r"\s+and\s+"):
        if not name:
            continue
        if name.startswith("{") and name.endswith("}") and len(_split_top(name, ",")) == 1:
            out.append((plain(name), ""))
            continue
        parts = _split_top(name, ",")
        if len(parts) >= 2:
            out.append((plain(parts[0]), plain(" ".join(parts[1:]))))
            continue
        words = _split_top(name, r"\s+")
        out.append((plain(words[-1]), plain(" ".join(words[:-1]))))
    return out


def corporate(value):
    return [
        n.startswith("{") and n.endswith("}") and len(_split_top(n, ",")) == 1
        for n in _split_top(value or "", r"\s+and\s+")
        if n
    ]


def plain(value):
    s = re.sub(r"\\([&%$#_{}])", r"\1", value or "")
    s = s.replace("{", "").replace("}", "").replace("~", " ")
    return re.sub(r"\s+", " ", s).strip()


def citation(entry):
    f = entry["fields"]
    families = [fam for fam, _ in split_authors(f.get("author", ""))]
    if len(families) > 3:
        who = f"{families[0]} et al."
    elif len(families) > 1:
        who = ", ".join(families[:-1]) + " & " + families[-1]
    else:
        who = families[0] if families else ""
    kind = entry["type"]
    venue = f.get("journal") or f.get("booktitle") or ""
    if kind == "phdthesis":
        venue = "PhD thesis, " + f.get("school", "")
    elif kind == "mastersthesis":
        venue = "Master's thesis, " + f.get("school", "")
    elif kind == "techreport":
        venue = "Technical report, " + f.get("institution", "")
    elif not venue:
        venue = f.get("publisher") or f.get("howpublished") or ""
    venue = plain(venue).strip(", ")
    if f.get("volume") and kind == "article":
        venue += f" {plain(f['volume'])}" + (f"({plain(f['number'])})" if f.get("number") else "")
    if kind == "software" and f.get("version"):
        venue = f"version {plain(f['version'])}" + (f", {venue}" if venue else "")
    parts = [who, f"*{plain(f.get('title', ''))}*", venue, plain(f.get("year", ""))]
    if f.get("pages"):
        pages = plain(f["pages"]).replace("--", "–").replace("-", "–")
        parts.append(("pp. " if "–" in pages else "p. ") + pages)
    return ", ".join(p for p in parts if p and p != "**")
