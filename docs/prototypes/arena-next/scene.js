// Colony Arena prototypes: the storyboard scene (docs/prototypes/arena-next).
// SPDX-License-Identifier: GPL-2.0-only
// Copyright (c) 2026 Daniel Joppi (https://github.com/swarm-routing)
//
// A SCRIPTED animation, not a simulation: no protocol runs here and nothing is
// decided. Ants walk the paths the page lists (`flow.paths`), a returning ant
// adds to a link's glow, the glow fades. It shows how the shipped renderer
// (site/anthocnet/site/js/iso.js) could draw the core's own events: an ant per
// TxAnt/RxAnt, a carried crumb per data packet, the trail from World.pheromone.
// Golden rule 10 stands: the real page keeps drawing the WebAssembly core.
// A classic script (no module), so a prototype opens straight from disk.

const TAU = Math.PI * 2;
const rng = (seed) => () => {
  seed |= 0; seed = (seed + 0x6d2b79f5) | 0;
  let t = Math.imul(seed ^ (seed >>> 15), 1 | seed);
  t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
  return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
};
const key = (a, b) => (a < b ? `${a}-${b}` : `${b}-${a}`);

class Scene {
  /**
   * cfg: { nodes: [{x, y, label?}], links: [[a, b]], flow: {src, dst, paths, strays},
   *        proactive, dataReinforce, workerEvery, seed, warm, onSay(key, data), onStats(stats) }
   */
  constructor(canvas, cfg) {
    this.c = canvas; this.g = canvas.getContext('2d'); this.cfg = cfg;
    this.rand = rng(cfg.seed || 7);
    this.nodes = cfg.nodes.map((n, id) => ({ up: true, joy: 0, ...n, id }));
    this.links = cfg.links.map(([a, b]) => ({ a, b, ph: 0 }));
    this.linkOf = new Map(this.links.map((l) => [key(l.a, l.b), l]));
    this.ants = []; this.fx = []; this.t = 0; this.speed = 1; this.playing = true; this.hover = -1;
    this.stats = { delivered: 0, dropped: 0, ants: 0, repairs: 0 };
    this.flow = { ...cfg.flow, open: false, searching: false, retryAt: 0.6, nextWorker: 0, nextScout: 5, opened: false };
    const d = rng(99);
    this.decor = Array.from({ length: 70 }, () => ({ x: d(), y: d(), k: d() < 0.62 ? 'tuft' : d() < 0.6 ? 'pebble' : 'flower', s: 0.7 + d() * 0.7 }));
    this.col = {};
    this.readColours();
    new ResizeObserver(() => this.resize()).observe(canvas);
    this.resize();
    canvas.addEventListener('pointermove', (e) => { this.hover = this.pick(e); canvas.style.cursor = this.hover >= 0 ? 'pointer' : 'default'; });
    canvas.addEventListener('pointerleave', () => { this.hover = -1; });
    canvas.addEventListener('click', (e) => { const n = this.pick(e); if (n >= 0) this.toggleNode(n); });
    const still = matchMedia('(prefers-reduced-motion: reduce)').matches;
    for (let k = 0; k < (cfg.warm ?? (still ? 14 : 0)) * 30; k++) this.step(1 / 30);
    if (still) this.playing = false;
    let last = performance.now();
    const loop = (now) => {
      const dt = Math.min(0.05, (now - last) / 1000); last = now;
      if (this.playing) this.step(dt * this.speed);
      this.draw();
      requestAnimationFrame(loop);
    };
    requestAnimationFrame(loop);
  }

  readColours() {
    const cs = getComputedStyle(this.c);
    for (const k of ['field-a', 'field-b', 'field-edge', 'side-a', 'side-b', 'tuft', 'pebble', 'petal', 'link', 'ph', 'ph-glow',
      'ant-scout', 'ant-back', 'ant-work', 'ant-fix', 'leaf', 'dev', 'dev-2', 'dev-screen', 'dev-down', 'shadow-c', 'tag', 'ink', 'accent', 'good', 'bad']) {
      this.col[k] = cs.getPropertyValue(`--${k}`).trim();
    }
  }

  resize() {
    const r = this.c.getBoundingClientRect(), dpr = Math.min(2, devicePixelRatio || 1);
    this.w = r.width; this.h = r.height;
    this.c.width = Math.round(r.width * dpr); this.c.height = Math.round(r.height * dpr);
    this.g.setTransform(dpr, 0, 0, dpr, 0, 0);
    const pad = this.cfg.pad || [70, 110]; // room for the overlays above and below the field
    this.W = Math.min(this.w * (this.w < 700 ? 0.96 : 0.8), (this.h - pad[0] - pad[1]) * 1.9);
    this.ox = this.w / 2; this.oy = pad[0] + (this.h - pad[0] - pad[1] - this.W / 2) / 2;
  }

  /** World (0..1, 0..1) to screen. */
  iso(x, y, z = 0) { return [this.ox + (x - y) * this.W / 2, this.oy + (x + y) * this.W / 4 - z]; }
  nodeXY(id) { const n = this.nodes[id]; return this.iso(n.x, n.y); }
  pick(e) {
    const r = this.c.getBoundingClientRect(), px = e.clientX - r.left, py = e.clientY - r.top;
    let best = -1, bd = 26;
    for (const n of this.nodes) { const [x, y] = this.nodeXY(n.id); const d = Math.hypot(px - x, py - (y - 14)); if (d < bd) { bd = d; best = n.id; } }
    return best;
  }
  say(k, data) { this.cfg.onSay?.(k, data); }
  valid(p) { return p.every((id) => this.nodes[id].up); }
  strength(p) { let s = 1; for (let i = 0; i + 1 < p.length; i++) s = Math.min(s, this.linkOf.get(key(p[i], p[i + 1])).ph); return s; }

  spawn(type, path, wait = 0) {
    const sp = { scout: 0.30, back: 0.34, work: 0.24, fix: 0.34 }[type];
    this.ants.push({ type, path, i: 0, u: 0, wait, speed: sp * (0.9 + this.rand() * 0.2), ph: this.rand() * TAU });
    if (type !== 'work') this.stats.ants++;
  }

  discover(kind = 'scout') {
    const f = this.flow, ok = f.paths.filter((p) => this.valid(p));
    if (!ok.length) { this.say('island'); f.retryAt = this.t + 4; return; }
    f.searching = true;
    this.say(kind === 'fix' ? 'repair' : 'search');
    ok.forEach((p, k) => this.spawn(kind, p, k * 0.5));
    (f.strays || []).filter((p) => this.valid(p)).forEach((p, k) => this.spawn(kind, p, 0.2 + k * 0.35));
  }

  step(dt) {
    this.t += dt;
    const f = this.flow;
    for (const l of this.links) l.ph *= Math.exp(-dt * 0.045);
    for (const n of this.nodes) n.joy = Math.max(0, n.joy - dt);
    if (!f.open && !f.searching && this.t >= f.retryAt) this.discover(f.opened ? 'fix' : 'scout');
    if (f.open && this.t >= f.nextWorker) {
      const ok = f.paths.filter((p) => this.valid(p)).map((p) => ({ p, s: this.strength(p) })).filter((x) => x.s > 0.06);
      if (!ok.length) { f.open = false; f.retryAt = this.t + 0.5; } else {
        let sum = 0; for (const x of ok) sum += x.s ** 3;
        let r = this.rand() * sum, pickd = ok[0];
        for (const x of ok) { r -= x.s ** 3; if (r <= 0) { pickd = x; break; } }
        this.spawn('work', pickd.p);
        f.nextWorker = this.t + (this.cfg.workerEvery || 0.75);
      }
    }
    if (this.cfg.proactive && f.open && this.t >= f.nextScout) {
      const ok = f.paths.filter((p) => this.valid(p));
      if (ok.length) this.spawn('scout', ok[Math.floor(this.rand() * ok.length)]);
      f.nextScout = this.t + 3.2;
    }
    for (const a of this.ants) {
      if (a.wait > 0) { a.wait -= dt; continue; }
      const A = this.nodes[a.path[a.i]], B = this.nodes[a.path[a.i + 1]];
      a.u += (dt * a.speed) / Math.hypot(B.x - A.x, B.y - A.y);
      a.ph += dt * 22;
      while (a.u >= 1 && !a.dead) {
        const l = this.linkOf.get(key(a.path[a.i], a.path[a.i + 1]));
        if (a.type === 'back') l.ph = Math.min(1, l.ph + 0.5);
        if (a.type === 'work' && this.cfg.dataReinforce) l.ph = Math.min(1, l.ph + 0.05);
        a.i++; a.u -= 1;
        if (a.i >= a.path.length - 1) { this.arrive(a); a.dead = true; }
      }
    }
    this.ants = this.ants.filter((a) => !a.dead);
    for (const e of this.fx) e.age += dt;
    this.fx = this.fx.filter((e) => e.age < e.life);
    this.cfg.onStats?.(this.stats, this);
  }

  arrive(a) {
    const f = this.flow, end = a.path[a.path.length - 1], [x, y] = this.nodeXY(end);
    if (a.type === 'scout' || a.type === 'fix') {
      if (end === f.dst) { this.spawn('back', [...a.path].reverse()); this.pop(x, y - 34, '!', 'ant-scout'); } else this.pop(x, y - 34, '?', 'ink');
    } else if (a.type === 'back') {
      if (!f.open) {
        f.open = true; f.searching = false; f.nextWorker = this.t + 0.3;
        this.say(f.opened ? 'reopen' : 'open', { hops: a.path.length - 1 });
        f.opened = true;
      }
    } else {
      this.stats.delivered++; this.nodes[end].joy = 0.6;
      this.pop(x, y - 36, '+1', 'good');
      for (let k = 0; k < 6; k++) this.fx.push({ kind: 'crumb', x, y: y - 22, vx: (this.rand() - 0.5) * 70, vy: -40 - this.rand() * 60, age: 0, life: 0.7 });
      if (this.stats.delivered === 1) this.say('first');
      if (this.stats.delivered === 25) this.say('party');
    }
  }
  pop(x, y, text, colour) { this.fx.push({ kind: 'pop', x, y, text, colour, age: 0, life: 0.9 }); }

  toggleNode(id) {
    const n = this.nodes[id], f = this.flow;
    if (id === f.src || id === f.dst) { this.say('vip'); return; }
    n.up = !n.up;
    const [x, y] = this.nodeXY(id);
    if (n.up) { this.say('back', { id }); this.pop(x, y - 34, 'hi again', 'good'); return; }
    for (let k = 0; k < 10; k++) this.fx.push({ kind: 'dust', x, y: y - 8, vx: (this.rand() - 0.5) * 90, vy: -this.rand() * 50, age: 0, life: 0.8 });
    for (const l of this.links) if (l.a === id || l.b === id) l.ph = 0;
    for (const a of this.ants) {
      if (a.wait > 0 ? a.path.includes(id) : a.path.slice(a.i).includes(id)) {
        a.dead = true;
        if (a.type === 'work') { this.stats.dropped++; const A = this.nodeXY(a.path[a.i]); this.pop(A[0], A[1] - 30, 'oops', 'bad'); }
      }
    }
    this.ants = this.ants.filter((a) => !a.dead);
    const alive = f.paths.some((p) => this.valid(p) && this.strength(p) > 0.06);
    if (alive) this.say('planB', { id }); else {
      this.say('down', { id });
      if (f.open || f.searching) this.stats.repairs++;
      f.open = false; f.searching = false; f.retryAt = this.t + 0.9;
    }
  }

  // --- drawing -------------------------------------------------------------------
  draw() {
    const g = this.g, c = this.col, W = this.W;
    g.clearRect(0, 0, this.w, this.h);
    const P = (x, y, z) => this.iso(x, y, z), T = P(0, 0), R = P(1, 0), B = P(1, 1), L = P(0, 1), dz = W * 0.035;
    const poly = (pts, fill) => { g.beginPath(); pts.forEach(([x, y], i) => (i ? g.lineTo(x, y) : g.moveTo(x, y))); g.closePath(); g.fillStyle = fill; g.fill(); };
    poly([L, B, [B[0], B[1] + dz], [L[0], L[1] + dz]], c['side-a']);
    poly([B, R, [R[0], R[1] + dz], [B[0], B[1] + dz]], c['side-b']);
    poly([T, R, B, L], c['field-a']);
    g.save(); g.beginPath(); [T, R, B, L].forEach(([x, y], i) => (i ? g.lineTo(x, y) : g.moveTo(x, y))); g.clip();
    const N = 8;
    for (let i = 0; i < N; i++) for (let j = 0; j < N; j++) if ((i + j) % 2) poly([P(i / N, j / N), P((i + 1) / N, j / N), P((i + 1) / N, (j + 1) / N), P(i / N, (j + 1) / N)], c['field-b']);
    g.restore();
    g.strokeStyle = c['field-edge']; g.lineWidth = 2; g.beginPath(); g.moveTo(...L); g.lineTo(...B); g.lineTo(...R); g.stroke();
    for (const d of this.decor) this.drawDecor(d);

    g.lineCap = 'round';
    for (const l of this.links) {
      const up = this.nodes[l.a].up && this.nodes[l.b].up, [x1, y1] = this.nodeXY(l.a), [x2, y2] = this.nodeXY(l.b);
      g.strokeStyle = c.link; g.lineWidth = 1.5; g.setLineDash(up ? [] : [3, 6]);
      g.beginPath(); g.moveTo(x1, y1); g.lineTo(x2, y2); g.stroke(); g.setLineDash([]);
      if (l.ph > 0.03) {
        g.save(); g.globalAlpha = Math.min(1, 0.2 + l.ph * 0.8); g.shadowColor = c['ph-glow']; g.shadowBlur = 6 + 16 * l.ph;
        g.strokeStyle = c.ph; g.lineWidth = 2 + 6 * l.ph; g.beginPath(); g.moveTo(x1, y1); g.lineTo(x2, y2); g.stroke(); g.restore();
      }
    }
    const items = [];
    for (const n of this.nodes) { const [x, y] = this.nodeXY(n.id); items.push({ y, f: () => this.drawDevice(n, x, y) }); }
    for (const a of this.ants) {
      if (a.wait > 0) continue;
      const [x1, y1] = this.nodeXY(a.path[a.i]), [x2, y2] = this.nodeXY(a.path[a.i + 1]);
      const ang = Math.atan2(y2 - y1, x2 - x1), side = a.type === 'back' ? -5 : 5;
      const x = x1 + (x2 - x1) * a.u - Math.sin(ang) * side, y = y1 + (y2 - y1) * a.u + Math.cos(ang) * side;
      items.push({ y: y - 1, f: () => this.drawAnt(x, y, ang, a) });
    }
    items.sort((p, q) => p.y - q.y).forEach((it) => it.f());
    for (const e of this.fx) this.drawFx(e);
  }

  drawDecor(d) {
    const g = this.g, c = this.col, [x, y] = this.iso(0.03 + d.x * 0.94, 0.03 + d.y * 0.94), s = d.s * this.W / 620;
    if (d.k === 'tuft') {
      g.strokeStyle = c.tuft; g.lineWidth = 1.6 * s; g.beginPath();
      for (const k of [-1, 0, 1]) { g.moveTo(x + k * 2 * s, y); g.quadraticCurveTo(x + k * 3 * s, y - 5 * s, x + k * 5 * s, y - 8 * s); }
      g.stroke();
    } else if (d.k === 'pebble') {
      g.fillStyle = c.pebble; g.beginPath(); g.ellipse(x, y, 4 * s, 2.4 * s, 0, 0, TAU); g.fill();
    } else {
      g.fillStyle = c.petal; for (let k = 0; k < 5; k++) { g.beginPath(); g.arc(x + Math.cos(k * TAU / 5) * 3 * s, y - 4 * s + Math.sin(k * TAU / 5) * 3 * s, 1.9 * s, 0, TAU); g.fill(); }
      g.fillStyle = c.ph; g.beginPath(); g.arc(x, y - 4 * s, 1.6 * s, 0, TAU); g.fill();
    }
  }

  /** A phone: bezel, screen, signal bars. A tick on a delivery; dark and on its side when switched off. */
  drawDevice(n, x, y) {
    const g = this.g, c = this.col, k = Math.max(0.7, this.W / 760), f = this.flow, hot = this.hover === n.id;
    const hop = n.up && n.joy > 0 ? Math.sin(n.joy * 10) * 4 : 0;
    g.fillStyle = c['shadow-c']; g.beginPath(); g.ellipse(x, y, 12 * k, 4.5 * k, 0, 0, TAU); g.fill();
    g.save(); g.translate(x, y - 2 - hop); if (!n.up) g.rotate(1.3);
    const w = 15 * k, h = 27 * k;
    g.fillStyle = n.up ? c['dev-2'] : c['dev-down']; g.beginPath(); g.roundRect(-w / 2, -h, w, h, 3.5 * k); g.fill();
    if (hot) { g.strokeStyle = c.accent; g.lineWidth = 2.5; g.stroke(); }
    const sx = -w / 2 + 1.6 * k, sy = -h + 2.6 * k, sw = w - 3.2 * k, sh = h - 6.4 * k;
    g.fillStyle = !n.up ? c['shadow-c'] : n.joy > 0 ? c.good : c['dev-screen'];
    g.beginPath(); g.roundRect(sx, sy, sw, sh, 2 * k); g.fill();
    g.fillStyle = n.up ? c['dev-2'] : c['dev-down']; g.beginPath(); g.roundRect(-2.2 * k, -h + 1.1 * k, 4.4 * k, 1 * k, 0.5 * k); g.fill();
    if (n.up && n.joy > 0) {
      g.strokeStyle = c['dev-screen']; g.lineWidth = 2 * k; g.lineCap = 'round'; g.lineJoin = 'round';
      g.beginPath(); g.moveTo(-3.4 * k, sy + sh / 2); g.lineTo(-0.8 * k, sy + sh / 2 + 2.8 * k); g.lineTo(3.6 * k, sy + sh / 2 - 3 * k); g.stroke();
    } else if (n.up) {
      // signal bars: how many of this phone's links carry a trail right now
      let lit = 1; for (const l of this.links) if ((l.a === n.id || l.b === n.id) && l.ph > 0.15) lit = Math.min(4, lit + 1);
      for (let b = 0; b < 4; b++) {
        g.fillStyle = b < lit ? c.dev : c['dev-down']; g.globalAlpha = b < lit ? 1 : 0.35;
        const bh = (2.5 + b * 2.2) * k; g.fillRect(-5 * k + b * 2.7 * k, sy + sh - 3 * k - bh, 1.9 * k, bh);
      }
      g.globalAlpha = 1;
    }
    g.restore();
    const tag = n.id === f.src ? 'sender' : n.id === f.dst ? 'receiver' : hot ? (n.up ? 'click: switch off' : 'click: switch on') : null;
    if (tag) {
      g.font = `700 ${11 * Math.max(1, k)}px ui-rounded, system-ui, sans-serif`;
      const tw = g.measureText(tag).width + 12, ty = y + 9 * k;
      g.fillStyle = c.tag; g.beginPath(); g.roundRect(x - tw / 2, ty, tw, 17, 8); g.fill();
      g.fillStyle = c.ink; g.textAlign = 'center'; g.textBaseline = 'middle'; g.fillText(tag, x, ty + 9);
    }
  }

  /** One ant: three body segments, six legs in step, antennae; a worker carries a crumb of leaf. */
  drawAnt(x, y, ang, a) {
    const g = this.g, c = this.col, k = Math.max(0.75, this.W / 820);
    const col = c[{ scout: 'ant-scout', back: 'ant-back', work: 'ant-work', fix: 'ant-fix' }[a.type]];
    g.save(); g.translate(x, y); g.rotate(ang); g.scale(k, k);
    g.strokeStyle = col; g.fillStyle = col; g.lineWidth = 1.1; g.lineCap = 'round';
    for (let i = -1; i <= 1; i++) for (const s of [-1, 1]) {
      const sw = Math.sin(a.ph + i * 2.1 + (s > 0 ? 0 : Math.PI)) * 2.2;
      g.beginPath(); g.moveTo(i * 2.4, 0); g.lineTo(i * 2.6 + sw, s * 5.4); g.stroke();
    }
    g.beginPath(); g.ellipse(-5.2, 0, 4.2, 3, 0, 0, TAU); g.fill();
    g.beginPath(); g.ellipse(0, 0, 2.6, 2, 0, 0, TAU); g.fill();
    g.beginPath(); g.arc(4.2, 0, 2.5, 0, TAU); g.fill();
    for (const s of [-1, 1]) { g.beginPath(); g.moveTo(5.6, s * 1); g.quadraticCurveTo(8.5, s * 2.5, 9.5, s * 4 + Math.sin(a.ph * 0.6) * 0.8); g.stroke(); }
    if (a.type === 'work') { g.fillStyle = c.leaf; g.beginPath(); g.ellipse(3, -5.5 + Math.sin(a.ph) * 0.5, 4.8, 3, -0.5, 0, TAU); g.fill(); }
    g.restore();
  }

  drawFx(e) {
    const g = this.g, c = this.col, p = e.age / e.life;
    g.save(); g.globalAlpha = 1 - p * p;
    if (e.kind === 'pop') {
      g.font = `800 ${15 + 6 * Math.sin(Math.min(1, p * 3) * Math.PI / 2)}px ui-rounded, system-ui, sans-serif`;
      g.textAlign = 'center'; g.lineWidth = 4; g.strokeStyle = c.tag; g.fillStyle = c[e.colour];
      g.strokeText(e.text, e.x, e.y - p * 26); g.fillText(e.text, e.x, e.y - p * 26);
    } else {
      const x = e.x + e.vx * e.age, y = e.y + e.vy * e.age + 140 * e.age * e.age;
      g.fillStyle = e.kind === 'crumb' ? c.leaf : c.pebble;
      g.beginPath(); g.arc(x, y, e.kind === 'crumb' ? 2.6 : 3.5 * (1 + p), 0, TAU); g.fill();
    }
    g.restore();
  }
}

/** The storyboard town both prototypes play: 14 devices, one flow, two ways round. */
const TOWN = {
  nodes: [
    { x: 0.10, y: 0.52 }, { x: 0.25, y: 0.30 }, { x: 0.30, y: 0.68 }, { x: 0.42, y: 0.16 }, { x: 0.46, y: 0.47 },
    { x: 0.50, y: 0.84 }, { x: 0.62, y: 0.28 }, { x: 0.66, y: 0.62 }, { x: 0.80, y: 0.42 }, { x: 0.90, y: 0.60 },
    { x: 0.16, y: 0.86 }, { x: 0.78, y: 0.12 }, { x: 0.72, y: 0.88 }, { x: 0.12, y: 0.16 },
  ],
  links: [[0, 1], [0, 2], [1, 3], [1, 4], [2, 4], [2, 5], [3, 6], [4, 6], [4, 7], [5, 7], [6, 8], [7, 8], [7, 9], [8, 9],
    [0, 10], [2, 10], [10, 5], [3, 11], [6, 11], [11, 8], [5, 12], [7, 12], [12, 9], [13, 1], [13, 3], [0, 13]],
  flow: {
    src: 0, dst: 9,
    paths: [[0, 1, 4, 7, 9], [0, 2, 5, 7, 9], [0, 1, 3, 6, 8, 9], [0, 2, 5, 12, 9]],
    strays: [[0, 10, 5], [0, 13, 3, 11], [0, 2, 4, 6, 11], [0, 1, 4, 6]],
  },
};
