// Experiment mode's Worker (#99): runs the worlds off the page's thread, so the
// page stays usable. One World per (arm, seed): arm 0 is the default Config,
// arm i the i-th value, all on the same seeds. Seeds go first to last and the
// arms run inside each seed, so every column of the chart grows together.
// Messages in:  { type: 'run', id, spec } | { type: 'kit', id, spec, value }
// Messages out: { type: 'cell', id, arm, k, cell } ... { type: 'done', id, ms }
//               { type: 'kit', id, value, seed, snap } | { type: 'error', id, message }
import { engine } from './engine.js';
import { KitRecorder, SAMPLE_STEP } from './kit.js';
import { runWorld, seedList, configOf } from './experiment-lib.js';

async function run({ id, spec }) {
  const M = await engine();
  const t0 = performance.now();
  seedList(spec).forEach((seed, k) => {
    [null, ...spec.values].forEach((value, arm) => {
      const cell = runWorld(M, spec.world, seed, value === null ? {} : configOf(spec, value), spec.time);
      self.postMessage({ type: 'cell', id, arm, k, cell });
    });
  });
  self.postMessage({ type: 'done', id, ms: performance.now() - t0 });
}

// The scene of one value on the first seed, for the ns-3 kit (kit.js): where
// every node was each half second, and what kit.js's sceneFrom reads off a World.
async function kit({ id, spec, value }) {
  const M = await engine();
  const rec = new KitRecorder();
  let snap = null;
  const seed = spec.seeds[0];
  runWorld(M, spec.world, seed, configOf(spec, value), spec.time, SAMPLE_STEP, (w) => {
    rec.tick(w);
    snap = {
      channel: w.channel(), areaX: w.areaX(), areaY: w.areaY(), areaZ: w.areaZ(), range: w.range(),
      blocksX: w.blocksX(), blocksY: w.blocksY(), streetWidth: w.streetWidth(), nodeCount: w.nodeCount(),
      flowSpecs: Array.from(w.flowSpecs()),
    };
  });
  self.postMessage({ type: 'kit', id, value, seed, snap: { ...snap, samples: rec.samples } });
}

self.onmessage = (e) => {
  const job = e.data.type === 'run' ? run : e.data.type === 'kit' ? kit : null;
  if (!job) return;  // only the two messages above are answered
  job(e.data).catch((err) => self.postMessage({ type: 'error', id: e.data.id, message: String(err) }));
};
