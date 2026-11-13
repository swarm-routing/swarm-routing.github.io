// Experiment mode (#99): one Config field, a few values, the default beside
// them on the same seeds, and the paired difference per seed with its mean and
// 95 % confidence interval. The worlds run in a Worker (experiment-worker.js);
// the statistics, the link and the CSV are experiment-lib.js; the fields are
// the tuning bench's (config-fields.json) and the ns-3 kit is kit.js. This
// file only draws: every number comes from the WebAssembly core's counters.
import { initPage } from '../shell/shell.js';
import { initI18n, t, num } from './i18n.js';
import { WORLDS, worldById } from './worlds.js';
import { ns3Line } from './bench.js';
import { sceneFrom, buildKit, zip } from './kit.js';
import {
  METRICS, LIMITS, metric, paired, summary, verdict, suggest, checkSpec, wholeMs, toHash, fromHash, toCsv,
  seedList, fieldOf, benchValue,
} from './experiment-lib.js';

const $ = (id) => document.getElementById(id);
const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' })[c]);
const GLYPH = { better: '▲', worse: '▼', noise: '●', none: '…' };

await initI18n();
initPage();

let meta = null;
try {
  const r = await fetch('config-fields.json');
  if (r.ok) meta = await r.json();
} catch { /* reported below */ }
// The core's version is the hash build-site.sh puts on engine.js's import.
const core = await fetch(new URL('./engine.js', import.meta.url)).then((r) => r.text())
  .then((s) => (s.match(/anthocnet\.js\?v=([0-9a-f]+)/) || [])[1] || '').catch(() => '');
const build = document.querySelector('meta[name="swarm-site-build"]')?.content || '';
// The CSV's caveat is the world's line in English, whatever the page's language.
const english = await fetch(new URL('../i18n/en.json', import.meta.url)).then((r) => r.json()).catch(() => null);
const worldIds = WORLDS.map((w) => w.id);

// --- what the form holds, and what was run --------------------------------------------
const form = { world: 'manet', param: 'helloInterval', values: [], first: 1 };
let spec = null;        // the experiment on screen (running or finished)
let cells = [];         // cells[arm][k]: the core's counters, arm 0 = default
let done = 0, running = false, runId = 0, tookMs = 0;
let M = 0;              // the metric shown
let worker = null, kit = null;

const shown = (f, v) => (f.kind === 'bool' ? t(v ? 'bench.on' : 'bench.off')
  : `${num(v, Number.isInteger(v) ? 0 : Math.min(4, String(v).split('.')[1]?.length || 0))}${f.kind === 'time' ? ' s' : ''}`);
const signed = (x, d = 2) => (x > 0 ? '+' : x < 0 ? '−' : '') + num(Math.abs(x), d);
const metricName = (m) => t(`experiment.metrics.${m.key}`);
const total = (s) => (s.values.length + 1) * seedList(s).length;
const complete = () => !!spec && !running && done === total(spec);

// --- the form ----------------------------------------------------------------------------
function renderValues() {
  const f = fieldOf(meta, form.param);
  $('expDoc').textContent = `${f.doc} ${t('bench.attr')} ${f.attr}`;
  $('expDefault').textContent = t('experiment.default', { v: shown(f, Number(f.default)) });
  $('expAdd').hidden = f.kind === 'bool';
  $('expValues').replaceChildren(...form.values.map((v) => {
    const b = document.createElement('button');
    b.type = 'button';
    b.className = 'bevel exp-chip';
    b.textContent = shown(f, v);
    if (f.kind === 'bool') { b.disabled = true; return b; }
    b.append(' ×');
    b.setAttribute('aria-label', t('experiment.remove', { v: shown(f, v) }));
    b.addEventListener('click', () => { form.values = form.values.filter((x) => x !== v); renderValues(); });
    return b;
  }));
  renderRun();
}

function formSpec() {
  return checkSpec({
    world: form.world, param: form.param, values: form.values, time: Number($('expTime').value),
    seeds: [form.first, form.first + Number($('expSeeds').value) - 1],
  }, meta, worldIds);
}

function renderRun() {
  const s = formSpec();
  $('expRun').textContent = running ? t('experiment.stop') : t('experiment.run', { n: s ? total(s) : '–' });
  $('expHonest').replaceChildren(
    worldById(form.world).honest, ' ', Object.assign(document.createElement('b'), { textContent: t('experiment.honest') }));
}

function addValue() {
  const f = fieldOf(meta, form.param), v = Number($('expAddValue').value);
  if (!$('expAddValue').value || !Number.isFinite(v) || v <= 0 || (f.kind === 'time' && !wholeMs(v)) || v === Number(f.default) || form.values.includes(v)
    || form.values.length >= LIMITS.valuesMax) { say(t('experiment.badValue', { max: LIMITS.valuesMax })); return; }
  form.values = [...form.values, v].sort((a, b) => a - b);
  $('expAddValue').value = '';
  renderValues();
}

function fillForm(s) {
  form.world = s.world; form.param = s.param; form.values = [...s.values]; form.first = s.seeds[0];
  $('expWorld').value = s.world; $('expParam').value = s.param;
  $('expSeeds').value = s.seeds[1] - s.seeds[0] + 1; $('expTime').value = s.time;
  renderValues();
}

const say = (text) => { $('expStatus').textContent = text; };

// --- running -------------------------------------------------------------------------------
function newWorker() {
  worker = new Worker(new URL('./experiment-worker.js', import.meta.url), { type: 'module' });
  worker.onmessage = ({ data }) => {
    if (data.type === 'kit') { if (data.id === runId) gotKit(data); return; }
    if (data.id !== runId) return;
    if (data.type === 'cell') {
      if (!Number.isInteger(data.arm) || !Number.isInteger(data.k) || !cells[data.arm] || data.k < 0 || data.k >= cells[data.arm].length) return;
      cells[data.arm][data.k] = data.cell;
      done++;
      $('expProgress').children[data.arm].lastChild.children[data.k].classList.add('on');
      if (data.arm === spec.values.length) { progressText(); draw(); }
    } else if (data.type === 'done') {
      running = false; tookMs = data.ms;
      progressText(); renderRun(); draw(); finished();
    } else if (data.type === 'error') failed(data.message);
  };
  worker.onerror = (e) => failed(e.message || '');
}

// A Worker that failed is not used again: its engine (the WASM load) stays
// rejected, so the next run or kit starts a fresh one.
function failed(err) {
  if (worker) worker.terminate();
  worker = null; running = false;
  renderRun(); say(t('experiment.failed', { err }));
}

function progressText() {
  const text = running ? t('experiment.running', { done, total: total(spec) })
    : complete() ? t('experiment.done', { total: total(spec), s: num(tookMs / 1000, 1) })
      : t('experiment.stopped', { done, total: total(spec) });
  say(text);
  // An image only once there is a run to describe: before one the box is empty
  // and a role=img with no name fails axe (role-img-alt).
  $('expProgress').setAttribute('role', 'img');
  $('expProgress').setAttribute('aria-label', text);
}

function start(s) {
  stop();
  if (!worker) newWorker();
  spec = s; kit = null; done = 0; running = true; runId++;
  const seeds = seedList(s), f = fieldOf(meta, s.param);
  cells = [null, ...s.values].map(() => new Array(seeds.length).fill(null));
  $('expProgress').replaceChildren(...[null, ...s.values].map((v) => {
    const row = document.createElement('div');
    row.className = 'exp-seedrow';
    const grid = document.createElement('span');
    grid.className = 'exp-cells';
    grid.style.setProperty('--n', seeds.length);
    grid.append(...seeds.map(() => document.createElement('i')));
    row.append(Object.assign(document.createElement('span'), { textContent: v === null ? t('experiment.armDefault') : shown(f, v) }), grid);
    return row;
  }));
  const hash = toHash(s, core);
  if (location.hash !== hash) history.replaceState(null, '', hash);
  $('expLink').textContent = location.href;
  $('expCopy').disabled = false;
  $('expTake').replaceChildren(...s.values.map((v) => Object.assign(document.createElement('option'), { value: v, textContent: `${f.key} = ${shown(f, v)}` })));
  for (const id of ['expCsv', 'expTake', 'expKit', 'expCmdCopy']) $(id).disabled = true;
  $('expCmd').firstChild.textContent = t('experiment.noCmd');
  renderRun(); progressText(); draw();
  worker.postMessage({ type: 'run', id: runId, spec: s });
}

// Stopping ends the Worker (a run cannot be interrupted from inside); what
// arrived stays on screen, without a verdict.
function stop() {
  if (!running) return;
  worker.terminate();
  worker = null; running = false;
  progressText(); renderRun(); draw();
}

function finished() {
  $('expCsv').disabled = false;
  $('expTake').disabled = false;
  askKit();
}

// --- the ns-3 kit for one value (kit.js) ----------------------------------------------
function askKit() {
  kit = null;
  $('expKit').disabled = true; $('expCmdCopy').disabled = true;
  if (!worker) newWorker();
  worker.postMessage({ type: 'kit', id: runId, spec, value: Number($('expTake').value) });
}

function gotKit({ value, seed, snap }) {
  if (value !== Number($('expTake').value)) return;
  const f = fieldOf(meta, spec.param), w = worldById(spec.world);
  // sceneFrom reads a World; here it reads the Worker's copy of the same getters.
  const facade = Object.fromEntries(Object.keys(snap).map((k) => [k, () => snap[k]]));
  kit = buildKit(sceneFrom(facade, { samples: snap.samples }, {
    worldId: spec.world, seed, title: `${w.title}, ${f.key} = ${shown(f, value)}`, results: w.results,
    ranges: spec.world === 'town', attrs: ns3Line(meta, { [f.key]: benchValue(f, value) }),
  }));
  kit.name = `anthocnet-experiment-${spec.world}-${f.key}-${value}-seed${seed}-ns3`;
  $('expCmd').firstChild.textContent = kit.command.replace(/\$KIT\//g, '');
  $('expKit').disabled = false; $('expCmdCopy').disabled = false;
}

function download(name, type, data) {
  const url = URL.createObjectURL(new Blob([data], { type }));
  const a = Object.assign(document.createElement('a'), { href: url, download: name });
  document.body.append(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 10000);
}

/** The finished experiment's CSV (also what the smoke compares between runs). */
function csv() {
  const caveat = english?.world?.[spec.world]?.honest || worldById(spec.world).honest;
  return toCsv(spec, meta, cells, { core, build, caveat });
}

// --- the result: chart, table ------------------------------------------------------------
function columns() {
  const m = METRICS[M];
  const base = cells[0].map((c) => metric(c, m.key));
  return spec.values.map((v, i) => {
    const own = cells[i + 1].map((c) => metric(c, m.key));
    const dots = own.map((x, k) => (x == null || base[k] == null ? null : x - base[k]));
    const s = summary(paired(own, base));
    return { v, own, dots, s, verdict: complete() ? verdict(s, m.up) : 'none' };
  });
}

function niceStep(lim) {
  const raw = lim / 4, pow = 10 ** Math.floor(Math.log10(raw)), k = raw / pow;
  return (k < 1.5 ? 1 : k < 3.5 ? 2 : k < 7.5 ? 5 : 10) * pow;
}

function draw() {
  const plot = $('expPlot');
  if (!spec) {
    $('expSub').textContent = t('experiment.empty');
    plot.replaceChildren();
    return;
  }
  const m = METRICS[M], f = fieldOf(meta, spec.param), cols = columns(), seeds = seedList(spec);
  const unit = m.unit ? ` ${m.unit}` : '';
  $('expSub').textContent = `${t(m.up ? 'experiment.subUp' : 'experiment.subDown', { metric: metricName(m) })} `
    + t('experiment.what', { world: worldById(spec.world).title, a: spec.seeds[0], b: spec.seeds[1], time: spec.time });
  $('expKey').hidden = false; $('expTableBox').hidden = false;

  // Sized in real pixels, so the text stays readable on a phone; many values scroll sideways.
  // On a wide plot the zero line's label sits in the right margin; on a narrow
  // one it joins the axis title, and a two-word verdict takes two lines.
  const wide = (plot.clientWidth || 700) >= 600;
  const L = 56, R = wide ? 96 : 14, B = 46, H = 380;
  const W = Math.max(plot.clientWidth || 700, L + R + cols.length * 62);
  const words = (c) => { const w = t(`experiment.verdict.${c.verdict}`); return (W - L - R) / cols.length < 96 ? w.split(' ') : [w]; };
  const Tp = 36 + 14 * Math.max(1, ...cols.map((c) => (c.verdict === 'none' ? 1 : words(c).length)));
  const all = cols.flatMap((c) => [...c.dots.filter((d) => d != null), ...(c.s.half === null ? [] : [c.s.lo, c.s.hi])]);
  const lim = (Math.max(0, ...all.map(Math.abs)) || 1) * 1.12;
  const step = niceStep(lim), digits = Math.max(0, -Math.floor(Math.log10(step)));
  const y = (v) => Tp + (H - Tp - B) * (1 - (v + lim) / (2 * lim));
  const colW = (W - L - R) / cols.length, cx = (i) => L + colW * (i + 0.5);
  const label = t('experiment.chartLabel', { metric: metricName(m), param: f.key, n: seeds.length });
  const zero = t('experiment.zero', { v: shown(f, Number(f.default)) });
  let s = `<svg width="${W}" height="${H}" viewBox="0 0 ${W} ${H}" role="group" aria-label="${esc(label)}">`;
  for (let v = -Math.floor(lim / step) * step; v <= lim + 1e-12; v += step) {
    if (Math.abs(v) > step / 2) s += `<line class="exp-grid" x1="${L}" x2="${W - R}" y1="${y(v)}" y2="${y(v)}"/>`;
    s += `<text x="${L - 8}" y="${y(v) + 4}" text-anchor="end">${esc(Math.abs(v) < step / 2 ? '0' : signed(v, digits))}</text>`;
  }
  s += `<line class="exp-zero" x1="${L}" x2="${W - R}" y1="${y(0)}" y2="${y(0)}"/>`
    + (wide ? `<text x="${W - R + 6}" y="${y(0) + 4}">${esc(zero)}</text>` : '')
    + `<text x="8" y="14">${esc(t('experiment.axis', { metric: metricName(m) }) + (m.unit ? `, ${m.unit}` : '') + (wide ? '' : ` · 0 = ${zero}`))}</text>`;
  cols.forEach((c, i) => {
    const x = cx(i), spread = Math.min(46, colW * 0.5);
    // The column's hover area goes under the dots, so a dot keeps its own tooltip;
    // the mean and its interval are drawn over them.
    if (c.s.half !== null) s += `<rect class="exp-hit" data-i="${i}" x="${x - colW / 2 + 4}" y="${Tp}" width="${colW - 8}" height="${H - Tp - B}" fill="none" pointer-events="all"/>`;
    c.dots.forEach((d, k) => {
      // The sideways jitter is a fixed function of the seed's place, not random.
      if (d != null) s += `<circle class="exp-dot" data-i="${i}" data-k="${k}" cx="${x + (((k * 0.618034) % 1) - 0.5) * spread}" cy="${y(d)}" r="4"/>`;
    });
    if (c.s.half !== null) {
      s += `<g class="exp-meang" data-i="${i}" tabindex="0" role="img" aria-label="${esc(tipMean(c, f, m, unit).join('. '))}">`
        + `<path class="exp-bar" d="M${x} ${y(c.s.lo)}V${y(c.s.hi)}M${x - 8} ${y(c.s.lo)}h16M${x - 8} ${y(c.s.hi)}h16"/>`
        + `<circle class="exp-mean" cx="${x}" cy="${y(c.s.mean)}" r="5.5"/></g>`;
    }
    if (c.verdict !== 'none') {
      const lines = [GLYPH[c.verdict], ...words(c)];
      lines.forEach((line, n) => { s += `<text class="exp-verdict" x="${x}" y="${Tp - 8 - 14 * (lines.length - 1 - n)}" text-anchor="middle">${esc(line)}</text>`; });
    }
    s += `<text class="exp-val" x="${x}" y="${H - B + 20}" text-anchor="middle">${esc(shown(f, c.v))}</text>`;
  });
  s += `<text x="${(L + W - R) / 2}" y="${H - 6}" text-anchor="middle">${esc(f.key)}</text></svg>`;
  plot.innerHTML = s;

  // The hover layer: a seed's own difference, or a value's mean and interval.
  const tip = Object.assign(document.createElement('div'), { className: 'exp-tip', hidden: true });
  plot.append(tip);
  const show = (px, py, lines) => {
    tip.replaceChildren(...lines.flatMap((line, n) => (n ? [document.createElement('br'), line] : [Object.assign(document.createElement('b'), { textContent: line })])));
    tip.hidden = false;
    tip.style.left = `${Math.min(Math.max(px, tip.offsetWidth / 2 + 4), W - tip.offsetWidth / 2 - 4)}px`;
    tip.style.top = `${py}px`;
  };
  const at = (e) => { const r = plot.getBoundingClientRect(); return [e.clientX - r.left + plot.scrollLeft, e.clientY - r.top]; };
  for (const g of plot.querySelectorAll('.exp-meang, .exp-hit')) {
    const c = cols[+g.dataset.i];
    g.addEventListener('pointermove', (e) => show(...at(e), tipMean(c, f, m, unit)));
    if (g.tagName === 'rect') continue;
    g.addEventListener('focus', () => show(cx(+g.dataset.i), y(c.s.hi), tipMean(c, f, m, unit)));
    g.addEventListener('blur', () => { tip.hidden = true; });
  }
  for (const dot of plot.querySelectorAll('circle.exp-dot')) {
    dot.addEventListener('pointermove', (e) => {
      e.stopPropagation();
      const c = cols[+dot.dataset.i], k = +dot.dataset.k;
      show(...at(e), [t('experiment.tipSeed', { seed: seeds[k] }), `${signed(c.dots[k])}${unit}`,
        t('experiment.tipPair', { own: num(c.own[k], 2), base: num(c.own[k] - c.dots[k], 2) })]);
    });
  }
  plot.onpointerleave = () => { tip.hidden = true; };
  table(cols, f, m, unit);
}

function tipMean(c, f, m, unit) {
  return [`${f.key} = ${shown(f, c.v)}`, t('experiment.tipMean', { v: `${signed(c.s.mean)}${unit}` }),
    t('experiment.tipCi', { lo: signed(c.s.lo), hi: signed(c.s.hi) }),
    c.verdict === 'none' ? t('experiment.tipPartial', { n: c.s.n, total: seedList(spec).length })
      : `${GLYPH[c.verdict]} ${t(`experiment.verdict.${c.verdict}`)}`];
}

function table(cols, f, m, unit) {
  const mean = (xs) => { const v = xs.filter((x) => x != null); return v.length ? num(v.reduce((a, b) => a + b, 0) / v.length, 2) : '–'; };
  const head = ['value', 'pairs', 'defaultMean', 'changedMean', 'diff', 'lo', 'hi', 'verdict']
    .map((k) => `<th scope="col">${esc(t(`experiment.th.${k}`, { param: f.key, unit: unit.trim() }))}</th>`).join('');
  const base = cells[0].map((c) => metric(c, m.key));
  const rows = cols.map((c) => `<tr><th scope="row">${esc(shown(f, c.v))}</th><td>${c.s.n}</td><td>${mean(base)}</td><td>${mean(c.own)}</td>`
    + (c.s.half === null ? '<td>–</td><td>–</td><td>–</td>' : `<td>${signed(c.s.mean)}</td><td>${signed(c.s.lo)}</td><td>${signed(c.s.hi)}</td>`)
    + `<td>${c.verdict === 'none' ? '–' : `${GLYPH[c.verdict]} ${esc(t(`experiment.verdict.${c.verdict}`))}`}</td></tr>`).join('');
  $('expTable').innerHTML = `<table class="ph"><caption>${esc(metricName(m))}${esc(unit ? ` (${unit.trim()})` : '')}</caption><thead><tr>${head}</tr></thead><tbody>${rows}</tbody></table>`;
}

// --- wiring ----------------------------------------------------------------------------------
if (!meta) {
  say(t('bench.unavailable'));
  $('expRun').disabled = true;
} else {
  $('expWorld').replaceChildren(...WORLDS.map((w) => Object.assign(document.createElement('option'), { value: w.id, textContent: w.title })));
  $('expParam').replaceChildren(...meta.fields.map((f) => Object.assign(document.createElement('option'), { value: f.key, textContent: f.key })));
  $('expMetrics').replaceChildren(...METRICS.map((m, i) => {
    const b = Object.assign(document.createElement('button'), { type: 'button', className: 'bevel exp-chip', textContent: metricName(m) });
    b.setAttribute('aria-pressed', String(i === M));
    b.addEventListener('click', () => {
      M = i;
      [...$('expMetrics').children].forEach((o, n) => o.setAttribute('aria-pressed', String(n === i)));
      draw();
    });
    return b;
  }));
  $('expWorld').addEventListener('change', (e) => { form.world = e.target.value; renderRun(); });
  $('expParam').addEventListener('change', (e) => { form.param = e.target.value; form.values = suggest(fieldOf(meta, form.param)); renderValues(); });
  $('expSeeds').addEventListener('input', renderRun);
  $('expTime').addEventListener('input', renderRun);
  $('expAddBtn').addEventListener('click', addValue);
  $('expAddValue').addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); addValue(); } });
  $('expForm').addEventListener('submit', (e) => {
    e.preventDefault();
    if (running) { stop(); return; }
    const s = formSpec();
    if (s) start(s);
    else say(t('experiment.invalid', LIMITS));
  });
  $('expTake').addEventListener('change', askKit);
  const copy = async (text, ok) => {
    try { await navigator.clipboard.writeText(text); $('expKeepSay').textContent = t(ok); } catch { $('expKeepSay').textContent = text; }
  };
  $('expCopy').addEventListener('click', () => copy(location.href, 'experiment.copied'));
  $('expCmdCopy').addEventListener('click', () => copy(kit.command.replace(/\$KIT\//g, ''), 'kit.copied'));
  $('expCsv').addEventListener('click', () => download(`anthocnet-experiment-${spec.world}-${spec.param}.csv`, 'text/csv', csv()));
  $('expKit').addEventListener('click', () => download(`${kit.name}.zip`, 'application/zip', zip(kit.files, kit.name)));
  new ResizeObserver(() => { if (spec) draw(); }).observe($('expPlot'));

  // For the smoke and for a curious console: the finished experiment's CSV.
  window.experiment = { csv: () => (complete() ? csv() : null), get done() { return complete(); }, get ms() { return tookMs; } };

  // A link is a whole experiment: open it and it runs.
  const open = () => {
    const from = fromHash(location.hash, meta, worldIds);
    if (!from) return false;
    $('expCoreNote').hidden = !(from.core && core && from.core !== core);
    $('expCoreNote').textContent = t('experiment.otherCore', { theirs: from.core, ours: core });
    fillForm(from.spec);
    start(from.spec);
    return true;
  };
  window.addEventListener('hashchange', () => { if (!spec || location.hash !== toHash(spec, core)) open(); });
  if (!open()) {
    if (location.hash.length > 1) say(t('experiment.badLink'));
    form.values = suggest(fieldOf(meta, form.param));
    $('expWorld').value = form.world; $('expParam').value = form.param;
    renderValues();
    draw();
  }
}
