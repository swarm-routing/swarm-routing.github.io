// Unit tests that need no browser and no WASM: the install quest's parser
// (#636), on real `make doctor` output (ns3/doctor.sh, as CI runs it) and real
// `./test.py` lines; and the one progress system (#96): the stored state, its
// migration from the entries the build before kept, and researcher mode.
// Usage: node web/test/quest.test.mjs
import { readFileSync } from 'node:fs';
import { parseDoctor, testsPassed, testsFailed, STEPS } from '../site/js/install-steps.js';
import { useStrings } from '../site/js/i18n.js';

useStrings(JSON.parse(readFileSync(new URL('../site/i18n/en.json', import.meta.url), 'utf8')));

let failed = 0;
const eq = (name, got, want) => {
  const ok = JSON.stringify(got) === JSON.stringify(want);
  if (!ok) failed++;
  console.log(`${ok ? 'ok  ' : 'FAIL'} ${name}${ok ? '' : `: got ${JSON.stringify(got)}, want ${JSON.stringify(want)}`}`);
};
const states = (doctor, text = '') => STEPS.map((s) => s.status(doctor, text)[0]);

// A full install on a supported tree, before building (doctor's own output).
const full = `ok    ns-3 tree: /opt/ns-3
ok    ns-3 3.42 (tested range 3.36-3.48)
ok    contrib/ is writable
ok    AntHocNet installed in contrib/anthocnet
ok    comparison baselines: aomdv:ok,gpsr:ok,oracle:ok
ok    CMake 3.28.3
ok    C++ compiler g++-13.3.0
ok    python3 3.11.15 (ns-3's ./ns3 driver)
----
verdict: ok
##DOCTOR## v=1 ns3=3.42 cmake=3.28.3 cxx=g++-13.3.0 python=3.11.15 contrib=writable module=installed baselines=aomdv:ok,gpsr:ok,oracle:ok built=no verdict=ok`;
const d = parseDoctor(full);
eq('doctor line parsed', [d.v, d.ns3, d.module, d.built, d.verdict], ['1', '3.42', 'installed', 'no', 'ok']);
eq('baselines parsed', d.baselineMap, { aomdv: 'ok', gpsr: 'ok', oracle: 'ok' });
eq('full install, not built', states(d), ['ok', 'ok', 'ok', 'todo', 'todo']);
eq('built + tests pass', states({ ...d, built: 'yes' }, '[1/1] PASS: TestSuite anthocnet'), ['ok', 'ok', 'ok', 'ok', 'ok']);

// BASELINES=0 install: still a pass, with a note.
const alone = parseDoctor('##DOCTOR## v=1 ns3=3.48 cmake=3.28.3 cxx=g++-13.3.0 python=3.11.15 contrib=writable module=installed baselines=aomdv:missing,gpsr:missing,oracle:missing built=yes verdict=warn');
eq('BASELINES=0 install', states(alone), ['ok', 'ok', 'ok', 'ok', 'todo']);
eq('BASELINES=0 note', /without aomdv, gpsr, oracle/.test(STEPS[2].status(alone)[1]), true);

// Not an ns-3 tree (doctor's fail case).
const bad = parseDoctor('##DOCTOR## v=1 ns3=unknown cmake=3.28.3 cxx=g++-13.3.0 python=3.11.15 contrib=missing module=missing baselines=none built=no verdict=fail');
eq('not a tree', states(bad), ['fail', 'ok', 'todo', 'todo', 'todo']);
// ns-3-dev and an old waf tree.
eq('ns-3-dev warns', STEPS[0].status(parseDoctor('##DOCTOR## v=1 ns3=3-dev contrib=writable'))[0], 'warn');
eq('ns-3.35 warns', STEPS[0].status(parseDoctor('##DOCTOR## v=1 ns3=3.35 contrib=writable'))[0], 'warn');
// A missing compiler.
eq('no compiler', STEPS[1].status(parseDoctor('##DOCTOR## v=1 ns3=3.42 cmake=3.28.3 cxx=missing python=3.11 contrib=writable'))[0], 'fail');
// Test output.
eq('test pass', [testsPassed('[1/1] PASS: TestSuite anthocnet'), testsFailed('[1/1] PASS: TestSuite anthocnet')], [true, false]);
eq('test fail', STEPS[4].status(null, '[1/1] FAIL: TestSuite anthocnet')[0], 'fail');
// Garbage in, nothing out.
eq('no doctor line', parseDoctor('hello'), null);

// --- one progress system (#96): campaign/progress.js, no browser --------------------
// A fake localStorage, then the module's own functions on it.
const store = new Map();
globalThis.localStorage = { getItem: (k) => (store.has(k) ? store.get(k) : null), setItem: (k, v) => { store.set(k, String(v)); } };
const P = await import('../site/js/campaign/progress.js');
const { LEVELS } = await import('../site/js/campaign/levels.js');
const { isUnlocked } = await import('../site/js/campaign/engine.js');
const { MISSIONS } = await import('../site/js/missions-data.js');

// The state the build before #96 stored: two entries, each { id: stars }.
const oldLevels = { '1.1': 3, '1.2': 2, '1.3': 1, '5.3': 3 };
const oldDrills = { hello: 3, scouts: 1, 'sat-failcell': 2 };
store.set(P.OLD_LEVELS, JSON.stringify(oldLevels));
store.set(P.OLD_DRILLS, JSON.stringify(oldDrills));
eq('old state: every level keeps its stars', P.loadProgress(), oldLevels);
eq('old state: every drill keeps its best try', P.loadPractice(), oldDrills);
eq('old state: researcher mode starts off', P.researcherMode(), false);
eq('old state: one total, levels only', P.starTotal(LEVELS, P.loadProgress()), { n: 9, max: LEVELS.length * 3 });
eq('the migration is stored at once', JSON.parse(store.get(P.STORE)), { v: 2, levels: oldLevels, practice: oldDrills, open: false });
eq('the old entries are left as they were', [store.get(P.OLD_LEVELS), store.get(P.OLD_DRILLS)], [JSON.stringify(oldLevels), JSON.stringify(oldDrills)]);

// Stars only go up, and the two kinds never mix.
const prog = P.loadProgress();
P.recordStars(prog, '1.2', 1);
P.recordStars(prog, '1.4', 2);
eq('a worse run keeps the best stars', [prog['1.2'], P.loadProgress()['1.2']], [2, 2]);
eq('a new level is recorded', P.loadProgress()['1.4'], 2);
eq('a drill is recorded as practice', [P.recordPractice('scouts', 3), P.recordPractice('scouts', 1), P.loadPractice().scouts], [3, 3, 3]);
eq('a drill adds nothing to the total', P.starTotal(LEVELS, P.loadProgress()).n, 11);

// An old tab that still writes the v1 entry is folded in, never lost.
store.set(P.OLD_LEVELS, JSON.stringify({ ...oldLevels, '1.5': 3, '1.4': 1 }));
eq('a later v1 write is picked up, best of both', [P.loadProgress()['1.5'], P.loadProgress()['1.4']], [3, 2]);

// Researcher mode is one stored flag; it changes no star.
const before = JSON.stringify(P.loadProgress());
P.setResearcherMode(true);
eq('researcher mode is stored', [P.researcherMode(), JSON.parse(store.get(P.STORE)).open], [true, true]);
eq('researcher mode changes no star', JSON.stringify(P.loadProgress()), before);
P.recordStars(prog, '7.1', 3);
eq('stars earned with it on count', P.loadProgress()['7.1'], 3);
P.setResearcherMode(false);
eq('and it switches off', P.researcherMode(), false);

// Storage that refuses every write (private mode, a full quota): the best score
// of the session stays in the caller's map.
{
  const real = globalThis.localStorage;
  globalThis.localStorage = { getItem: () => null, setItem: () => { throw new Error('blocked'); } };
  const held = {};
  P.recordStars(held, '1.1', 3);
  P.recordStars(held, '1.1', 1);
  eq('storage blocked: a later, lower score does not replace the best', held, { '1.1': 3 });
  globalThis.localStorage = real;
}

// Damaged or foreign values never throw and never invent stars.
eq('damaged entries', P.migrate('{nope', '[1,2]', JSON.stringify({ hello: 9, cut: -1, boss: 'x', fresh: 2.7 })),
  { v: 2, levels: {}, practice: { hello: 3, fresh: 2 }, open: false });
store.clear();
eq('a fresh profile stores nothing on a read', [P.loadProgress(), store.size], [{}, 0]);

// The lock order is the engine's, as before: a fresh profile opens 1.1 only.
eq('fresh profile: only 1.1 is open', LEVELS.filter((l) => isUnlocked(l, LEVELS, {})).map((l) => l.id), ['1.1']);
// Every drill is practice for a level that exists.
eq('every drill names a campaign level', MISSIONS.filter((m) => !LEVELS.some((l) => l.id === m.level)).map((m) => m.id), []);

console.log(failed ? `quest parser + progress: FAIL (${failed})` : 'quest parser + progress: PASS');
process.exit(failed ? 1 : 0);
