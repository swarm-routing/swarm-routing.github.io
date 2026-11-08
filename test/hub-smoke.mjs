// Copyright (c) 2026 Daniel Joppi (https://github.com/swarm-routing)
// SPDX-License-Identifier: GPL-2.0-only
// Browser smoke for the Colony Arena's own pages (the hub, the pipeline page and
// every project space; AntHocNet's pages have site/anthocnet/test/smoke.mjs). Serves the
// assembled site at / and, in headless Chromium:
//   1. opens the hub, /pipeline/ and every /arena/<id>/ page in day and night, requires no
//      console error and no uncaught exception, and runs axe-core: a serious
//      or critical violation fails;
//   2. checks the colony map has one place per project plus the arena, and
//      that focusing a place by keyboard fills the map card;
//   3. checks the day/night switch flips the theme and the hub has no
//      horizontal scroll at 320 px.
// Usage: node test/hub-smoke.mjs <assembled-site-root>   (tools/build-site.sh's output)
// Env:   CHROMIUM=/path/to/chrome (default: Playwright's own)
// Needs: playwright-core and axe-core resolvable from the working directory
//        (CI installs them from site/anthocnet/test/browser-tools' lockfile).
import http from 'node:http';
import fs from 'node:fs';
import path from 'node:path';
import { createRequire } from 'node:module';

const require = createRequire(path.join(process.cwd(), 'x.js'));
const { chromium } = require('playwright-core');
const AXE = fs.readFileSync(require.resolve('axe-core/axe.min.js'), 'utf8');
const ROOT = path.resolve(process.argv[2] || 'build/site');
const projects = JSON.parse(fs.readFileSync(new URL('../site/hub/projects.json', import.meta.url))).projects;
const TYPES = { '.html': 'text/html', '.css': 'text/css', '.js': 'text/javascript', '.json': 'application/json',
  '.svg': 'image/svg+xml', '.png': 'image/png', '.wasm': 'application/wasm', '.webmanifest': 'application/manifest+json' };

const srv = http.createServer((req, res) => {
  let f = path.join(ROOT, decodeURIComponent(req.url.split('?')[0]));
  if (!f.startsWith(ROOT)) { res.writeHead(403); return res.end(); }
  if (fs.existsSync(f) && fs.statSync(f).isDirectory()) f = path.join(f, 'index.html');
  if (!fs.existsSync(f)) {
    res.writeHead(404, { 'content-type': 'text/html' });
    return res.end(fs.existsSync(path.join(ROOT, '404.html')) ? fs.readFileSync(path.join(ROOT, '404.html')) : 'not found');
  }
  res.writeHead(200, { 'content-type': TYPES[path.extname(f)] || 'application/octet-stream' });
  fs.createReadStream(f).pipe(res);
}).listen(0);
const base = `http://127.0.0.1:${srv.address().port}/`;

let failed = 0;
const fail = (m) => { failed++; console.log(`FAIL: ${m}`); };
const browser = await chromium.launch(process.env.CHROMIUM ? { executablePath: process.env.CHROMIUM } : {});

async function open(url, scheme, viewport = { width: 1280, height: 900 }) {
  const page = await browser.newPage({ colorScheme: scheme, viewport });
  const errors = [];
  page.on('pageerror', (e) => errors.push(`exception: ${e.message}`));
  page.on('console', (m) => { if (m.type() === 'error' && !/favicon/.test(m.location().url || '')) errors.push(m.text()); });
  page.on('requestfailed', (r) => errors.push(`request failed: ${r.url()}`));
  page.on('response', (r) => { if (r.status() >= 400 && !/favicon/.test(r.url())) errors.push(`HTTP ${r.status()}: ${r.url()}`); });
  await page.goto(base + url, { waitUntil: 'load' });
  await page.waitForTimeout(300);
  return { page, errors };
}

async function axe(page) {
  await page.addScriptTag({ content: AXE });
  const r = await page.evaluate(async () => await window.axe.run(document, { resultTypes: ['violations'] }));
  return r.violations.filter((v) => v.impact === 'serious' || v.impact === 'critical');
}

const urls = ['', 'pipeline/'].concat(projects.map((p) => `arena/${p.id}/`));
for (const scheme of ['light', 'dark']) {
  for (const u of urls) {
    const { page, errors } = await open(u, scheme);
    const bad = await axe(page);
    for (const v of bad) fail(`${u || '/'} (${scheme}): axe ${v.impact} ${v.id}: ${v.help} [${v.nodes.slice(0, 3).map((n) => n.target.join(' ')).join(', ')}]`);
    for (const e of errors) fail(`${u || '/'} (${scheme}): ${e}`);
    if (!bad.length && !errors.length) console.log(`ok: ${u || '/'} (${scheme}) — axe clean, no errors`);
    await page.close();
  }
}

{
  const { page } = await open('', 'light');
  const n = await page.locator('.colony .place').count();
  if (n !== projects.length + 1) fail(`map: ${n} places, expected ${projects.length + 1}`);
  await page.locator('.colony .place').first().focus();
  const card = await page.locator('#map-card .mc-t').textContent();
  if (!card || card === 'Hover or tab through the colony.') fail(`map: focusing a place left the card at "${card}"`);
  const before = await page.evaluate(() => getComputedStyle(document.body).backgroundColor);
  await page.click('#theme');
  const after = await page.evaluate(() => getComputedStyle(document.body).backgroundColor);
  if (before === after) fail('theme: the day/night switch did not change the background');
  if (!failed) console.log(`ok: map — ${n} places, keyboard focus fills the card ("${card}"); theme switch flips`);
  await page.close();
}
for (const u of ['', 'pipeline/', 'arena/ns3-containers/']) {
  const { page } = await open(u, 'light', { width: 320, height: 720 });
  const over = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  if (over > 0) fail(`${u || '/'} at 320 px: ${over} px of horizontal page scroll`);
  else console.log(`ok: ${u || '/'} at 320 px — no horizontal page scroll`);
  await page.close();
}

await browser.close();
srv.close();
console.log(failed ? `hub smoke: FAIL (${failed})` : 'hub smoke: PASS');
process.exit(failed ? 1 : 0);
