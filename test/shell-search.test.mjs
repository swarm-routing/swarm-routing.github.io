// Copyright (c) 2026 Daniel Joppi (https://github.com/swarm-routing)
// SPDX-License-Identifier: GPL-2.0-only
// The top bar's search (site/anthocnet/shell/shell.js) reads mkdocs' index,
// which holds HTML and escaped HTML. Its titles and snippets are decoded in
// script, never by handing text to the DOM as HTML (CodeQL js/xss-through-dom,
// #247): this runs search() in Node with a document that has no
// createElement and no innerHTML, and checks what it returns.
//   1. '&amp;lt;' in a code block decodes in two passes, '&gt;', '&amp;' and
//      numeric entities decode; tags, decoded ones included, are dropped;
//   2. markup inside an entity-escaped title is dropped, never parsed;
//   3. an unknown entity and an out-of-range number are left as written.
// Usage: node test/shell-search.test.mjs
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const repo = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
// No createElement, no innerHTML: a decoder that needs the DOM fails here.
globalThis.document = { readyState: 'loading', addEventListener() {} };
const docs = [
  { location: 'a/', title: 'Codec &amp;lt;wire&amp;gt;', text: '<p>Use <code>&amp;lt;b&amp;gt; &lt;i&gt;</code> &amp; more &#39;q&#39; &#x2192; end</p>' },
  { location: 'b/', title: '&lt;img src=x onerror=alert(1)&gt; trap', text: '<p>trap &bogus; &#99999999; tail</p>' },
];
globalThis.fetch = async () => ({ json: async () => ({ docs }) });
const { search } = await import(pathToFileURL(path.join(repo, 'site/anthocnet/shell/shell.js')).href);

let failed = 0;
const check = (name, got, want) => {
  const ok = got === want;
  if (!ok) failed++;
  console.log(`${ok ? 'ok  ' : 'FAIL'} ${name}${ok ? '' : `: got ${JSON.stringify(got)}, want ${JSON.stringify(want)}`}`);
};

const [a] = await search('./', 'codec');
check('title: double-escaped markup decodes, then drops as a tag', a?.title, 'Codec');
check('snippet: entities decode, tags dropped', a?.snippet, 'Use & more \'q\' → end');
const [b] = await search('./', 'trap');
check('title: escaped markup is dropped', b?.title, 'trap');
check('snippet: unknown and out-of-range entities stay as written', b?.snippet, 'trap &bogus; &#99999999; tail');
if (failed) { console.error(`${failed} check(s) failed`); process.exit(1); }
console.log('shell search: every check passed');
