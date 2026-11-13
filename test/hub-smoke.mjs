// Copyright (c) 2026 Daniel Joppi (https://github.com/swarm-routing)
// SPDX-License-Identifier: GPL-2.0-only
// Browser smoke for the Colony Arena's own pages (the hub, the pipeline page and
// every project space; AntHocNet's pages have site/anthocnet/test/smoke.mjs). Serves the
// assembled site at / and, in headless Chromium:
//   1. opens the hub, /pipeline/, /projects/, /references/ and every /projects/<id>/ page in day and night, requires no
//      console error and no uncaught exception, and runs axe-core: a serious
//      or critical violation fails;
//   2. checks the colony map has one place per project plus the arena, and
//      that focusing a place by keyboard fills the map card;
//   3. checks the day/night switch flips the theme and the hub has no
//      horizontal scroll at 320 px;
//   3b. the site's one top bar (#97): the same bar on the hub, a project
//      page, /references/ and /pipeline/ (and, when /AntHocNet/ was built, on
//      the game, a docs page and an API page, which add AntHocNet's row),
//      apart from the current-place marker; night chosen on one page is night
//      on the others, the game included, and a choice kept under the game's
//      old key is carried over; the bar is one row on a phone; AntHocNet's
//      project page and the game point at each other beside the breadcrumb;
//   4. on a project page that has a References section (rendered from the
//      repository's docs/references.bib; none when the bib is empty), checks
//      every entry carries one https link (its doi.org link, else its url);
//   5. checks the generated fields (#104): every project page shows a status;
//      one computed from data/hub.json links the GitHub issues it came from,
//      shows the data's date and lists the repository's epics as its quests;
//      the hub's colony level is the closed sub-issues over all sub-issues in
//      data/hub.json, and the map locks exactly the places whose status is
//      planned. Without data/hub.json every status reads "not available".
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
const hubFile = new URL('../data/hub.json', import.meta.url);
const hubData = fs.existsSync(hubFile) ? JSON.parse(fs.readFileSync(hubFile)) : null;
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

const urls = ['', 'pipeline/', 'projects/', 'references/'].concat(projects.map((p) => `projects/${p.id}/`));
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
// 3b. One top bar, one day/night choice (#97).
{
  const hasGame = fs.existsSync(path.join(ROOT, 'AntHocNet', 'index.html'));
  const has = (rel) => fs.existsSync(path.join(ROOT, rel));
  // What a page's bar is, with what may differ taken out: the current-place
  // marker, AntHocNet's row, and the depth of a link (compared as resolved).
  const barOf = (page) => page.evaluate(() => {
    const bar = document.querySelector('.ahn-bar').cloneNode(true);
    bar.querySelector('.ahn-row2')?.remove();
    bar.classList.remove('ahn-open');
    for (const e of bar.querySelectorAll('[aria-current]')) e.removeAttribute('aria-current');
    for (const a of bar.querySelectorAll('a[href]')) a.setAttribute('href', new URL(a.getAttribute('href'), location.href).pathname.replace(/^.*\/\/[^/]+/, ''));
    bar.querySelector('#theme').textContent = '';
    bar.querySelector('#ahn-menu').setAttribute('aria-expanded', 'false');
    return bar.outerHTML.replace(/>\s+</g, '><');
  });
  const current = (page) => page.evaluate(() => [...document.querySelectorAll('.ahn-bar .ahn-top[aria-current]')]
    .map((a) => `${a.dataset.top}=${a.getAttribute('aria-current')}`).join(','));
  const surfaces = [['', ''], ['projects/', 'projects=page'], ['projects/AntHocNet/', 'projects=page'],
    ['references/', 'refs=page'], ['pipeline/', 'run=page']];
  if (hasGame) surfaces.push(['AntHocNet/#play', 'play=page'], ['AntHocNet/workshop.html', 'play=true']);
  if (has('AntHocNet/docs/places/lab/index.html')) surfaces.push(['AntHocNet/docs/places/lab/', 'play=true']);
  if (has('AntHocNet/api/annotated.html')) surfaces.push(['AntHocNet/api/annotated.html', 'play=true']);
  const ctx = await browser.newContext({ colorScheme: 'light', viewport: { width: 1280, height: 900 } });
  const page = await ctx.newPage();
  let want = null, n = 0;
  for (const [u, cur] of surfaces) {
    await page.goto(base + u, { waitUntil: 'load' });
    await page.waitForSelector('.ahn-bar');
    const bar = await barOf(page);
    if (want === null) {
      want = bar;
      const tops = (await page.locator('.ahn-bar .ahn-brand, .ahn-bar .ahn-top').allTextContents()).map((t) => t.trim()).join('|');
      if (tops !== 'Colony\u00a0Arena|Play|Projects|References|How it runs|GitHub') fail(`top bar: ${tops}`);
    } else if (bar !== want) fail(`${u}: its top bar differs from the hub's:\n  ${bar}\n  ${want}`);
    const got = await current(page);
    if (got !== cur) fail(`${u || '/'}: current place "${got}", expected "${cur}"`);
    if (u.startsWith('AntHocNet/') !== !!(await page.locator('.ahn-bar .ahn-row2').count())) fail(`${u || '/'}: AntHocNet's row is ${u.startsWith('AntHocNet/') ? 'missing' : 'on a page outside AntHocNet'}`);
    n++;
  }
  if (!failed) console.log(`ok: one top bar — identical on ${n} pages (${surfaces.map(([u]) => '/' + u).join(', ')}) apart from the current place and AntHocNet's row`);
  // Night chosen on the hub is night on every other page.
  const theme = () => page.evaluate(() => [document.documentElement.dataset.theme || 'system', getComputedStyle(document.body).backgroundColor].join(' '));
  await page.goto(base, { waitUntil: 'load' });
  const day = await theme();
  await page.click('#theme');
  const night = await theme();
  if (!night.startsWith('dark ') || night === day) fail(`theme: the switch on the hub gave "${night}" (day was "${day}")`);
  for (const [u] of surfaces.slice(1)) {
    await page.goto(base + u, { waitUntil: 'load' });
    await page.waitForFunction(() => document.getElementById('theme')?.textContent === '☀', null, { timeout: 10000 }).catch(() => fail(`${u}: the day/night button does not show night`));
    const here = await theme();
    if (here !== night) fail(`theme: night on the hub is "${here}" on ${u}, expected "${night}"`);
  }
  const stored = await page.evaluate(() => [localStorage.getItem('arena-theme'), localStorage.getItem('ahn-theme')].map(String).join(' '));
  if (stored !== 'dark null') fail(`theme: stored as "${stored}", expected one entry, arena-theme=dark`);
  await ctx.close();
  // A returning visitor of the game: its old key alone carries over to the hub.
  const old = await browser.newContext({ colorScheme: 'light' });
  await old.addInitScript(() => { try { if (!sessionStorage.getItem('seeded')) { localStorage.setItem('ahn-theme', 'dark'); sessionStorage.setItem('seeded', '1'); } } catch (e) { /* none */ } });
  const q = await old.newPage();
  await q.goto(base, { waitUntil: 'load' });
  const kept = await q.evaluate(() => [document.documentElement.dataset.theme, localStorage.getItem('arena-theme'), localStorage.getItem('ahn-theme')].map(String).join(' '));
  if (kept !== 'dark dark null') fail(`theme: a choice under the game's old key was not carried over (${kept})`);
  await old.close();
  if (!failed) console.log(`ok: one day/night choice — night on the hub is night on ${surfaces.length - 1} other pages${hasGame ? ', the game included' : ''}; the old ahn-theme key is carried over`);
  // The game and AntHocNet's project page point at each other from the same place.
  {
    const { page: pp } = await open('projects/AntHocNet/', 'light');
    const to = await pp.locator('.ahn-crumbbar .ahn-pair').evaluate((a) => new URL(a.getAttribute('href'), location.href).pathname).catch(() => null);
    if (to !== '/AntHocNet/') fail(`projects/AntHocNet/: the link to the game beside the breadcrumb goes to ${to}`);
    await pp.close();
    if (hasGame) {
      const { page: g } = await open('AntHocNet/#play', 'light');
      const back = await g.locator('.ahn-crumbbar .ahn-pair').evaluate((a) => new URL(a.getAttribute('href'), location.href).pathname).catch(() => null);
      if (back !== '/projects/AntHocNet/') fail(`the game: the link to the project page beside the breadcrumb goes to ${back}`);
      await g.close();
    }
    if (!failed) console.log(`ok: AntHocNet's project page links the game beside its breadcrumb${hasGame ? ', and the game links back from the same place' : ''}`);
  }
  // On a phone the bar is one row (the old header was 144 px at 375 px, #30); Menu opens the places.
  for (const u of ['', 'projects/AntHocNet/'].concat(hasGame ? ['AntHocNet/#play'] : [])) {
    const { page: ph } = await open(u, 'light', { width: 375, height: 720 });
    const h = await ph.locator('.ahn-bar').evaluate((e) => Math.round(e.getBoundingClientRect().height));
    if (h > 60) fail(`${u || '/'} at 375 px: the top bar is ${h} px tall, expected one row (at most 60)`);
    await ph.click('#ahn-menu');
    if (!(await ph.locator('.ahn-bar .ahn-top[data-top="refs"]').isVisible())) fail(`${u || '/'} at 375 px: Menu did not open the places`);
    await ph.keyboard.press('Escape');
    if (await ph.locator('.ahn-bar .ahn-top[data-top="refs"]').isVisible()) fail(`${u || '/'} at 375 px: Escape did not close the menu`);
    else console.log(`ok: ${u || '/'} at 375 px — top bar ${h} px, the places open from Menu and close with Escape`);
    await ph.close();
  }
}
// If shell.js never runs (blocked, or a module of the page fails to load), the
// Menu button is dead: the bar must not stay folded behind it (theme.js unfolds it at load).
{
  const ctx = await browser.newContext({ colorScheme: 'light', viewport: { width: 375, height: 720 } });
  const ph = await ctx.newPage();
  await ph.route('**/shell.js', (r) => r.abort());
  await ph.goto(base, { waitUntil: 'load' });
  if (!(await ph.locator('.ahn-bar .ahn-top[data-top="refs"]').isVisible())) fail('/ at 375 px with shell.js unavailable: the places stay folded behind a Menu button that cannot open them');
  else console.log('ok: / at 375 px with shell.js unavailable — the places stay reachable (the bar does not fold)');
  await ctx.close();
}
for (const u of ['', 'pipeline/', 'projects/', 'references/', 'projects/ns3-containers/', 'projects/AntHocNet/']) {
  const { page } = await open(u, 'light', { width: 320, height: 720 });
  const over = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  if (over > 0) fail(`${u || '/'} at 320 px: ${over} px of horizontal page scroll`);
  else console.log(`ok: ${u || '/'} at 320 px — no horizontal page scroll`);
  await page.close();
}

{
  let pages = 0, entries = 0;
  for (const p of projects) {
    const { page } = await open(`projects/${p.id}/`, 'light');
    if (await page.locator('#refs-t').count()) {
      pages++;
      const hrefs = await page.locator('.refs li').evaluateAll((lis) => lis.map((li) => [...li.querySelectorAll('a')].map((a) => a.getAttribute('href'))));
      if (!hrefs.length) fail(`projects/${p.id}/: a References section with no entry`);
      for (const h of hrefs) {
        entries++;
        if (h.length !== 1 || !/^https:\/\//.test(h[0])) fail(`projects/${p.id}/: a reference without one https link: ${JSON.stringify(h)}`);
      }
    }
    await page.close();
  }
  console.log(`ok: references — ${entries} entries on ${pages} project pages (a page whose bib is empty has none)`);
}

// The generated fields: status, quests, the colony level, the data's date.
{
  const { page } = await open('', 'light');
  const level = (await page.locator('.xp-v').textContent()).replace(/\s+/g, ' ').trim();
  if (hubData) {
    const epics = Object.values(hubData.repos).flatMap((r) => r.epics);
    const want = `${epics.reduce((n, e) => n + e.completed, 0)}/ ${epics.reduce((n, e) => n + e.total, 0)} sub-issues closed`;
    if (level !== want) fail(`hub: the colony level reads "${level}", data/hub.json says "${want}"`);
    const dates = await page.locator('time[data-asof]').evaluateAll((ts) => ts.map((t) => t.getAttribute('datetime')));
    if (!dates.length || dates.some((d) => d !== hubData.asOf)) fail(`hub: the data's date is ${hubData.asOf}, the page shows ${JSON.stringify(dates)}`);
  } else if (!/^–$/.test(level)) fail(`hub: no data/hub.json, yet the colony level reads "${level}"`);
  const locked = await page.locator('.colony .place[data-status="planned"]').count();
  const padlocks = await page.locator('.colony .padlock').count();
  if (locked !== padlocks) fail(`map: ${padlocks} padlocks for ${locked} planned places`);
  await page.close();
  let known = 0;
  for (const p of projects) {
    const { page } = await open(`projects/${p.id}/`, 'light');
    const st = await page.locator('p.status').getAttribute('data-status').catch(() => null);
    const has = hubData && hubData.repos[p.repo.split('/')[1]];
    if (!st) fail(`projects/${p.id}/: no status`);
    else if (!has) {
      if (st !== 'unknown' || !/not available/i.test(await page.locator('p.status').textContent())) fail(`projects/${p.id}/: no data for it, yet its status is ${st}`);
    } else {
      known++;
      if (st === 'unknown') fail(`projects/${p.id}/: data/hub.json has ${p.repo}, yet its status is not available`);
      const src = await page.locator('p.status a').evaluateAll((as) => as.map((a) => a.getAttribute('href')));
      if (!src.some((h) => h.startsWith(`https://github.com/${p.repo}/issues`))) fail(`projects/${p.id}/: the status does not link ${p.repo}'s issues`);
      if ((await page.locator('p.status time[data-asof]').getAttribute('datetime').catch(() => null)) !== hubData.asOf) fail(`projects/${p.id}/: the status does not show the data's date`);
      const quests = await page.locator('#quests .quests li a').evaluateAll((as) => as.map((a) => a.getAttribute('href')));
      const want = has.epics.map((e) => e.url);
      if (quests.length !== want.length || want.some((u) => !quests.includes(u))) fail(`projects/${p.id}/: ${quests.length} quests, ${want.length} epics in data/hub.json`);
    }
    await page.close();
  }
  console.log(`ok: status — ${known} of ${projects.length} project pages computed from data/hub.json${hubData ? ` (${hubData.asOf})` : ' (none: every status reads "not available")'}; colony level "${level}"; ${padlocks} padlocks`);
}

// The old address of a project page (/arena/<id>/, until #102) lands on the new one.
for (const old of ['arena/', `arena/${projects[0].id}/`]) {
  const { page } = await open(old, 'light');
  await page.waitForURL((u) => u.pathname.includes('/projects/'), { timeout: 5000 }).catch(() => {});
  const at = new URL(page.url()).pathname;
  const want = '/' + old.replace('arena/', 'projects/');
  if (!at.endsWith(want)) fail(`${old}: did not redirect to ${want} (at ${at})`);
  else console.log(`ok: ${old} redirects to ${want}`);
  await page.close();
}

// How to cite: where a project page has the block, its text names a version or a DOI, and Copy works.
{
  let blocks = 0;
  for (const p of projects) {
    const { page } = await open(`projects/${p.id}/`, 'light');
    if (await page.locator('#cite-t').count()) {
      blocks++;
      const outs = await page.locator('.cite-out').allTextContents();
      if (outs.length !== 2 || !outs[1].startsWith('@')) fail(`projects/${p.id}/: the cite block needs a text and a BibTeX citation`);
      const dois = await page.locator('#cite a.doi').evaluateAll((as) => as.map((a) => a.getAttribute('href')));
      for (const d of dois) if (!/^https:\/\/doi\.org\/10\./.test(d)) fail(`projects/${p.id}/: a DOI link that is not a doi.org link: ${d}`);
      const b = page.locator('#cite [data-copy]').first();
      if ((await b.getAttribute('data-copy')) !== outs[0]) fail(`projects/${p.id}/: the copy button does not carry the citation shown`);
    }
    await page.close();
  }
  console.log(`ok: cite — ${blocks} project pages say how to cite the project (a repository without a CITATION.cff has no block)`);
}

await browser.close();
srv.close();
console.log(failed ? `hub smoke: FAIL (${failed})` : 'hub smoke: PASS');
process.exit(failed ? 1 : 0);
