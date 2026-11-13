// One progress system (#96). Everything the game remembers about a player is
// one localStorage entry, `ahn-progress-v2`:
//
//   { v: 2,
//     levels:   { '1.2': 3, ... },   best stars per campaign level: THE star count
//     practice: { scouts: 2, ... },  best try per drill (missions-data.js): never summed
//     open:     false }              researcher mode: every level open
//
// The build before it kept two entries, each a flat { id: stars } map:
// `ahn-campaign-v1` (levels, "n / 96 stars") and `ahn-missions-v1` (the eight
// drills and four world challenges, "n / 36 stars"). They are read, never
// written and never removed: every load folds them in, star by star, taking
// the larger number, so a visitor keeps what they earned, an old tab that
// still writes the v1 entries is picked up too, and going back to an older
// build finds its own entries as it left them.
//
// No DOM and no simulator here: the unit test (test/quest.test.mjs) runs this
// file in Node.

export const STORE = 'ahn-progress-v2';
export const OLD_LEVELS = 'ahn-campaign-v1';
export const OLD_DRILLS = 'ahn-missions-v1';

const parse = (s) => {
  try { const o = JSON.parse(s || 'null'); return o && typeof o === 'object' && !Array.isArray(o) ? o : {}; } catch { return {}; }
};
/** A stored star count, as a whole number from 0 to 3 (anything else is 0). */
const star = (x) => (Number.isFinite(x) ? Math.max(0, Math.min(3, Math.floor(x))) : 0);
/** Fold star maps together: per id, the best count; ids with no star are left out. */
function best(...maps) {
  const out = {};
  for (const m of maps) {
    for (const [id, n] of Object.entries(m && typeof m === 'object' ? m : {})) {
      const s = Math.max(out[id] || 0, star(n));
      if (s) out[id] = s;
    }
  }
  return out;
}

/**
 * The v2 state from what is stored: the v2 entry (or nothing) and the two v1
 * entries (or nothing), each as the raw string localStorage holds.
 */
export function migrate(v2, oldLevels, oldDrills) {
  const cur = parse(v2);
  return {
    v: 2,
    levels: best(cur.levels, parse(oldLevels)),
    practice: best(cur.practice, parse(oldDrills)),
    open: cur.open === true,
  };
}

const get = (k) => { try { return localStorage.getItem(k); } catch { return null; } };

export function loadState() {
  const raw = get(STORE);
  const state = migrate(raw, get(OLD_LEVELS), get(OLD_DRILLS));
  // Write the merged state once it differs from what is stored, so the
  // migration does not depend on the player earning another star.
  if (JSON.stringify(state) !== raw && (raw !== null || Object.keys(state.levels).length || Object.keys(state.practice).length)) saveState(state);
  return state;
}
function saveState(state) {
  try { localStorage.setItem(STORE, JSON.stringify(state)); } catch { /* storage blocked: play without it */ }
}
/** Read the stored state, change it, write it back; returns the new state. */
function update(change) {
  const state = loadState();
  change(state);
  saveState(state);
  return state;
}

// --- levels: the one star count ------------------------------------------------------
/** Best stars per level id, as { id: stars }. */
export function loadProgress() { return loadState().levels; }
/** Keep the best star count of a level; `progress` (a loadProgress() map) is updated too. */
export function recordStars(progress, levelId, stars) {
  const n = update((s) => { s.levels[levelId] = Math.max(s.levels[levelId] || 0, star(stars)); }).levels[levelId];
  progress[levelId] = n;
}
/** The page's star total: stars earned over stars there are, levels only. */
export function starTotal(levels, progress) {
  return { n: levels.reduce((a, l) => a + star(progress[l.id]), 0), max: levels.length * 3 };
}

// --- drills: practice, each with its best try -------------------------------------------
export function loadPractice() { return loadState().practice; }
export function recordPractice(drillId, stars) {
  return update((s) => { s.practice[drillId] = Math.max(s.practice[drillId] || 0, star(stars)); }).practice[drillId];
}

// --- researcher mode: every level open -----------------------------------------------------
// It removes the lock and nothing else: a level started with it on is scored
// and recorded exactly as any other.
export function researcherMode() { return loadState().open; }
export function setResearcherMode(on) { update((s) => { s.open = !!on; }); }
