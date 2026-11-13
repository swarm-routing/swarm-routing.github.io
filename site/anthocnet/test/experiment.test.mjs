// Experiment mode's promises (#99), checked in Node against the real WASM core
// and against swarm-routing/ns3-tools' statistics:
//   1. the page's mean and 95 % interval are stats_util.py's. The expected
//      numbers below were produced by RUNNING stats_util.t975 and
//      stats_util.t_ci (ns3-tools at the commit named below) on the data sets
//      in this file, and are committed, so this test needs no ns3-tools
//      checkout. With NS3_TOOLS=<checkout> it also runs that Python on the same
//      data and requires the same agreement. Tolerance: 1e-12 relative (both
//      sides are IEEE doubles through the same formula; the last bits may differ
//      in the square).
//   2. the verdict is "within noise" whenever the interval contains zero;
//   3. determinism: the same experiment run twice gives a byte-identical CSV,
//      and its link decodes back to the same experiment;
//   4. the CSV's header names the world, the seeds, the core, the site build
//      and the teaching-radio caveat.
// Usage: node web/test/experiment.test.mjs <assembled-site-root>
import fs from 'node:fs';
import path from 'node:path';
import { execFileSync } from 'node:child_process';
import { pathToFileURL } from 'node:url';

const root = process.argv[2];
if (!root) { console.error('usage: experiment.test.mjs <site-root>'); process.exit(2); }
const url = (p) => pathToFileURL(path.resolve(root, p)).href;
const { default: createAntHocNet } = await import(url('anthocnet.js'));
const lib = await import(url('js/experiment-lib.js'));
const M = await createAntHocNet();
let failed = 0;
const check = (name, ok, detail = '') => { if (!ok) failed++; console.log(`${ok ? 'ok  ' : 'FAIL'} ${name}${ok ? '' : ': ' + detail}`); };
const TOL = 1e-12;
const close = (a, b) => (a === null || b === null ? a === b : Math.abs(a - b) <= TOL * Math.max(1, Math.abs(a), Math.abs(b)));

// --- 1. the statistics ---------------------------------------------------------------
// Paired per-seed samples (changed, default); the statistics are taken on changed - default.
const SETS = {
  twenty: [
    [91.2, 88.4, 95.1, 79.9, 90.3, 85.7, 93.3, 87.0, 96.4, 82.5, 89.9, 91.8, 84.2, 94.6, 86.1, 90.7, 92.5, 83.9, 88.8, 97.0],
    [89.5, 88.9, 93.0, 81.1, 88.7, 86.2, 91.4, 87.3, 94.9, 80.2, 90.4, 89.6, 85.0, 92.1, 86.6, 88.2, 91.9, 84.4, 87.1, 95.8],
  ],
  three: [[1.5, 2.25, 0.125], [1.0, 2.5, 0.5]],
  fortyfive: [Array.from({ length: 45 }, (_, k) => ((k * 37) % 101) / 7), Array.from({ length: 45 }, (_, k) => ((k * 53) % 97) / 9)],
  one: [[2.0], [0.5]],
};
// Produced by stats_util.py of swarm-routing/ns3-tools at ab3374e (see the header): [mean, halfwidth].
const EXPECTED = {"twenty": [0.85, 0.6074636105410578], "three": [-0.041666666666666664, 1.1756940820863129], "fortyfive": [1.9368606701940037, 1.4628454881642068], "one": [1.5, null]};
const T975 = {"1": 12.706, "2": 4.303, "19": 2.093, "30": 2.042, "35": 2.03, "44": 2.0152727272727273, "99": 1.9842424242424241, "120": 1.98, "500": 1.9647999999999999};   // stats_util.t975(df) for these df

for (const [df, want] of Object.entries(T975)) check(`t975(${df}) = ${want}`, close(lib.t975(Number(df)), want), String(lib.t975(Number(df))));
for (const [name, [a, b]] of Object.entries(SETS)) {
  const s = lib.summary(lib.paired(a, b)), [mean, half] = EXPECTED[name];
  check(`${name}: mean and half-width equal stats_util.t_ci`, close(s.mean, mean) && close(s.half, half), `${s.mean} ± ${s.half} vs ${mean} ± ${half}`);
}
if (process.env.NS3_TOOLS) {
  const py = 'import json,sys\nsys.path.insert(0, sys.argv[1])\nimport stats_util as s\nd = json.loads(sys.argv[2])\n'
    + 'print(json.dumps({"ci": {k: list(s.t_ci([x - y for x, y in zip(a, b)])) for k, (a, b) in d["sets"].items()}, "t": {str(n): s.t975(n) for n in d["df"]}}))';
  const out = JSON.parse(execFileSync('python3', ['-c', py, path.join(process.env.NS3_TOOLS, 'python/ns3_tool'), JSON.stringify({ sets: SETS, df: Object.keys(T975).map(Number) })], { encoding: 'utf8' }));
  let same = Object.entries(out.t).every(([df, v]) => close(lib.t975(Number(df)), v));
  for (const [name, [a, b]] of Object.entries(SETS)) { const s = lib.summary(lib.paired(a, b)); same = same && close(s.mean, out.ci[name][0]) && close(s.half, out.ci[name][1]); }
  check('the same numbers from stats_util.py, run now from NS3_TOOLS', same, JSON.stringify(out));
} else console.log('skip the live stats_util.py run (set NS3_TOOLS=<ns3-tools checkout>); the committed numbers were checked');
check('a missing side drops the pair', lib.paired([1, null, 3], [0.5, 2, null]).join() === '0.5');

// --- 2. the verdict ----------------------------------------------------------------------
const v = (lo, hi, up) => lib.verdict({ half: (hi - lo) / 2, lo, hi }, up);
check('interval across zero is within noise, either direction', v(-1, 2, true) === 'noise' && v(-1, 2, false) === 'noise');
check('an interval that touches zero is within noise', v(0, 2, true) === 'noise' && v(-2, 0, false) === 'noise' && v(0, 0, true) === 'noise');
check('above zero: better when higher is better, worse when lower is', v(0.1, 2, true) === 'better' && v(0.1, 2, false) === 'worse');
check('below zero: worse when higher is better, better when lower is', v(-2, -0.1, true) === 'worse' && v(-2, -0.1, false) === 'better');
check('no interval, no verdict', lib.verdict(lib.summary([1]), true) === 'none');

// --- 3. determinism, and the link --------------------------------------------------------
const meta = JSON.parse(fs.readFileSync(path.join(root, 'config-fields.json'), 'utf8'));
const worlds = Array.from(M.scenarios());
const spec = lib.checkSpec({ world: 'manet', param: 'helloInterval', values: [0.5, 2], seeds: [1, 20], time: 20 }, meta, worlds);
const info = { core: 'abc123', build: 'f'.repeat(40), caveat: 'Teaching radio: unit disk.' };
const once = () => {
  const cells = [null, ...spec.values].map((value) => lib.seedList(spec).map((seed) => lib.runWorld(M, spec.world, seed, value === null ? {} : lib.configOf(spec, value), spec.time)));
  return lib.toCsv(spec, meta, cells, info);
};
const a = once(), b = once();
check('the same experiment twice gives a byte-identical CSV', a === b && a.length > 2000, `${a.length} vs ${b.length} bytes`);
const rows = a.split('\n').filter((l) => l && !l.startsWith('#'));
check('one row per arm and seed, after one header row', rows.length === 1 + 3 * 20, String(rows.length));
check('a changed value changes what the core does', rows.some((r) => r.startsWith('changed,') && r.split(',').slice(10).some((d) => d !== '' && Number(d) !== 0)));
const back = lib.fromHash(lib.toHash(spec, 'abc123'), meta, worlds);
check('the link decodes back to the same experiment', JSON.stringify(back) === JSON.stringify({ spec, core: 'abc123' }), JSON.stringify(back));
check('a link with an unknown field, world or too few seeds is refused',
  !lib.fromHash('#w=manet&p=nope&v=1', meta, worlds) && !lib.fromHash('#w=mars&p=alpha&v=0.5', meta, worlds) && !lib.fromHash('#w=manet&p=alpha&v=0.5&seeds=1-5', meta, worlds));
const tryOn = (over) => lib.checkSpec({ world: 'manet', param: 'helloInterval', values: [0.5], seeds: [1, 20], time: 20, ...over }, meta, worlds);
check('seeds past the safe integers are refused (2^53 + 1 is 2^53: the seeds would repeat)', tryOn({}) && !tryOn({ seeds: [2 ** 53, 2 ** 53 + 20] }));
check('a time value the ns-3 kit cannot say in whole milliseconds is refused', tryOn({ values: [0.001] }) && tryOn({ values: [0.25] }) && !tryOn({ values: [0.0001] }) && !tryOn({ values: [0.0015] }));
check('every suggested time value is one the kit can say', meta.fields.filter((f) => f.kind === 'time').every((f) => lib.suggest(f).every(lib.wholeMs)));
check('a bool field is tried at its other value', lib.suggest(lib.fieldOf(meta, 'enableProactive')).join() === '0');

// --- the Worker answers its two messages and no other name --------------------------------
// A message's type is never used as a method name: 'toString' or 'constructor'
// reach nothing, throw nothing and are not answered.
{
  const posted = [];
  globalThis.self = { postMessage: (m) => posted.push(m) };
  await import(url('js/experiment-worker.js'));
  let threw = '';
  for (const type of ['toString', 'constructor', '__proto__', 'hasOwnProperty', undefined]) {
    try { globalThis.self.onmessage({ data: { type, id: 1 } }); } catch (e) { threw += `${String(type)}: ${e.message}; `; }
  }
  await new Promise((r) => setTimeout(r, 50));
  check('the Worker runs no handler for a message type it does not know', !threw && !posted.length, threw + JSON.stringify(posted));
  const kitSpec = { ...spec, time: 10 };
  globalThis.self.onmessage({ data: { type: 'kit', id: 2, spec: kitSpec, value: spec.values[0] } });
  for (let n = 0; n < 200 && !posted.length; n++) await new Promise((r) => setTimeout(r, 50));
  check('and still answers a kit message', posted.length === 1 && posted[0].type === 'kit' && posted[0].id === 2 && posted[0].snap.samples.length > 0, JSON.stringify(posted).slice(0, 300));
}

// --- 4. the CSV header ---------------------------------------------------------------------
const head = a.split('\n').filter((l) => l.startsWith('#')).join('\n');
for (const [what, text] of [['the world', '# world: manet'], ['the seeds', '# seeds: 1-20 (20)'], ['the core', 'anthocnet.js?v=abc123'],
  ['the site build', `# site build: ${'f'.repeat(40)}`], ['the teaching-radio caveat', 'Teaching radio: unit disk.'], ['the link', '# reproduce: experiment.html#w=manet&p=helloInterval&v=0.5,2&seeds=1-20&t=20&core=abc123']]) {
  check(`the CSV header names ${what}`, head.includes(text), head);
}

console.log(failed ? `experiment: FAIL (${failed})` : 'experiment: PASS');
process.exit(failed ? 1 : 0);
