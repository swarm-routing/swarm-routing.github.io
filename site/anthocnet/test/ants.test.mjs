// The map draws the ants the core reports (#94). In headless Chromium, on a
// fixed seed:
//   1. over an interval of simulated time, the ants and crumbs the renderer
//      was asked to draw (IsoRenderer.stats.asked, by kind) equal the event
//      log's TxAnt and TxData counts for the same interval, kind by kind;
//   2. each kind's colour on the map is its token in css/learn.css, the seven
//      differ from one another, day and night, and the legend names every
//      type with a swatch and links the ant types to docs/ant-types/;
//   3. on the largest built-in world (the 64-satellite shell) at 20x, no
//      frame draws more sprites than the cap, and the overflow is non-zero
//      at some point (so the density path is exercised);
//   4. under prefers-reduced-motion the renderer is still and the counts
//      still match (a still frame shows the ants; it does not drop them).
// The counter is read-only: nothing in the page decides anything from it.
//
// Usage: node web/test/ants.test.mjs <assembled-site-root>
// Env:   CHROMIUM=/path/to/chrome (default: Playwright's pre-installed one)
// Needs: playwright-core resolvable from the working directory (as smoke.mjs).
import http from 'node:http';
import fs from 'node:fs';
import path from 'node:path';
import { createRequire } from 'node:module';

const root = process.argv[2];
if (!root) { console.error('usage: ants.test.mjs <site-root>'); process.exit(2); }
const require = createRequire(path.join(process.cwd(), 'noop.js'));
const { chromium } = require('playwright-core');
const types = { '.html': 'text/html', '.js': 'text/javascript', '.css': 'text/css', '.wasm': 'application/wasm', '.json': 'application/json', '.png': 'image/png', '.svg': 'image/svg+xml', '.woff2': 'font/woff2', '.webmanifest': 'application/manifest+json' };
const server = http.createServer((req, res) => {
  let p = decodeURIComponent(req.url.split('?')[0].split('#')[0]);
  if (p.endsWith('/')) p += 'index.html';
  const f = path.join(root, p);
  if (!f.startsWith(path.resolve(root)) || !fs.existsSync(f)) { res.writeHead(404); res.end(); return; }
  res.writeHead(200, { 'content-type': types[path.extname(f)] || 'application/octet-stream' });
  fs.createReadStream(f).pipe(res);
}).listen(0);
const base = `http://127.0.0.1:${server.address().port}/`;
const preinstalled = '/opt/pw-browsers/chromium-1194/chrome-linux/chrome';
const executablePath = process.env.CHROMIUM || (fs.existsSync(preinstalled) ? preinstalled : undefined);
const browser = await chromium.launch({ executablePath });
let failed = 0;
const check = (name, ok, detail = '') => { if (!ok) failed++; console.log(`${ok ? 'ok  ' : 'FAIL'} ${name}${ok ? '' : ': ' + detail}`); };

async function open(hash, options = {}) {
  const p = await browser.newPage({ viewport: { width: 1280, height: 860 }, ...options });
  const errors = [];
  p.on('pageerror', (e) => errors.push(e.message));
  await p.goto(base + hash);
  await p.waitForFunction(async () => !!(await import('./js/app.js')).playground.world);
  return [p, errors];
}

/** Run `seconds` of simulated time at `speed`; return what the event log held
 *  and what the renderer was asked to draw in that interval, by kind. */
function interval(p, seconds, speed) {
  return p.evaluate(async ([seconds, speed]) => {
    const { playground } = await import('./js/app.js');
    const { Ev, antKind } = await import('./js/engine.js');
    const frames = (n) => new Promise((done) => { const step = () => (n-- > 0 ? requestAnimationFrame(step) : done()); step(); });
    const R = playground.renderer;
    document.getElementById('ovHello').checked = true; // a hello is drawn only while its overlay is on
    playground.setSpeed(0);
    await frames(2); // everything already logged has been handed to the renderer
    const before = R.stats.asked;
    const logged = {};
    const off = playground.on((e) => {
      const kind = e.kind === Ev.TxAnt ? antKind(e.a, e.b) : e.kind === Ev.TxData ? 'data' : null;
      if (kind) logged[kind] = (logged[kind] || 0) + 1;
    });
    const t0 = playground.world.now();
    playground.setSpeed(speed);
    while (playground.world.now() < t0 + seconds) await frames(1);
    playground.setSpeed(0);
    await frames(2);
    off();
    const after = R.stats.asked;
    const asked = {};
    for (const k of Object.keys(after)) if (after[k] - (before[k] || 0)) asked[k] = after[k] - (before[k] || 0);
    return { logged, asked, from: t0, to: playground.world.now(), still: R.still };
  }, [seconds, speed]);
}

const same = (a, b) => JSON.stringify(Object.entries(a).sort()) === JSON.stringify(Object.entries(b).sort());
const KINDS = ['reactive', 'backward', 'proactive', 'repair', 'linkfail', 'hello', 'data'];

// 1. The count, kind by kind, on a fixed seed.
{
  const [p, errors] = await open('#manet?seed=1');
  const r = await interval(p, 12, 2);
  check(`manet seed 1, t=${r.from.toFixed(1)}..${r.to.toFixed(1)} s: asked to draw = logged, by kind (${JSON.stringify(r.logged)})`,
    same(r.logged, r.asked), `logged ${JSON.stringify(r.logged)} drawn ${JSON.stringify(r.asked)}`);
  for (const k of ['reactive', 'backward', 'hello', 'data']) check(`manet: the interval holds ${k} (${r.logged[k] || 0})`, (r.logged[k] || 0) > 0);

  // 2. Colour per kind = its token; all different; the legend.
  for (const scheme of ['light', 'dark']) {
    await p.emulateMedia({ colorScheme: scheme });
    const c = await p.evaluate(async (KINDS) => {
      const { playground } = await import('./js/app.js');
      const R = playground.renderer;
      R.refreshColors();
      const cs = getComputedStyle(document.documentElement);
      const token = { reactive: '--ant-scout', backward: '--ant-back', proactive: '--ant-pro', repair: '--ant-fix', linkfail: '--ant-fail', hello: '--ant-hello', data: '--ant-work' };
      return KINDS.map((k) => [k, R.colors[k], cs.getPropertyValue(token[k]).trim()]);
    }, KINDS);
    check(`${scheme}: every kind is drawn in its token's colour`, c.every(([, drawn, token]) => drawn && drawn === token), JSON.stringify(c));
    check(`${scheme}: the seven kinds have seven colours`, new Set(c.map(([, drawn]) => drawn)).size === KINDS.length, JSON.stringify(c));
  }
  const legend = await p.evaluate(() => Array.from(document.querySelectorAll('#legend li'), (li) => ({
    text: li.textContent.trim(), swatch: !!li.querySelector('canvas'), href: li.querySelector('a')?.getAttribute('href') || null })));
  check(`the legend has ${legend.length} entries, each with a swatch and a name`, legend.length === 10 && legend.every((l) => l.swatch && l.text));
  const typed = legend.filter((l) => /\bant\b/.test(l.text));
  check(`the ${typed.length} ant types link to docs/ant-types/`, typed.length === 6 && typed.every((l) => /^docs\/ant-types\/#[a-z0-9-]+$/.test(l.href || '')), JSON.stringify(typed));
  check('manet: no page errors', errors.length === 0, errors.join(' | '));
  await p.close();
}

// 3. The sprite cap on the largest built-in world.
{
  const [p, errors] = await open('#satellite?seed=1');
  const r = await p.evaluate(async () => {
    const { playground } = await import('./js/app.js');
    const R = playground.renderer;
    playground.setSpeed(20);
    let maxSprites = 0, maxOverflow = 0, frames = 0;
    const t0 = playground.world.now();
    while (playground.world.now() < t0 + 40) {
      await new Promise((done) => requestAnimationFrame(done));
      const s = R.stats;
      maxSprites = Math.max(maxSprites, s.sprites); maxOverflow = Math.max(maxOverflow, s.overflow); frames++;
    }
    return { nodes: playground.world.nodeCount(), cap: R.stats.cap, maxSprites, maxOverflow, frames };
  });
  check(`satellite (${r.nodes} nodes) at 20x: at most ${r.cap} sprites in any of ${r.frames} frames (most: ${r.maxSprites})`, r.maxSprites <= r.cap && r.maxSprites > 0);
  check(`satellite: the overflow is shown as density (up to ${r.maxOverflow} ants beyond the cap in one frame)`, r.maxOverflow > 0);
  const c = await interval(p, 4, 4);
  check(`satellite, t=${c.from.toFixed(1)}..${c.to.toFixed(1)} s: asked to draw = logged with the cap in force (${JSON.stringify(c.logged)})`,
    same(c.logged, c.asked), `logged ${JSON.stringify(c.logged)} drawn ${JSON.stringify(c.asked)}`);
  check('satellite: no page errors', errors.length === 0, errors.join(' | '));
  await p.close();
}

// 4. Reduced motion: a still frame, the same ants.
{
  const [p, errors] = await open('#manet?seed=1', { reducedMotion: 'reduce' });
  const r = await interval(p, 8, 2);
  check('reduced motion: the renderer is still', r.still === true);
  check(`reduced motion: asked to draw = logged, by kind (${JSON.stringify(r.logged)})`, same(r.logged, r.asked) && (r.logged.data || 0) > 0,
    `logged ${JSON.stringify(r.logged)} drawn ${JSON.stringify(r.asked)}`);
  check('reduced motion: no page errors', errors.length === 0, errors.join(' | '));
  await p.close();
}

await browser.close();
server.close();
if (failed) { console.error(`\n${failed} check(s) failed`); process.exit(1); }
console.log('\nants: the map draws what the core reports');
