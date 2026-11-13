// Experiment mode (#99), the part with no page in it: the statistics, the
// experiment as a link, one run of the core, and the CSV. The page
// (experiment.js), its Worker (experiment-worker.js) and the Node tests
// (web/test/experiment.test.mjs) all use this file, so what the test holds to
// ns3-tools' stats_util.py is what the page shows.
//
// Nothing here routes: a run sets one Config field the bench exposes
// (config-fields.json), advances the core, and reads its own counters
// (flowStats, antTransmissions).
import { totals, RANGE } from './bench.js';

// --- statistics: swarm-routing/ns3-tools python/ns3_tool/stats_util.py -------------
// t_{0.975, df}: the same table, anchors and 1/df interpolation as _T975,
// _T975_ANCHORS and _T975_INF there. Change them there and here together.
const T975 = [0, 12.706, 4.303, 3.182, 2.776, 2.571, 2.447, 2.365, 2.306, 2.262, 2.228,
  2.201, 2.179, 2.160, 2.145, 2.131, 2.120, 2.110, 2.101, 2.093, 2.086,
  2.080, 2.074, 2.069, 2.064, 2.060, 2.056, 2.052, 2.048, 2.045, 2.042];
const T975_ANCHORS = [[30, 2.042], [40, 2.021], [60, 2.000], [120, 1.980]];
const T975_INF = 1.960;

/** stats_util.t975: the two-sided 97.5 % Student-t quantile. */
export function t975(df) {
  if (df < 1) throw new RangeError('df must be >= 1'); // i18n-ok: an error for a developer
  if (df <= 30) return T975[Math.floor(df)];
  let prev = T975_ANCHORS[0];
  for (const anchor of T975_ANCHORS.slice(1)) {
    if (df <= anchor[0]) {
      const [d0, t0] = prev, [d1, t1] = anchor;
      const w = (1.0 / df - 1.0 / d0) / (1.0 / d1 - 1.0 / d0);
      return t0 + w * (t1 - t0);
    }
    prev = anchor;
  }
  const [d0, t0] = T975_ANCHORS.at(-1);
  const w = (1.0 / df) / (1.0 / d0);
  return T975_INF + w * (t0 - T975_INF);
}

const sum = (xs) => { let s = 0; for (const x of xs) s += x; return s; };

/** stats_util.sample_sd: n - 1 in the denominator; 0 for n < 2. */
export function sampleSd(xs) {
  const n = xs.length;
  if (n < 2) return 0.0;
  const m = sum(xs) / n;
  return Math.sqrt(sum(xs.map((x) => (x - m) ** 2)) / (n - 1));
}

/** stats_util.t_halfwidth: t_{0.975, n-1} * sd / sqrt(n); null when n < 2. */
export function tHalfwidth(sd, n) {
  if (n < 2 || sd === null) return null;
  return t975(n - 1) * sd / Math.sqrt(n);
}

/** stats_util.t_ci: { mean, half } of a sample; half is null when n < 2. */
export function tCi(xs) {
  if (!xs.length) return { mean: null, half: null };
  return { mean: sum(xs) / xs.length, half: tHalfwidth(sampleSd(xs), xs.length) };
}

/** Per-seed differences, changed minus default; a seed where either side has
 *  no value (nothing delivered, so no delay) is left out, as a pair. */
export function paired(changed, base) {
  const out = [];
  for (let k = 0; k < changed.length; k++) {
    if (changed[k] != null && base[k] != null) out.push(changed[k] - base[k]);
  }
  return out;
}

/** The paired differences' mean and 95 % interval: { n, mean, half, lo, hi }. */
export function summary(diffs) {
  const { mean, half } = tCi(diffs);
  return { n: diffs.length, mean, half, lo: half === null ? null : mean - half, hi: half === null ? null : mean + half };
}

/** 'noise' whenever the interval contains zero; 'none' without an interval. */
export function verdict(s, higherIsBetter) {
  if (s.half === null) return 'none';
  if (s.lo <= 0 && s.hi >= 0) return 'noise';
  return (s.lo > 0) === higherIsBetter ? 'better' : 'worse';
}

// --- the three metrics, from the core's own counters ---------------------------------
export const METRICS = [
  { key: 'pdr', csv: 'delivery_pct', unit: 'pp', up: true },
  { key: 'delay', csv: 'delay_ms', unit: 'ms', up: false },
  { key: 'ants', csv: 'ants_per_delivered', unit: '', up: false },
];
/** One run's metric; null where it does not exist (nothing sent or delivered). */
export function metric(cell, key) {
  if (!cell) return null;
  if (key === 'pdr') return cell.sent ? (100 * cell.got) / cell.sent : null;
  if (key === 'delay') return cell.got ? cell.delayMs : null;
  return cell.got ? cell.ants / cell.got : null;
}

// --- one run -------------------------------------------------------------------------
/** A World on `seed` with `config` set, advanced to `time` in `step` slices
 *  (the event log is drained each slice so it does not grow); `each(w)` runs
 *  after every slice. Returns the core's counters. */
export function runWorld(M, worldId, seed, config, time, step = 5, each = null) {
  const w = new M.World(seed, worldId);
  try {
    for (const [k, v] of Object.entries(config)) w.setConfig(k, Number(v));
    w.start();
    if (each) each(w);
    for (let k = 1; k * step < time; k++) { w.advanceTo(k * step); w.drainEvents(); if (each) each(w); }
    w.advanceTo(time);
    w.drainEvents();
    if (each) each(w);
    const s = totals(w);
    return { sent: s.sent, got: s.got, delayMs: s.delayMs, ants: w.antTransmissions() };
  } finally {
    w.delete();
  }
}

// --- the experiment, as data and as a link ---------------------------------------------
export const LIMITS = { seedsMin: 20, seedsMax: 100, timeMin: 10, timeMax: 600, valuesMax: 8 };

export const seedList = (spec) => Array.from({ length: spec.seeds[1] - spec.seeds[0] + 1 }, (_, k) => spec.seeds[0] + k);
export const fieldOf = (meta, key) => meta.fields.find((f) => f.key === key);
/** The Config a value stands for (the default arm is the empty Config). */
export const configOf = (spec, value) => ({ [spec.param]: value });
/** A value as the bench holds it, for ns3Line: a bool field's 0/1 as a boolean. */
export const benchValue = (f, v) => (f.kind === 'bool' ? !!v : v);

/** Values worth trying first: around the default, inside the bench's slider range. */
export function suggest(f) {
  if (f.kind === 'bool') return [f.default ? 0 : 1];
  const [lo, hi] = RANGE[f.key] || [f.default / 4, f.default * 4];
  const out = [];
  for (const m of [0.25, 0.5, 2, 4]) {
    const v = Number(Math.min(hi, Math.max(lo, f.default * m)).toPrecision(3));
    if (v !== f.default && !out.includes(v)) out.push(v);
  }
  return out;
}

/** A time value (seconds) the ns-3 kit can say exactly: a whole number of
 *  milliseconds, at least one (bench.js's ns3Value writes times in ms). */
export const wholeMs = (v) => Math.round(v * 1000) >= 1 && Math.abs(v * 1000 - Math.round(v * 1000)) < 1e-6;

/** Checks an experiment against the fields and worlds that exist; returns the
 *  clean spec, or null when any part is not valid. */
export function checkSpec(spec, meta, worldIds) {
  const f = spec && fieldOf(meta, spec.param);
  if (!f || !worldIds.includes(spec.world)) return null;
  const values = [];
  for (const raw of spec.values || []) {
    const v = f.kind === 'bool' ? (Number(raw) ? 1 : 0) : Number(raw);
    if (!Number.isFinite(v) || (f.kind !== 'bool' && v <= 0) || (f.kind === 'time' && !wholeMs(v))) return null;
    if (v !== Number(f.default) && !values.includes(v)) values.push(v);
  }
  const [a, b] = (spec.seeds || []).map(Number);
  const n = b - a + 1, time = Number(spec.time);
  if (!values.length || values.length > LIMITS.valuesMax) return null;
  if (!Number.isSafeInteger(a) || !Number.isSafeInteger(b) || a < 1 || n < LIMITS.seedsMin || n > LIMITS.seedsMax) return null;
  if (!Number.isInteger(time) || time < LIMITS.timeMin || time > LIMITS.timeMax) return null;
  return { world: spec.world, param: f.key, values, seeds: [a, b], time };
}

/** The experiment as a URL fragment; `core` is the core's version, so whoever
 *  opens the link is told when their page runs another core. */
export function toHash(spec, core) {
  return `#w=${spec.world}&p=${spec.param}&v=${spec.values.join(',')}&seeds=${spec.seeds[0]}-${spec.seeds[1]}&t=${spec.time}${core ? `&core=${core}` : ''}`;
}

/** The fragment back to { spec, core }; null when it is not a whole, valid experiment. */
export function fromHash(hash, meta, worldIds) {
  const q = new URLSearchParams(String(hash).replace(/^#/, ''));
  if (!q.has('w') || !q.has('p')) return null;
  const spec = checkSpec({
    world: q.get('w'), param: q.get('p'), values: (q.get('v') || '').split(',').filter((s) => s !== ''),
    seeds: (q.get('seeds') || '1-20').split('-'), time: q.get('t') || 120,
  }, meta, worldIds);
  return spec ? { spec, core: q.get('core') || '' } : null;
}

// --- the CSV ---------------------------------------------------------------------------
const cellText = (x) => (x == null ? '' : String(x));

/**
 * One row per arm (the default, then each value) and seed. `cells[arm][k]` is
 * runWorld's result for arm (0 = default) and the k-th seed. `info`: { core,
 * build, caveat } -- the core's version, the site build and the world's
 * teaching-radio line, in English so the file is the same for every reader.
 * Numbers are written as JavaScript prints them (shortest form that reads back
 * exactly), so the same runs give the same bytes.
 */
export function toCsv(spec, meta, cells, info) {
  const f = fieldOf(meta, spec.param), seeds = seedList(spec);
  const lines = [
    '# AntHocNet experiment mode: one Config field changed, each value paired by seed with the default', // i18n-ok: a file header, the same in every language
    `# world: ${spec.world}`,
    `# parameter: ${f.key} (ns-3 attribute ${f.attr}); default ${Number(f.default)}; values ${spec.values.join(' ')}`,
    `# seeds: ${spec.seeds[0]}-${spec.seeds[1]} (${seeds.length}); simulated time: ${spec.time} s`, // i18n-ok: a file header, the same in every language
    `# core: anthocnet.js?v=${info.core || 'unversioned'} (the WebAssembly build of AntHocNet's core/ this page loaded)`, // i18n-ok: a file header, the same in every language
    `# site build: ${info.build || 'unstamped'} (commit of swarm-routing/swarm-routing.github.io; its protocols.lock names the core's commit)`, // i18n-ok: a file header, the same in every language
    `# this world, as the page says it: ${info.caveat}`, // i18n-ok: a file header, the same in every language
    '# A result here is a hypothesis to test in ns-3, not a number to publish.', // i18n-ok: a file header, the same in every language
    `# reproduce: experiment.html${toHash(spec, info.core)}`,
    '# d_* columns: this row minus the default arm on the same seed; empty where a metric does not exist (nothing delivered)', // i18n-ok: a file header, the same in every language
    `arm,parameter,value,seed,sent,delivered,ant_tx,${METRICS.map((m) => m.csv).join(',')},${METRICS.map((m) => 'd_' + m.csv).join(',')}`,
  ];
  [Number(f.default), ...spec.values].forEach((value, arm) => {
    seeds.forEach((seed, k) => {
      const c = cells[arm] && cells[arm][k];
      if (!c) return;
      const own = METRICS.map((m) => metric(c, m.key));
      const base = METRICS.map((m) => metric(cells[0][k], m.key));
      const d = own.map((x, i) => (arm === 0 || x == null || base[i] == null ? null : x - base[i]));
      lines.push([arm === 0 ? 'default' : 'changed', f.key, value, seed, c.sent, c.got, c.ants, ...own, ...d].map(cellText).join(','));
    });
  });
  return lines.join('\n') + '\n';
}
