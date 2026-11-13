// Drills (#546, #547): short exercises, one AntHocNet mechanism each, on the
// sandbox worlds. Drills are data (missions-data.js); this file is the small
// engine that runs them: questions, prediction rounds scored against the
// core's own forwarding probabilities, goals checked against core events,
// hints, and a debrief that links to the doc page and the API symbol behind it.
//
// One progress system (#96): a drill is optional practice for the campaign
// level that teaches the same thing (its `level`), listed here under that
// level's chapter. A drill keeps its best try; the page's one star total is
// the campaign's (campaign/progress.js).
import { MISSIONS } from './missions-data.js';
import { Ev } from './engine.js';
import { CHAPTERS, LEVELS, levelById } from './campaign/levels.js';
import { loadProgress, loadPractice, recordPractice, starTotal } from './campaign/progress.js';
import { t, has } from './i18n.js';

const $ = (id) => document.getElementById(id);

/** The drills in the campaign's order: by the level each one practises. */
export const DRILLS = [...MISSIONS].sort((a, b) => LEVELS.indexOf(levelById(a.level)) - LEVELS.indexOf(levelById(b.level)));
/** The drills that practise a level. */
export const drillsFor = (levelId) => DRILLS.filter((m) => m.level === levelId);

export function initMissions(pg) {
  let active = null;

  function el(tag, attrs = {}, ...kids) {
    const e = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs)) {
      if (k === 'class') e.className = v;
      else if (k.startsWith('on')) e.addEventListener(k.slice(2), v);
      else e.setAttribute(k, v);
    }
    for (const k of kids) e.append(k);
    return e;
  }

  function stars(n) { return '★'.repeat(n) + '☆'.repeat(3 - n); }

  // --- the mission list -------------------------------------------------------
  function showList() {
    active?.stop(true);
    active = null;
    $('missionTitle').textContent = t('missions.title');
    const body = $('missionBody');
    body.replaceChildren();
    // The stars are the campaign's; a drill shows its best try and the level
    // it practises.
    const practice = loadPractice();
    body.append(el('p', { class: 'small' }, t('missions.campaignNote')));
    for (const c of CHAPTERS) {
      const drills = DRILLS.filter((m) => levelById(m.level).chapter === c.n);
      if (!drills.length) continue;
      body.append(el('p', { class: 'small' }, el('b', {}, t('campaign.chapter', { n: c.n, title: c.title }))));
      const ul = el('ul', { class: 'missions' });
      for (const m of drills) {
        const got = practice[m.id] || 0;
        ul.append(el('li', {}, el('button', { class: 'bevel', type: 'button', onclick: () => start(m) },
          el('span', {}, `${m.level} · ${m.title}`),
          el('span', { class: 'stars', 'aria-label': t('missions.best', { n: got }) }, stars(got)))));
      }
      body.append(ul);
    }
    const total = starTotal(LEVELS, loadProgress());
    const line = el('p', { class: 'muted small' }, el('b', { id: 'starTotal' }, t('campaign.totalStars', total)), ' ' + t('missions.total') + ' ');
    if (pg.campaign) line.append(el('button', { class: 'bevel', type: 'button', onclick: () => pg.campaign.openMap() }, t('missions.campaignBtn')));
    body.append(line);
  }

  // --- running one mission ------------------------------------------------------
  async function start(m) {
    active?.stop();
    const body = $('missionBody');
    $('missionTitle').textContent = t('missions.missionTitle', { level: m.level, title: m.title });
    const goal = el('p', { class: 'mission-goal' }, m.goal);
    const status = el('p', { class: 'small' }, '');
    const bar = el('div', { class: 'progress' }, el('span', { style: 'width:0%' }));
    const ask = el('div', {});
    let hintsUsed = 0;
    const hintBtn = el('button', { class: 'bevel', type: 'button' }, t('missions.hint'));
    const hintText = el('p', { class: 'small muted' }, '');
    hintBtn.addEventListener('click', () => {
      if (hintsUsed < m.hints.length) hintText.textContent = m.hints[hintsUsed++];
      if (hintsUsed >= m.hints.length) hintBtn.disabled = true;
    });
    const back = el('button', { class: 'bevel', type: 'button', onclick: showList }, t('missions.back'));
    body.replaceChildren(el('p', {}, m.intro), goal, bar, status, ask,
      el('div', { class: 'choices' }, hintBtn, back), hintText);

    await pg.load(m.world, m.seed, { config: m.config || {} });
    if (m.config && Object.keys(m.config).length) {
      pg.toast(t('missions.knob', { knobs: Object.entries(m.config).map(([k, v]) => `${k} = ${v}`).join(', ') }), 5000);
    }
    pg.setSpeed(m.speed ?? 0.25);
    if (m.tool) pg.setTool(m.tool);

    let done = false;
    const unsub = [];
    const timers = [];
    const ctx = {
      pg,
      get world() { return pg.world; },
      state: {},
      progress(frac, text) {
        bar.firstChild.style.width = `${Math.round(Math.max(0, Math.min(1, frac)) * 100)}%`;
        if (text !== undefined) status.textContent = text;
      },
      /** Show a question; resolves with the chosen option's value. */
      ask(question, options) {
        return new Promise((resolve) => {
          const row = el('div', { class: 'choices', role: 'group', 'aria-label': question });
          for (const o of options) {
            row.append(el('button', { class: 'bevel', type: 'button', onclick: () => { ask.replaceChildren(); resolve(o.value); } }, o.label));
          }
          ask.replaceChildren(el('p', {}, el('b', {}, question)), row);
          row.querySelector('button')?.focus({ preventScroll: true });
        });
      },
      say(text) { ask.replaceChildren(el('p', {}, text)); },
      on(fn) { const u = pg.on((e) => { if (!done && e.type !== 'reset') fn(e); }); unsub.push(u); return u; },
      /** Run fn every `ms` of wall time until the mission ends; returns a cancel. */
      every(ms, fn) {
        const id = setInterval(() => { if (!done) fn(); }, ms);
        timers.push(id);
        return () => clearInterval(id);
      },
      complete(score, debriefText) {
        if (done) return;
        done = true;
        const n = Math.max(1, Math.min(3, score - Math.max(0, hintsUsed - 1)));
        recordPractice(m.id, n);
        bar.firstChild.style.width = '100%';
        pg.news(t('missions.accomplished', { title: m.title, stars: stars(n) }), true);
        const links = el('p', { class: 'small' });
        for (const [label, href] of m.links) {
          links.append(el('a', { href }, (has(label) ? t(label) : label) + ' →'), ' ');
        }
        const next = DRILLS[DRILLS.indexOf(m) + 1];
        const lv = levelById(m.level);
        ask.replaceChildren(
          el('p', {}, el('span', { class: 'stars', 'aria-label': t('missions.stars', { n }) }, stars(n)), ' ', el('b', {}, t('missions.done'))),
          el('p', {}, debriefText || ''),
          el('p', {}, m.debrief), links,
          el('div', { class: 'choices' },
            pg.campaign ? el('button', { class: 'bevel primary', type: 'button', onclick: () => pg.campaign.openLevel(lv.id) }, t('missions.toLevel', { id: lv.id, title: lv.title })) : '',
            next ? el('button', { class: 'bevel', type: 'button', onclick: () => start(next) }, t('missions.next', { title: next.title })) : '',
            el('button', { class: 'bevel', type: 'button', onclick: showList }, t('missions.all'))));
      },
    };
    active = {
      /** Leave the mission; `reload` restores a mission knob to the defaults. */
      stop(reload = false) {
        done = true;
        unsub.forEach((u) => u());
        timers.forEach((id) => clearInterval(id));
        if (reload && ctx.state.knobbed) pg.load(pg.worldId, pg.seed);
      },
    };
    if (m.config && Object.keys(m.config).length) ctx.state.knobbed = true;
    m.run(ctx, Ev);
  }

  showList();
  // The campaign's briefing offers a level's drills (campaign.js).
  pg.missions = { showList, start };
  return pg.missions;
}
