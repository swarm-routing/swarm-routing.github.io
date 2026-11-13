// Isometric city-builder renderer for the learn site (#545). The map is the
// world the WASM core simulates, seen at a 2:1 isometric angle: ground tiles,
// roads and buildings, phones / mesh routers / drones / cars / satellites as
// nodes, ants walking the pheromone trails, packets riding the radio beams.
// Moving nodes leave a fading trail and show their heading, so a MANET reads
// as people walking, not as a static plan.
//
// It draws what the core and the adapter report and decides nothing. All art
// is procedural (no image assets); colours come from the CSS tokens so the
// day (light) and night (dark) palettes stay the validated steps.

// Vehicle paints (decoration only, never an identity colour).
const CAR_PAINT = ['#c0392b', '#2e5aa8', '#e8e6df', '#3f4a59', '#d9a21b', '#2f7d5b'];

const EARTH_R = 6.371e6; // m: the globe drawn in the satellite world

// One token per ant kind (#94): the sprite on the map, the legend and the
// log's swatch all read the same one.
const KIND_VAR = {
  hello: '--ant-hello', reactive: '--ant-scout', backward: '--ant-back',
  proactive: '--ant-pro', repair: '--ant-fix', linkfail: '--ant-fail',
  data: '--ant-work',
};

// #94: at most this many ants and crumbs are drawn as sprites in one frame;
// the rest show as density (marching dots) on the link they walk. A drawing
// budget only: every one of them is still counted in `stats.asked`.
const SPRITE_CAP = 96;
const RING_CAP = 200;
// The ant's drawing box around its thorax [x, y, w, h] (droplets behind, flag
// and crumb above), and how many stride frames each kind is drawn in.
const ANT_BOX = [-18, -11, 29, 22];
const ANT_FRAMES = 6;

/** Deterministic 0..1 hash of two integers (decoration placement). */
function hash2(i, j) {
  let h = (i * 374761393 + j * 668265263) ^ 0x5bd1e995;
  h = Math.imul(h ^ (h >>> 13), 1274126177);
  return ((h ^ (h >>> 16)) >>> 0) / 4294967296;
}

export class IsoRenderer {
  constructor(canvas) {
    this.canvas = canvas;
    this.ctx = canvas.getContext('2d');
    this.meta = null;
    this.rot = 0;       // view rotation, quarter turns
    this.zoom = 1;
    this.panX = 0;
    this.panY = 0;
    this.colors = {};
    this.motionQuery = window.matchMedia('(prefers-reduced-motion: reduce)');
    // #94: what the renderer was asked to draw, for the test (read through `stats`).
    this.asked = {};
    this.seen = new WeakSet();
    this.frameStats = { sprites: 0, overflow: 0 };
    this.antStamps = new Map();
    this.trailLayer = null;
    this.camVersion = 0; // bumped whenever the camera or the canvas changes
    this.refreshColors();
  }

  /** Reduced motion: a still frame (no rotor spin, walking legs or marching dots). */
  get still() { return this.motionQuery.matches; }

  /** #94, read-only: every ant and crumb handed to draw() so far in this world,
   *  by kind (each transmission once), and the last frame's sprite budget. No
   *  decision is made from it; site/anthocnet/test/ants.test.mjs reads it. */
  get stats() { return { asked: { ...this.asked }, ...this.frameStats, cap: SPRITE_CAP }; }

  refreshColors() {
    const cs = getComputedStyle(document.documentElement);
    const v = (n) => cs.getPropertyValue(n).trim();
    const c = {};
    for (const n of ['sky', 'sky-top', 'slab-right', 'trail', 'grass-a', 'grass-b', 'grass-edge', 'road', 'road-mark', 'tree',
      'tree-dark', 'trunk', 'bldg-top', 'bldg-left', 'bldg-right', 'window', 'window-lit',
      'space', 'star', 'tower', 'tower-dark', 'node-off', 'beam', 'accent', 'good',
      'critical', 'text', 'text2', 'shadow', 'panel', 'panel-blue', 'ph-trail', 'ph-glow', 'ph-virtual', 'leaf',
      'ant-edge', 'dev', 'dev-2', 'dev-screen', 'dev-down']) c[n] = v('--' + n);
    for (const [k, name] of Object.entries(KIND_VAR)) c[k] = v(name);
    c.night = document.documentElement.dataset.theme === 'dark' ||
      (!document.documentElement.dataset.theme && matchMedia('(prefers-color-scheme: dark)').matches);
    this.colors = c;
    this.groundCache = null;
    this.antStamps = new Map();
    this.trailLayer = null;
  }

  /** World geometry, read once per world from the WASM World. */
  setWorld(meta) {
    this.meta = meta;
    this.motion = [];
    this.rings = null;
    this.orbitSample = null;
    this.asked = {};
    this.phPeak = 0;
    this.zoom = 1;
    this.panX = 0;
    this.panY = 0;
    this.groundCache = null;
    this.resize();
  }

  resize() {
    const dpr = window.devicePixelRatio || 1;
    const r = this.canvas.getBoundingClientRect();
    this.w = Math.max(1, r.width);
    this.h = Math.max(1, r.height);
    this.dpr = dpr;
    this.canvas.width = Math.round(this.w * dpr);
    this.canvas.height = Math.round(this.h * dpr);
    this.ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    this.groundCache = null;
    this.fit();
  }

  // --- camera ----------------------------------------------------------------
  /** Field size in the rotated frame. */
  dims() {
    const { areaX: W, areaY: H } = this.meta;
    return this.rot % 2 ? [H, W] : [W, H];
  }

  /** World (x, y) -> rotated (u, v). */
  rotate(x, y) {
    const { areaX: W, areaY: H } = this.meta;
    switch (this.rot) {
      case 1: return [y, W - x];
      case 2: return [W - x, H - y];
      case 3: return [H - y, x];
      default: return [x, y];
    }
  }

  unrotate(u, v) {
    const { areaX: W, areaY: H } = this.meta;
    switch (this.rot) {
      case 1: return [W - v, u];
      case 2: return [W - u, H - v];
      case 3: return [v, H - u];
      default: return [u, v];
    }
  }

  /** The satellite world is seen as a globe: Earth at the field's centre,
   *  satellites on their orbits, an orthographic camera tilted 22 degrees. */
  get globe() { return this.meta?.channel === 2 || this.meta?.channel === 3; }  // 3: #582 mixed

  fit() {
    if (!this.meta) return;
    this.camVersion++;
    if (this.globe) {
      const E = this.meta.areaX / 2 * 0.8; // frame the 7571 km orbits with a margin
      this.c = Math.min(this.w - 48, this.h - 48) / (2 * E) * this.zoom;
      this.ox = this.w / 2 + this.panX;
      this.oy = this.h / 2 + this.panY;
      this.yaw = this.rot * Math.PI / 2 + Math.PI / 5;
      this.el = 22 * Math.PI / 180;
      this.groundCache = null;
      return;
    }
    const [U, V] = this.dims();
    this.zf = 0.9; // vertical exaggeration of altitude
    const zmax = this.meta.areaZ || 0;
    const pad = 24;
    const top = 40;
    const base = Math.min((this.w - 2 * pad) / (U + V),
      (this.h - top - pad) / ((U + V) / 2 + zmax * this.zf + 40 / 1));
    this.c = base * this.zoom;
    this.ox = this.w / 2 + this.panX - (U - V) * this.c / 2;
    this.oy = top + zmax * this.zf * this.c + this.panY +
      ((this.h - top - pad) - ((U + V) / 2 + zmax * this.zf) * base) / 2 * this.zoom;
    this.groundCache = null;
  }

  /** World (x, y, z) -> screen [px, py]. */
  project(x, y, z = 0) {
    if (this.globe) {
      const [a, b] = this.camera(x, y);
      return [this.ox + a * this.c, this.oy + (b * Math.sin(this.el) - z * Math.cos(this.el)) * this.c];
    }
    const [u, v] = this.rotate(x, y);
    return [this.ox + (u - v) * this.c, this.oy + (u + v) * this.c / 2 - z * this.zf * this.c];
  }

  /** Screen -> world (x, y) on the ground plane. */
  unproject(px, py) {
    const a = (px - this.ox) / this.c;
    const b = (py - this.oy) * 2 / this.c;
    return this.unrotate((a + b) / 2, (b - a) / 2);
  }

  /** Globe: world (x, y) -> camera (across, toward the viewer). */
  camera(x, y) {
    const X = x - this.meta.areaX / 2, Y = y - this.meta.areaY / 2;
    const cy = Math.cos(this.yaw), sy = Math.sin(this.yaw);
    return [X * cy - Y * sy, X * sy + Y * cy];
  }

  /** Larger = nearer the viewer (z counts on the globe only). */
  depth(x, y, z = 0) {
    if (this.globe) return this.camera(x, y)[1] * Math.cos(this.el) + z * Math.sin(this.el);
    const [u, v] = this.rotate(x, y);
    return u + v;
  }

  hiddenNode(pos, i) { return this.hidden(pos[4 * i], pos[4 * i + 1], pos[4 * i + 2]) ? 1 : 0; }

  /** Globe: is the point hidden behind the Earth? */
  hidden(x, y, z) {
    if (!this.globe) return false;
    const [px, py] = this.project(x, y, z);
    return this.depth(x, y, z) < 0 && Math.hypot(px - this.ox, py - this.oy) < EARTH_R * this.c;
  }

  zoomAt(px, py, factor) {
    const z = Math.min(6, Math.max(0.5, this.zoom * factor));
    const f = z / this.zoom;
    this.panX = (this.panX - (px - this.w / 2)) * f + (px - this.w / 2);
    this.panY = (this.panY - (py - this.h / 2)) * f + (py - this.h / 2);
    this.zoom = z;
    this.fit();
  }

  pan(dx, dy) { this.panX += dx; this.panY += dy; this.fit(); }
  rotateView(dir = 1) { this.rot = (this.rot + 4 + dir) % 4; this.fit(); }
  resetView() { this.zoom = 1; this.panX = 0; this.panY = 0; this.fit(); }

  // --- world kind -------------------------------------------------------------
  get kind() {
    if (!this.meta) return 'field';
    if (this.globe) return 'space';
    if (this.meta.channel === 1) return 'city';
    return this.meta.areaZ > 0 ? 'sky' : 'field';
  }

  /** Where a node's antenna is: the point links and pulses attach to. */
  antenna(pos, i) {
    const x = pos[4 * i], y = pos[4 * i + 1], z = pos[4 * i + 2];
    const [px, py] = this.project(x, y, z);
    const k = this.kind;
    const lift = k === 'field' ? ((this.meta.sprites?.[i] || this.meta.sprite) === 'phone' ? 20 : 26) : k === 'city' ? 14 : 4;
    return [px, py - lift * this.spriteScale()];
  }

  /** Node icon size: grows with zoom, within limits, so devices stay legible. */
  spriteScale() { return 1.25 * Math.min(2.2, Math.max(0.8, this.zoom)); }

  /** Index of the node under (px, py), or -1. */
  hit(pos, px, py) {
    let best = -1, bestD = 20 * 20;
    for (let i = 0; i < pos.length / 4; i++) {
      for (const [x, y] of [this.project(pos[4 * i], pos[4 * i + 1], pos[4 * i + 2]), this.antenna(pos, i)]) {
        const d = (x - px) ** 2 + (y - py) ** 2;
        if (d < bestD) { bestD = d; best = i; }
      }
    }
    return best;
  }

  /** The ant in flight under (px, py) -- its flight object -- or null (#637). */
  hitFlight(pos, flights, px, py) {
    let best = null, bestD = 14 * 14;
    for (const f of flights) {
      if (f.kind === 'data' || f.antId === undefined) continue;
      const { x, y } = this.flightAt(pos, f);
      const d = (x - px) ** 2 + (y - py) ** 2;
      if (d < bestD) { bestD = d; best = f; }
    }
    return best;
  }

  /** Link [a, b] under (px, py), or null (for cutting ISLs). */
  hitLink(pos, links, px, py) {
    let best = null, bestD = 8 * 8;
    for (let k = 0; k < links.length; k += 2) {
      const a = this.antenna(pos, links[k]), b = this.antenna(pos, links[k + 1]);
      const dx = b[0] - a[0], dy = b[1] - a[1];
      const t = Math.max(0, Math.min(1, ((px - a[0]) * dx + (py - a[1]) * dy) / (dx * dx + dy * dy || 1)));
      const d = (a[0] + t * dx - px) ** 2 + (a[1] + t * dy - py) ** 2;
      if (d < bestD) { bestD = d; best = [links[k], links[k + 1]]; }
    }
    return best;
  }

  // --- motion (what the renderer infers from successive positions) ------------
  /** Track speed, heading and a short footprint trail per node, in sim time. */
  track(pos, simNow) {
    const n = pos.length / 4;
    const step = Math.max(this.meta.areaX, this.meta.areaY) / 70; // footprint spacing (m)
    for (let i = 0; i < n; i++) {
      const x = pos[4 * i], y = pos[4 * i + 1];
      let m = this.motion[i];
      if (!m || simNow < m.t) m = this.motion[i] = { x, y, t: simNow, speed: 0, dx: 0, dy: 0, trail: [] };
      const dx = x - m.x, dy = y - m.y, d = Math.hypot(dx, dy), dt = simNow - m.t;
      if (dt >= 0.25) {
        m.speed = d / dt;
        if (d > 1e-6) { m.dx = dx / d; m.dy = dy / d; }
        m.x = x; m.y = y; m.t = simNow;
      }
      const last = m.trail[m.trail.length - 1];
      if (!last || Math.hypot(x - last[0], y - last[1]) > step) {
        if (last && Math.hypot(x - last[0], y - last[1]) > step * 6) m.trail.length = 0; // a drag or a wrap
        m.trail.push([x, y]);
        if (m.trail.length > 12) m.trail.shift();
      }
    }
  }

  /** Last measured speed of node i (m/s of simulated time). */
  speedOf(i) { return this.motion?.[i]?.speed || 0; }

  // --- drawing ------------------------------------------------------------------
  draw(s) {
    const { ctx, colors: c } = this;
    if (!this.meta) return;
    this.t = s.time || 0;
    this.drawGround();
    if (s.jams?.length && this.kind !== 'space') this.drawJams(s.jams);
    const pos = s.positions;
    const n = pos.length / 4;
    if (this.kind !== 'space') this.track(pos, s.simNow || 0);
    this.note(s);
    const plan = this.planSprites(s.flights);
    // Per node, this frame: how many radio links it has (the phone's signal
    // bars) and whether a packet was just delivered to it (the tick).
    this.degree = new Uint8Array(n);
    for (let k = 0; k < s.links.length; k++) if (this.degree[s.links[k]] < 255) this.degree[s.links[k]]++;
    this.ticked = new Set();
    for (const m of s.marks) if (m.good && m.progress < 0.75) this.ticked.add(m.node);

    // The selected node's radio range: who can hear it right now.
    if (s.selected >= 0 && s.selected < n && this.kind !== 'space' && this.meta.range > 0) {
      const [px, py] = this.project(pos[4 * s.selected], pos[4 * s.selected + 1], 0);
      const R = this.meta.range * this.c * Math.SQRT2;
      ctx.save();
      ctx.fillStyle = c.accent;
      ctx.globalAlpha = 0.08;
      ctx.beginPath(); ctx.ellipse(px, py, R, R / 2, 0, 0, 2 * Math.PI); ctx.fill();
      ctx.globalAlpha = 0.5;
      ctx.strokeStyle = c.accent;
      ctx.setLineDash([6, 5]);
      ctx.lineWidth = 1.2;
      ctx.stroke();
      ctx.restore();
    }

    // Footprints: where each moving node has just been.
    if (this.kind !== 'space') {
      ctx.save();
      ctx.fillStyle = c.trail;
      for (let i = 0; i < n; i++) {
        const m = this.motion[i];
        if (!m || m.speed < 0.05 || m.trail.length < 2) continue;
        const T = m.trail;
        for (let k = 0; k < T.length - 1; k++) {
          const [px, py] = this.project(T[k][0], T[k][1], 0);
          ctx.globalAlpha = 0.1 + 0.4 * (k / T.length);
          ctx.beginPath(); ctx.ellipse(px, py, 3, 1.5, 0, 0, 2 * Math.PI); ctx.fill();
        }
      }
      ctx.restore();
    }

    // Pheromone trails: a glow per (node -> neighbour) entry toward the watched
    // node, as wide and bright as the pheromone the core holds there.
    if (s.pheromone) {
      // Painted into its own layer when the table is read again (app.js, a
      // few times a second) or the camera moves, and blitted in between.
      const L = this.trailLayer;
      if (!L || L.edges !== s.pheromone || L.camera !== this.camVersion || L.canvas.width !== this.canvas.width || L.canvas.height !== this.canvas.height) {
        const layer = L?.canvas || document.createElement('canvas');
        layer.width = this.canvas.width; layer.height = this.canvas.height; // also clears it
        const g = layer.getContext('2d');
        g.setTransform(this.dpr, 0, 0, this.dpr, 0, 0);
        const saved = this.ctx;
        this.ctx = g;
        this.drawTrails(pos, s.pheromone);
        this.ctx = saved;
        this.trailLayer = { canvas: layer, edges: s.pheromone, camera: this.camVersion };
      }
      ctx.save();
      ctx.setTransform(1, 0, 0, 1, 0, 0);
      ctx.drawImage(this.trailLayer.canvas, 0, 0);
      ctx.restore();
    }

    if (this.globe) this.orbits(pos, s.simNow || 0);

    // Radio beams between antennas.
    if (s.showLinks) {
      ctx.save();
      ctx.strokeStyle = c.beam;
      ctx.globalAlpha = c.night ? 0.45 : 0.55;
      ctx.lineWidth = 1;
      const L = s.links;
      const base = ctx.globalAlpha;
      for (const back of [true, false]) { // links behind the Earth are faint
        ctx.globalAlpha = back ? base * 0.25 : base;
        ctx.beginPath();
        for (let k = 0; k < L.length; k += 2) {
          if ((this.hiddenNode(pos, L[k]) + this.hiddenNode(pos, L[k + 1]) > 0) !== back) continue;
          const a = this.antenna(pos, L[k]), b = this.antenna(pos, L[k + 1]);
          ctx.moveTo(a[0], a[1]);
          ctx.lineTo(b[0], b[1]);
        }
        ctx.stroke();
      }
      ctx.restore();
    }

    if (s.ghostRoutes) this.drawGhostRoutes(pos, s.ghostRoutes);
    if (s.routes) this.drawRoutes(pos, s.routes);
    if (plan.crowd.size) this.drawCrowd(pos, plan.crowd);

    // Broadcast rings on the ground (an isometric circle is a 2:1 ellipse).
    for (const r of s.rings.length > RING_CAP ? s.rings.slice(-RING_CAP) : s.rings) {
      const x = pos[4 * r.node], y = pos[4 * r.node + 1], z = pos[4 * r.node + 2];
      const [px, py] = this.project(x, y, this.kind === 'sky' || this.globe ? z : 0);
      const grow = this.still ? 0.18 : r.progress; // reduced motion: a small ring at the sender that fades, it does not expand
      const R = this.globe ? (6 + 18 * grow) * this.spriteScale()
        : (12 / this.c + grow * r.radius) * this.c * Math.SQRT2;
      ctx.save();
      ctx.globalAlpha = (1 - r.progress) * (r.kind === 'hello' ? 0.35 : 0.45);
      ctx.strokeStyle = c[r.kind];
      ctx.lineWidth = r.kind === 'hello' ? 1 : 1.6;
      ctx.beginPath();
      ctx.ellipse(px, py, R, R / 2, 0, 0, 2 * Math.PI);
      ctx.stroke();
      ctx.restore();
    }

    // Everything standing on the map, back to front: trees/buildings were in
    // the ground layer; nodes sort by depth so nearer ones overlap farther.
    const order = [...Array(n).keys()].sort((i, j) =>
      this.depth(pos[4 * i], pos[4 * i + 1], pos[4 * i + 2]) - this.depth(pos[4 * j], pos[4 * j + 1], pos[4 * j + 2]));
    const flowEnds = new Map();
    for (const f of s.flows) {
      flowEnds.set(f.src, (flowEnds.get(f.src) || '') + ` S${f.id}`);
      flowEnds.set(f.dst, (flowEnds.get(f.dst) || '') + ` D${f.id}`);
    }
    for (const i of order) {
      this.heading(pos, i);
      this.drawNode(pos, i, s, flowEnds.get(i));
    }

    // Ants and crumbs in transit, farthest first. Forward ants keep to one
    // side of the link and backward ants to the other, as on a real trail.
    const sprites = plan.sprites.map((f) => this.flightAt(pos, f)).sort((p, q) => p.y - q.y);
    for (const p of sprites) {
      // Legs step with the distance walked (about one stride per 9 px).
      this.ant(p.f.kind, p.x, p.y, p.ang, this.still ? 0.9 : p.f.progress * p.len / 9 + (p.f.antId || 0), p.f.failed);
    }

    // Floating marks: delivered (✓) and lost (✕), always with a symbol.
    for (const m of s.marks) {
      const [px, py] = this.antenna(pos, m.node);
      ctx.save();
      ctx.globalAlpha = 1 - m.progress;
      ctx.font = `700 ${Math.round(12 * Math.min(1.4, this.zoom))}px system-ui, sans-serif`;
      ctx.fillStyle = m.good ? c.good : c.critical;
      ctx.textAlign = 'center';
      ctx.fillText(m.good ? '✓' : '✕', px, py - 8 - 18 * m.progress);
      ctx.restore();
    }

    if (s.hover >= 0 && s.tool !== 'inspect') {
      const [px, py] = this.project(pos[4 * s.hover], pos[4 * s.hover + 1], 0);
      this.groundDiamond(px, py, 10, c.accent, 0.35);
    }
    if (s.rangeRings) { // campaign planning (#566): every device's reach
      for (const [n, r] of s.rangeRings) this.groundCircle(pos[4 * n], pos[4 * n + 1], r, c.accent, 0.25);
    }
    if (s.ghost) { // build preview
      const [px, py] = this.project(s.ghost[0], s.ghost[1], 0);
      this.groundDiamond(px, py, 12, c.accent, 0.5);
      if (s.ghostRange) this.groundCircle(s.ghost[0], s.ghost[1], s.ghostRange, c.accent, 0.6);
    }
  }

  /** A circle of radius r metres on the ground, as the projection draws it. */
  groundCircle(x, y, r, color, alpha) {
    const { ctx } = this;
    ctx.save();
    ctx.globalAlpha = alpha;
    ctx.strokeStyle = color;
    ctx.lineWidth = 1.5;
    ctx.setLineDash([6, 5]);
    ctx.beginPath();
    for (let k = 0; k <= 48; k++) {
      const a = (k / 48) * 2 * Math.PI;
      const [px, py] = this.project(x + r * Math.cos(a), y + r * Math.sin(a), 0);
      if (k === 0) ctx.moveTo(px, py); else ctx.lineTo(px, py);
    }
    ctx.stroke();
    ctx.restore();
  }

  /** Each flow's strongest pheromone route: a dashed line marching from source
   *  to destination over the trail; in the accent colour for 2 s after it switches. */
  drawRoutes(pos, routes) {
    const { ctx, colors: c } = this;
    const zs = this.spriteScale();
    ctx.save();
    ctx.lineCap = 'round';
    ctx.lineJoin = 'round';
    for (const r of routes) {
      if (r.path.length < 2) continue;
      const pts = r.path.map((i) => (this.kind === 'sky' || this.globe ? this.antenna(pos, i)
        : this.project(pos[4 * i], pos[4 * i + 1], 0)));
      const fresh = this.t - r.changedAt < 2000;
      const trace = () => {
        ctx.beginPath();
        ctx.moveTo(pts[0][0], pts[0][1]);
        for (let k = 1; k < pts.length; k++) ctx.lineTo(pts[k][0], pts[k][1]);
      };
      // A marching dashed line over the trail it follows (the glow stays
      // visible on both sides): the direction packets go.
      ctx.globalAlpha = r.complete ? 0.85 : 0.4;
      ctx.setLineDash([5, 8]);
      ctx.lineDashOffset = this.still ? 0 : -this.t / 45;
      ctx.strokeStyle = c['ant-edge'];
      ctx.lineWidth = (fresh ? 4.4 : 3.4) * zs / 1.25;
      trace(); ctx.stroke();
      ctx.strokeStyle = fresh ? c.accent : c.text;
      ctx.lineWidth = (fresh ? 2.6 : 1.6) * zs / 1.25;
      trace(); ctx.stroke();
    }
    ctx.restore();
  }

  /** The tuning bench's ghost (#638): the same seed at default Config, its
   *  strongest routes drawn thin, dashed and faint under the live ones. */
  drawGhostRoutes(pos, routes) {
    const { ctx, colors: c } = this;
    const zs = this.spriteScale();
    ctx.save();
    ctx.lineCap = 'round';
    ctx.globalAlpha = 0.55;
    ctx.setLineDash([6, 6]);
    ctx.strokeStyle = c.night ? '#cbd5e1' : '#475569';
    ctx.lineWidth = 2 * zs / 1.25;
    for (const r of routes) {
      if (r.path.length < 2) continue;
      const pts = r.path.map((i) => (this.kind === 'sky' || this.globe ? this.antenna(pos, i)
        : this.project(pos[4 * i], pos[4 * i + 1], 0)));
      ctx.beginPath();
      ctx.moveTo(pts[0][0], pts[0][1]);
      for (let k = 1; k < pts.length; k++) ctx.lineTo(pts[k][0], pts[k][1]);
      ctx.stroke();
    }
    ctx.restore();
  }

  /** Where an ant or crumb in flight is drawn: on its link, at its progress
   *  (halfway, standing, under reduced motion), a little to one side. */
  flightAt(pos, f) {
    const [a, b] = this.trailEnds(pos, f.from, f.to);
    const ang = Math.atan2(b[1] - a[1], b[0] - a[0]);
    const u = this.still ? 0.5 : (f.progress || 0);
    const side = f.kind === 'data' ? 0 : f.kind === 'backward' ? -4.5 : 4.5;
    return { f, ang, x: a[0] + (b[0] - a[0]) * u - Math.sin(ang) * side, y: a[1] + (b[1] - a[1]) * u + Math.cos(ang) * side,
      len: Math.hypot(b[0] - a[0], b[1] - a[1]) };
  }

  /** #94: count what draw() was handed, each transmission once. A flight made
   *  from a broadcast's reception (`echo`) is the same ant as its ring. */
  note(s) {
    for (const list of [s.flights, s.rings]) {
      for (const f of list) {
        if (f.echo || this.seen.has(f)) continue;
        this.seen.add(f);
        this.asked[f.kind] = (this.asked[f.kind] || 0) + 1;
      }
    }
  }

  /** #94: the newest SPRITE_CAP flights get a sprite; the rest are counted per
   *  link and drawn as density on it. */
  planSprites(flights) {
    const sprites = [], crowd = new Map();
    for (let k = flights.length - 1; k >= 0; k--) {
      const f = flights[k];
      if (sprites.length < SPRITE_CAP) { sprites.push(f); continue; }
      const key = f.from < f.to ? f.from * 65536 + f.to : f.to * 65536 + f.from;
      const on = crowd.get(key);
      if (on) on.count++; else crowd.set(key, { count: 1, kind: f.kind });
    }
    this.frameStats = { sprites: sprites.length, overflow: flights.length - sprites.length };
    return { sprites, crowd };
  }

  /** Ants beyond the sprite budget: marching dots on their link, denser the
   *  more there are. */
  drawCrowd(pos, crowd) {
    const { ctx, colors: c } = this;
    ctx.save();
    ctx.lineWidth = 2.6 * Math.min(1.5, Math.max(0.8, this.zoom));
    for (const [key, { count, kind }] of crowd) {
      ctx.strokeStyle = c[kind]; // the newest ant waiting on this link
      const [a, b] = this.trailEnds(pos, Math.floor(key / 65536), key % 65536);
      ctx.globalAlpha = Math.min(0.9, 0.45 + 0.1 * count);
      ctx.setLineDash([2.6, Math.max(3, 10 - count)]);
      ctx.lineDashOffset = this.still ? 0 : -this.t / 30;
      ctx.beginPath(); ctx.moveTo(a[0], a[1]); ctx.lineTo(b[0], b[1]); ctx.stroke();
    }
    ctx.restore();
  }

  /** #94: the pheromone toward the watched node and toward each flow's
   *  destination, one tapering glow per (holder -> neighbour) entry: wide at
   *  the node that holds the entry, narrower toward the neighbour it points
   *  to. Width and brightness follow the regular pheromone, on a scale fixed
   *  by the largest value seen in this world, so a trail that evaporates
   *  fades. Entries toward the watched node are drawn in full, the others
   *  lighter; the watched node's virtual pheromone (hello diffusion) is a
   *  dotted line beside its link. */
  drawTrails(pos, edges) {
    const { ctx, colors: c } = this;
    let peak = this.phPeak || 0;
    for (const e of edges) peak = Math.max(peak, e.reg, e.virt);
    this.phPeak = peak;
    if (!(peak > 0)) return;
    const zf = Math.min(1.5, Math.max(0.8, this.zoom));
    // Six steps of strength, compressed so weak trails still show. Entries of
    // one step and one dimming share a path, so a busy world costs a few
    // dozen fills, not thousands.
    const STEPS = 6;
    const step = (tau) => Math.max(1, Math.ceil(Math.pow(tau / peak, 0.6) * STEPS));
    const glow = new Map(), core = new Map();
    const bucket = (map, q, dim) => {
      const key = q * 8 + dim;
      let p = map.get(key);
      if (!p) map.set(key, p = { q, dim, path: new Path2D() });
      return p.path;
    };
    for (const e of edges) {
      const [a, b] = this.trailEnds(pos, e.from, e.to);
      const dx = b[0] - a[0], dy = b[1] - a[1], L = Math.hypot(dx, dy) || 1;
      const nx = -dy / L, ny = dx / L;
      // 0: watched, in view; 1: another flow's; 2, 3: the same two behind the Earth.
      const dim = (e.watched ? 0 : 1) + (this.globe && this.hiddenNode(pos, e.from) ? 2 : 0);
      let half = 0;
      if (e.reg > 0) {
        const q = step(e.reg);
        half = (0.8 + 3.4 * q / STEPS) * zf;
        for (const [grow, map] of [[2.1, glow], [1, core]]) {
          const h0 = half * grow, h1 = h0 * 0.6;
          const p = bucket(map, q, dim + (grow === 1 ? 4 : 0));
          p.moveTo(a[0] + nx * h0, a[1] + ny * h0); p.lineTo(b[0] + nx * h1, b[1] + ny * h1);
          p.lineTo(b[0] - nx * h1, b[1] - ny * h1); p.lineTo(a[0] - nx * h0, a[1] - ny * h0);
          p.closePath();
        }
      }
      if (e.virt > 0 && e.watched) {
        const off = half + 2.5 * zf;
        const p = bucket(core, 0, dim);
        p.moveTo(a[0] + nx * off, a[1] + ny * off);
        p.lineTo(a[0] + dx * 0.9 + nx * off, a[1] + dy * 0.9 + ny * off);
      }
    }
    const DIM = [1, 0.7, 0.2, 0.15];
    ctx.save();
    for (const { q, dim, path } of glow.values()) {
      ctx.globalAlpha = (0.25 + 0.6 * q / STEPS) * DIM[dim];
      ctx.fillStyle = c['ph-glow'];
      ctx.fill(path);
    }
    for (const { q, dim, path } of core.values()) {
      if (q) { // the trail itself
        ctx.globalAlpha = (0.4 + 0.6 * q / STEPS) * DIM[dim - 4];
        ctx.fillStyle = c['ph-trail'];
        ctx.fill(path);
      } else { // virtual pheromone: dotted, beside the link
        ctx.globalAlpha = 0.75 * DIM[dim];
        ctx.strokeStyle = c['ph-virtual'];
        ctx.lineWidth = 1.6 * zf;
        ctx.setLineDash([1.6 * zf, 4.5 * zf]);
        ctx.stroke(path);
        ctx.setLineDash([]);
      }
    }
    ctx.restore();
  }

  /** A small ground chevron ahead of a moving node, pointing where it walks. */
  heading(pos, i) {
    const m = this.motion[i];
    if (!m || m.speed < 0.05 || this.kind === 'space') return;
    const { ctx, colors: c } = this;
    const x = pos[4 * i], y = pos[4 * i + 1];
    const L = 16 / this.c, W = 5 / this.c;
    const tip = this.project(x + m.dx * (L + 6 / this.c), y + m.dy * (L + 6 / this.c), 0);
    const l = this.project(x + m.dx * L - m.dy * W, y + m.dy * L + m.dx * W, 0);
    const r = this.project(x + m.dx * L + m.dy * W, y + m.dy * L - m.dx * W, 0);
    ctx.save();
    ctx.globalAlpha = 0.7;
    ctx.fillStyle = c.accent;
    ctx.beginPath(); ctx.moveTo(tip[0], tip[1]); ctx.lineTo(l[0], l[1]); ctx.lineTo(r[0], r[1]); ctx.closePath(); ctx.fill();
    ctx.restore();
  }

  trailEnds(pos, a, b) {
    if (this.kind === 'sky' || this.kind === 'space') return [this.antenna(pos, a), this.antenna(pos, b)];
    return [this.project(pos[4 * a], pos[4 * a + 1], 0), this.project(pos[4 * b], pos[4 * b + 1], 0)];
  }

  groundDiamond(px, py, r, color, alpha) {
    const { ctx } = this;
    ctx.save();
    ctx.globalAlpha = alpha;
    ctx.fillStyle = color;
    ctx.beginPath();
    ctx.moveTo(px, py - r / 2); ctx.lineTo(px + r, py); ctx.lineTo(px, py + r / 2); ctx.lineTo(px - r, py);
    ctx.closePath();
    ctx.fill();
    ctx.restore();
  }

  // --- ground layer (cached: it only changes with the camera) ------------------
  drawGround() {
    const { ctx } = this;
    if (!this.groundCache) {
      const off = document.createElement('canvas');
      off.width = this.canvas.width;
      off.height = this.canvas.height;
      const g = off.getContext('2d');
      g.setTransform(this.dpr, 0, 0, this.dpr, 0, 0);
      const saved = this.ctx;
      this.ctx = g;
      this.paintGround();
      this.ctx = saved;
      this.groundCache = off;
    }
    ctx.save();
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.drawImage(this.groundCache, 0, 0);
    ctx.restore();
  }

  tile(x0, y0, x1, y1, fill, edge) {
    const { ctx } = this;
    const p = [this.project(x0, y0), this.project(x1, y0), this.project(x1, y1), this.project(x0, y1)];
    ctx.beginPath();
    ctx.moveTo(p[0][0], p[0][1]);
    for (let k = 1; k < 4; k++) ctx.lineTo(p[k][0], p[k][1]);
    ctx.closePath();
    ctx.fillStyle = fill;
    ctx.fill();
    if (edge) { ctx.strokeStyle = edge; ctx.lineWidth = 0.5; ctx.stroke(); }
  }

  paintGround() {
    const { ctx, colors: c, meta } = this;
    const W = meta.areaX, H = meta.areaY;
    if (this.kind === 'space') {
      ctx.fillStyle = c.space;
    } else {
      const g = ctx.createLinearGradient(0, 0, 0, this.h);
      g.addColorStop(0, c['sky-top']);
      g.addColorStop(1, c.sky);
      ctx.fillStyle = g;
    }
    ctx.fillRect(0, 0, this.w, this.h);

    if (this.kind === 'space') {
      // Starfield, then the Earth.
      for (let k = 0; k < 220; k++) {
        const x = hash2(k, 1) * this.w, y = hash2(k, 2) * this.h, r = hash2(k, 3);
        ctx.fillStyle = c.star;
        ctx.globalAlpha = 0.3 + 0.7 * r;
        ctx.fillRect(x, y, r > 0.9 ? 2 : 1, r > 0.9 ? 2 : 1);
      }
      ctx.globalAlpha = 1;
      this.earth();
      return;
    }

    // Grass tiles with a little per-tile variation and a faint build grid,
    // plus the slab edge for depth.
    const nT = 20;
    const tx = W / nT, ty = H / nT;
    this.slab();
    const grid = c.night ? 'rgba(255,255,255,0.05)' : 'rgba(0,0,0,0.06)';
    for (let i = 0; i < nT; i++) {
      for (let j = 0; j < nT; j++) {
        this.tile(i * tx, j * ty, (i + 1) * tx, (j + 1) * ty, hash2(i + 3, j + 5) < 0.5 ? c['grass-a'] : c['grass-b'], grid);
      }
    }

    if (this.kind === 'city') {
      // Streets (centre lines of the block grid), then the buildings.
      // Roads are drawn wider than the radio model's street (and buildings
      // inset to match) so cars read at map scale; the radio still uses the
      // real street width for line of sight.
      const bw = W / meta.blocksX, bh = H / meta.blocksY, sw = Math.max(meta.streetWidth * 2.5, bw * 0.16);
      for (let i = 0; i <= meta.blocksX; i++) this.tile(i * bw - sw / 2, 0, i * bw + sw / 2, H, c.road);
      for (let j = 0; j <= meta.blocksY; j++) this.tile(0, j * bh - sw / 2, W, j * bh + sw / 2, c.road);
      const blocks = [];
      for (let i = 0; i < meta.blocksX; i++) for (let j = 0; j < meta.blocksY; j++) blocks.push([i, j]);
      blocks.sort((a, b) => this.depth(a[0] * bw, a[1] * bh) - this.depth(b[0] * bw, b[1] * bh));
      for (const [i, j] of blocks) {
        const h = 12 + 28 * hash2(i, j);
        this.box(i * bw + sw / 2, j * bh + sw / 2, (i + 1) * bw - sw / 2, (j + 1) * bh - sw / 2, h, hash2(j, i));
      }
      return;
    }

    // #575: attenuation zones (canopy) as dark ground with dense trees.
    const zones = this.zonePolys();
    for (const z of zones) {
      ctx.beginPath();
      z.forEach(([x, y], k) => { const [px, py] = this.project(x, y, 0); if (k) ctx.lineTo(px, py); else ctx.moveTo(px, py); });
      ctx.closePath();
      ctx.fillStyle = c.night ? 'rgba(0,40,10,0.45)' : 'rgba(20,90,30,0.35)';
      ctx.fill();
    }
    const inZone = (x, y) => zones.some((z) => {
      let inside = false;
      for (let a = 0, b = z.length - 1; a < z.length; b = a++) {
        const [xa, ya] = z[a], [xb, yb] = z[b];
        if ((ya > y) !== (yb > y) && x < (xb - xa) * (y - ya) / (yb - ya) + xa) inside = !inside;
      }
      return inside;
    });

    // Trees on a deterministic sprinkle of tiles (decoration only); dense
    // inside a canopy zone.
    const trees = [];
    for (let i = 0; i < nT; i++) {
      for (let j = 0; j < nT; j++) {
        const x = (i + 0.3 + 0.4 * hash2(i, j)) * tx, y = (j + 0.3 + 0.4 * hash2(j, i)) * ty;
        if (hash2(i + 7, j + 13) < (inZone(x, y) ? 0.8 : 0.09)) trees.push([x, y]);
      }
    }
    trees.sort((a, b) => this.depth(a[0], a[1]) - this.depth(b[0], b[1]));
    for (const [x, y] of trees) this.tree(x, y);
  }

  /** #582: the jamming zones active now (a jammer, a fire front), from the
   *  flat [n, x0, y0, ...] list, shaded and clipped to the field. */
  drawJams(f) {
    const { ctx, colors: c, meta } = this;
    const path = (pts) => {
      ctx.beginPath();
      pts.forEach(([x, y], k) => { const [px, py] = this.project(x, y, 0); if (k) ctx.lineTo(px, py); else ctx.moveTo(px, py); });
      ctx.closePath();
    };
    ctx.save();
    path([[0, 0], [meta.areaX, 0], [meta.areaX, meta.areaY], [0, meta.areaY]]);
    ctx.clip();
    for (let k = 0; k < f.length;) {
      const n = f[k];
      const poly = [];
      for (let j = 0; j < n; j++) poly.push([f[k + 1 + 2 * j], f[k + 2 + 2 * j]]);
      k += 1 + 2 * n;
      path(poly);
      ctx.fillStyle = c.critical;
      ctx.globalAlpha = c.night ? 0.35 : 0.3;
      ctx.fill();
      ctx.globalAlpha = 0.8;
      ctx.strokeStyle = c.critical;
      ctx.setLineDash([6, 4]);
      ctx.lineWidth = 1.5;
      ctx.stroke();
      ctx.setLineDash([]);
    }
    ctx.restore();
  }

  /** #575: the world's attenuation zones as [[x, y], ...] polygons. */
  zonePolys() {
    const f = this.meta.zones || [];
    const out = [];
    for (let k = 0; k < f.length;) {
      const n = f[k + 1];
      const poly = [];
      for (let j = 0; j < n; j++) poly.push([f[k + 2 + 2 * j], f[k + 3 + 2 * j]]);
      out.push(poly);
      k += 2 + 2 * n;
    }
    return out;
  }

  /** The Earth: a lit ocean sphere, an atmosphere rim and a graticule
   *  (front half only). It does not rotate: orbits are drawn inertially. */
  earth() {
    const { ctx } = this;
    const R = EARTH_R * this.c, cx = this.ox, cy = this.oy;
    const glow = ctx.createRadialGradient(cx, cy, R * 0.95, cx, cy, R * 1.12);
    glow.addColorStop(0, 'rgba(125, 211, 252, 0.45)');
    glow.addColorStop(1, 'rgba(125, 211, 252, 0)');
    ctx.fillStyle = glow;
    ctx.beginPath(); ctx.arc(cx, cy, R * 1.12, 0, 2 * Math.PI); ctx.fill();
    const g = ctx.createRadialGradient(cx - R * 0.35, cy - R * 0.4, R * 0.1, cx, cy, R);
    g.addColorStop(0, '#3b82c4');
    g.addColorStop(0.7, '#1e4f8f');
    g.addColorStop(1, '#0c2347');
    ctx.fillStyle = g;
    ctx.beginPath(); ctx.arc(cx, cy, R, 0, 2 * Math.PI); ctx.fill();
    ctx.save();
    ctx.strokeStyle = 'rgba(255, 255, 255, 0.16)';
    ctx.lineWidth = 0.8;
    const X0 = this.meta.areaX / 2, Y0 = this.meta.areaY / 2;
    const line = (pt) => { // a closed curve on the sphere, front half only
      ctx.beginPath();
      let pen = false;
      for (let k = 0; k <= 96; k++) {
        const [x, y, z] = pt(2 * Math.PI * k / 96);
        if (this.depth(X0 + x, Y0 + y, z) < 0) { pen = false; continue; }
        const [px, py] = this.project(X0 + x, Y0 + y, z);
        if (pen) ctx.lineTo(px, py); else ctx.moveTo(px, py);
        pen = true;
      }
      ctx.stroke();
    };
    for (const lat of [-60, -30, 0, 30, 60]) {
      const f = lat * Math.PI / 180, r = EARTH_R * Math.cos(f), z = EARTH_R * Math.sin(f);
      line((t) => [r * Math.cos(t), r * Math.sin(t), z]);
    }
    for (let lon = 0; lon < 180; lon += 30) {
      const f = lon * Math.PI / 180;
      line((t) => [EARTH_R * Math.cos(t) * Math.cos(f), EARTH_R * Math.cos(t) * Math.sin(f), EARTH_R * Math.sin(t)]);
    }
    ctx.restore();
  }

  /** Orbit rings, one per orbital plane, recovered from two position samples
   *  (normal = r x dr): satellites that share a ring share an orbit. */
  orbits(pos, simNow) {
    const { ctx, colors: c } = this;
    const n = pos.length / 4, X0 = this.meta.areaX / 2, Y0 = this.meta.areaY / 2;
    if (!this.rings) {
      if (!this.orbitSample) { this.orbitSample = { t: simNow, pos: Array.from(pos) }; return; }
      if (simNow - this.orbitSample.t < 0.5) return;
      const P = this.orbitSample.pos, rings = [];
      for (let i = 0; i < n; i++) {
        const r = [P[4 * i] - X0, P[4 * i + 1] - Y0, P[4 * i + 2]];
        const d = [pos[4 * i] - P[4 * i], pos[4 * i + 1] - P[4 * i + 1], pos[4 * i + 2] - P[4 * i + 2]];
        let nv = [r[1] * d[2] - r[2] * d[1], r[2] * d[0] - r[0] * d[2], r[0] * d[1] - r[1] * d[0]];
        const L = Math.hypot(...nv);
        if (!L) continue;
        nv = nv.map((v) => v / L);
        if (rings.some((q) => q.n[0] * nv[0] + q.n[1] * nv[1] + q.n[2] * nv[2] > 0.999)) continue;
        rings.push({ n: nv, R: Math.hypot(...r) });
      }
      this.rings = rings;
    }
    ctx.save();
    ctx.strokeStyle = c.night ? c.star : c.beam;
    ctx.lineWidth = 1;
    for (const { n: nv, R } of this.rings) {
      // e1 perpendicular to the normal, e2 = n x e1.
      const t = Math.abs(nv[2]) < 0.9 ? [0, 0, 1] : [1, 0, 0];
      let e1 = [nv[1] * t[2] - nv[2] * t[1], nv[2] * t[0] - nv[0] * t[2], nv[0] * t[1] - nv[1] * t[0]];
      const L1 = Math.hypot(...e1); e1 = e1.map((v) => v / L1);
      const e2 = [nv[1] * e1[2] - nv[2] * e1[1], nv[2] * e1[0] - nv[0] * e1[2], nv[0] * e1[1] - nv[1] * e1[0]];
      let prev = null;
      for (let k = 0; k <= 120; k++) {
        const a = 2 * Math.PI * k / 120, ca = Math.cos(a) * R, sa = Math.sin(a) * R;
        const x = X0 + e1[0] * ca + e2[0] * sa, y = Y0 + e1[1] * ca + e2[1] * sa, z = e1[2] * ca + e2[2] * sa;
        const p = this.project(x, y, z);
        if (prev) {
          ctx.globalAlpha = this.hidden(x, y, z) ? 0.08 : 0.4;
          ctx.beginPath(); ctx.moveTo(prev[0], prev[1]); ctx.lineTo(p[0], p[1]); ctx.stroke();
        }
        prev = p;
      }
    }
    ctx.restore();
  }

  slab() {
    const { ctx, colors: c } = this;
    // The two visible sides depend on rotation; in (u, v) the near corner is (U, V).
    const [U, V] = this.dims();
    const near = this.project(...this.unrotate(U, V));
    const left = this.project(...this.unrotate(0, V));
    const right = this.project(...this.unrotate(U, 0));
    const th = 18; // slab thickness, constant on screen
    // Two faces, two shades: the light falls from the right.
    for (const [a, fill] of [[left, c['grass-edge']], [right, c['slab-right']]]) {
      ctx.fillStyle = fill;
      ctx.beginPath();
      ctx.moveTo(a[0], a[1]); ctx.lineTo(near[0], near[1]);
      ctx.lineTo(near[0], near[1] + th); ctx.lineTo(a[0], a[1] + th);
      ctx.closePath();
      ctx.fill();
    }
  }

  box(x0, y0, x1, y1, h, seed) {
    const { ctx, colors: c } = this;
    const P = (x, y, z) => this.project(x, y, z);
    // Faces facing the viewer depend on rotation: draw the two "front" walls.
    const corners = [[x0, y0], [x1, y0], [x1, y1], [x0, y1]];
    const rc = corners.map(([x, y]) => this.rotate(x, y));
    let iNear = 0;
    for (let k = 1; k < 4; k++) if (rc[k][0] + rc[k][1] > rc[iNear][0] + rc[iNear][1]) iNear = k;
    const prev = corners[(iNear + 3) % 4], near = corners[iNear], next = corners[(iNear + 1) % 4];
    const wall = (a, b, fill) => {
      const p0 = P(a[0], a[1], 0), p1 = P(b[0], b[1], 0), p2 = P(b[0], b[1], h), p3 = P(a[0], a[1], h);
      ctx.beginPath();
      ctx.moveTo(p0[0], p0[1]); ctx.lineTo(p1[0], p1[1]); ctx.lineTo(p2[0], p2[1]); ctx.lineTo(p3[0], p3[1]);
      ctx.closePath();
      ctx.fillStyle = fill;
      ctx.fill();
      // Window rows.
      const rows = Math.max(1, Math.floor(h / 8)), cols = 4;
      for (let r = 0; r < rows; r++) {
        for (let q = 0; q < cols; q++) {
          const lit = c.night && hash2(r * 7 + q, Math.floor(seed * 1000)) > 0.45;
          const fx = (q + 0.3) / cols, fz = (r + 0.35) / rows;
          const wx = a[0] + (b[0] - a[0]) * fx, wy = a[1] + (b[1] - a[1]) * fx;
          const [px, py] = P(wx, wy, h * fz);
          ctx.fillStyle = lit ? c['window-lit'] : c.window;
          ctx.fillRect(px - 1.2, py - 2, 2.4, 3);
        }
      }
    };
    wall(prev, near, c['bldg-left']);
    wall(near, next, c['bldg-right']);
    const top = corners.map(([x, y]) => P(x, y, h));
    ctx.beginPath();
    ctx.moveTo(top[0][0], top[0][1]);
    for (let k = 1; k < 4; k++) ctx.lineTo(top[k][0], top[k][1]);
    ctx.closePath();
    ctx.fillStyle = c['bldg-top'];
    ctx.fill();
  }

  tree(x, y) {
    const { ctx, colors: c } = this;
    const [px, py] = this.project(x, y);
    const s = Math.max(3, Math.min(9, this.c * 9));
    ctx.fillStyle = c.trunk;
    ctx.fillRect(px - 1, py - s * 0.6, 2, s * 0.6);
    ctx.fillStyle = c['tree-dark'];
    ctx.beginPath(); ctx.arc(px, py - s * 1.1, s * 0.7, 0, 2 * Math.PI); ctx.fill();
    ctx.fillStyle = c.tree;
    ctx.beginPath(); ctx.arc(px - s * 0.2, py - s * 1.25, s * 0.45, 0, 2 * Math.PI); ctx.fill();
  }

  // --- sprites -----------------------------------------------------------------
  drawNode(pos, i, s, label) {
    const { ctx, colors: c } = this;
    const x = pos[4 * i], y = pos[4 * i + 1], z = pos[4 * i + 2];
    const up = pos[4 * i + 3] > 0;
    const [bx, by] = this.project(x, y, this.globe ? z : 0);
    const [ax, ay] = this.antenna(pos, i);
    const k = this.kind;
    const zs = this.spriteScale();
    const body = up ? c.tower : c['node-off'];
    const flash = s.flash && s.flash.get(i);
    ctx.save();
    if (this.hidden(x, y, z)) ctx.globalAlpha = 0.3; // behind the Earth

    if (i === s.selected) {
      if (this.globe) {
        ctx.strokeStyle = c.accent; ctx.lineWidth = 2;
        ctx.beginPath(); ctx.arc(ax, ay, 14 * zs, 0, 2 * Math.PI); ctx.stroke();
      } else this.groundDiamond(bx, by, 16 * zs, c.accent, 0.45);
    }

    // #575: a device class may override the world's default body -- a
    // roadside unit in the city, a ranger radio under the drones, a ground
    // station under the shell. Worlds without sprites draw as before.
    const own = this.meta.sprites?.[i];
    if (own === 'tower' && k !== 'space') this.router(bx, by, ay, up, zs);
    else if ((own === 'tower' || own === 'phone') && k === 'space') this.station(ax, ay, up, zs);
    else if (own === 'drone' && k === 'space') this.drone(bx, by, ax, ay, up, zs, i);  // #585: a HAPS
    else if (k === 'sky' && own !== 'phone') this.drone(bx, by, ax, ay, up, zs, i);
    else if (k === 'space') this.satellite(ax, ay, up, zs);
    else if (k === 'city') this.car(pos, i, up, zs);
    else if ((own || this.meta.sprite) === 'phone') this.phone(bx, by, i, up, zs);
    else this.router(bx, by, ay, up, zs);

    // Antenna light: lit in the colour of whatever it just transmitted.
    ctx.beginPath();
    ctx.arc(ax, ay, (flash ? 2.8 : 1.6) * zs / 1.25, 0, 2 * Math.PI);
    ctx.fillStyle = flash ? c[flash] : (up ? c.critical : c['node-off']);
    ctx.fill();
    if (!up) {
      ctx.strokeStyle = c.critical;
      ctx.lineWidth = 2;
      ctx.beginPath();
      ctx.moveTo(bx - 4, by - 10); ctx.lineTo(bx + 4, by - 2);
      ctx.moveTo(bx + 4, by - 10); ctx.lineTo(bx - 4, by - 2);
      ctx.stroke();
    }

    if (s.labels || label || i === s.selected) {
      ctx.font = `${label ? 700 : 400} ${Math.round(10 * Math.min(1.3, zs))}px system-ui, sans-serif`;
      ctx.textAlign = 'left';
      const text = String(i) + (label || '');
      const tx = ax + 6, ty = ay - 4;
      ctx.lineWidth = 3;
      ctx.strokeStyle = c.night ? 'rgba(0,0,0,0.6)' : 'rgba(255,255,255,0.75)';
      ctx.strokeText(text, tx, ty);
      ctx.fillStyle = c.text;
      ctx.fillText(text, tx, ty);
    }
    ctx.restore();
  }

  /** A mobile phone, standing: bezel with a side edge, a light screen, an
   *  earpiece. No face. Its state shows in shape as well as colour: signal
   *  bars while it is up (one per radio link it has now, up to four), a tick
   *  while a packet is being delivered to it, and switched off it lies on its
   *  side with a dark screen (drawNode adds the cross). */
  phone(bx, by, i, up, zs) {
    const { ctx, colors: c } = this;
    this.shadowAt(bx, by, 7 * zs, 0.22);
    // A carried phone bobs with its walker's step.
    const walking = up && !this.still && (this.motion[i]?.speed || 0) > 0.05;
    const bob = walking ? Math.abs(Math.sin(this.t / 140 + i)) * 2 * zs : 0;
    const w = 10.5 * zs, h = 18 * zs, t = 2 * zs;
    const ticked = up && this.ticked?.has(i);
    ctx.save();
    ctx.translate(bx, by - 2 * zs - bob);
    if (!up) { ctx.translate(-3 * zs, -1 * zs); ctx.rotate(1.3); }
    const body = up ? c['dev-2'] : c['dev-down'];
    ctx.fillStyle = body;
    ctx.beginPath(); // side edge, receding up-right
    ctx.moveTo(w / 2 - 1, -h + 2 * zs); ctx.lineTo(w / 2 + t, -h + 2 * zs - t / 2);
    ctx.lineTo(w / 2 + t, -2 * zs - t / 2); ctx.lineTo(w / 2 - 1, -2 * zs);
    ctx.closePath(); ctx.fill();
    ctx.fillStyle = c.shadow; ctx.globalAlpha = 0.28; ctx.fill(); ctx.globalAlpha = 1;
    ctx.beginPath(); ctx.roundRect(-w / 2, -h, w, h, 2.6 * zs);
    ctx.fillStyle = body; ctx.fill();
    ctx.lineWidth = 1; ctx.strokeStyle = c['ant-edge']; ctx.globalAlpha = 0.7; ctx.stroke(); ctx.globalAlpha = 1;
    const sx = -w / 2 + 1.3 * zs, sy = -h + 2.4 * zs, sw = w - 2.6 * zs, sh = h - 5 * zs;
    ctx.beginPath(); ctx.roundRect(sx, sy, sw, sh, 1.4 * zs);
    ctx.fillStyle = !up ? c.shadow : ticked ? c.good : c['dev-screen'];
    ctx.globalAlpha = up ? 1 : 0.45; ctx.fill(); ctx.globalAlpha = 1;
    ctx.fillStyle = c['dev-screen']; ctx.globalAlpha = up ? 0.85 : 0.4;
    ctx.fillRect(-1.6 * zs, -h + 1 * zs, 3.2 * zs, 0.7 * zs); // earpiece
    ctx.globalAlpha = 1;
    if (ticked) {
      ctx.strokeStyle = c['dev-screen']; ctx.lineWidth = 1.6 * zs; ctx.lineCap = 'round'; ctx.lineJoin = 'round';
      const my = sy + sh / 2;
      ctx.beginPath(); ctx.moveTo(-2.6 * zs, my); ctx.lineTo(-0.7 * zs, my + 2.1 * zs); ctx.lineTo(2.8 * zs, my - 2.4 * zs); ctx.stroke();
    } else if (up) {
      const lit = Math.min(4, this.degree?.[i] || 0);
      for (let q = 0; q < 4; q++) {
        const bh = (1.8 + q * 1.7) * zs;
        ctx.fillStyle = q < lit ? c.dev : c['dev-down'];
        ctx.globalAlpha = q < lit ? 1 : 0.4;
        ctx.fillRect(-3.7 * zs + q * 2 * zs, sy + sh - 1.6 * zs - bh, 1.4 * zs, bh);
      }
      ctx.globalAlpha = 1;
    }
    ctx.restore();
  }

  /** #575: a ground station on the globe: a dish on a small mast. */
  station(ax, ay, up, zs) {
    const { ctx, colors: c } = this;
    ctx.fillStyle = up ? c.tower : c['node-off'];
    ctx.fillRect(ax - 1 * zs, ay, 2 * zs, 7 * zs);
    ctx.beginPath();
    ctx.arc(ax, ay, 5 * zs, Math.PI * 1.1, Math.PI * 1.9);
    ctx.lineWidth = 2 * zs;
    ctx.strokeStyle = up ? c.accent : c['node-off'];
    ctx.stroke();
  }

  /** A screen-space isometric cube: ground centre (cx, cy), half-width a,
   *  height h, raised by e; faces top / left / right. */
  cube(cx, cy, a, h, e, top, left, right) {
    const { ctx } = this;
    const y0 = cy - e, y1 = cy - e - h;
    const face = (pts, fill) => {
      ctx.beginPath();
      ctx.moveTo(pts[0][0], pts[0][1]);
      for (let k = 1; k < pts.length; k++) ctx.lineTo(pts[k][0], pts[k][1]);
      ctx.closePath();
      ctx.fillStyle = fill;
      ctx.fill();
    };
    face([[cx - a, y1], [cx, y1 + a / 2], [cx, y0 + a / 2], [cx - a, y0]], left);
    face([[cx, y1 + a / 2], [cx + a, y1], [cx + a, y0], [cx, y0 + a / 2]], right);
    face([[cx, y1 - a / 2], [cx + a, y1], [cx, y1 + a / 2], [cx - a, y1]], top);
  }

  shadowAt(x, y, rx, alpha = 0.22) {
    const { ctx, colors: c } = this;
    ctx.save();
    ctx.globalAlpha = alpha;
    ctx.fillStyle = c.shadow;
    ctx.beginPath(); ctx.ellipse(x, y, rx, rx / 2, 0, 0, 2 * Math.PI); ctx.fill();
    ctx.restore();
  }

  /** Quadcopter: ground shadow and plumb line, X frame, four spinning rotors. */
  drone(bx, by, ax, ay, up, zs, i) {
    const { ctx, colors: c } = this;
    this.shadowAt(bx, by, 8 * zs, 0.25);
    ctx.save();
    ctx.globalAlpha = 0.18;
    ctx.strokeStyle = c.shadow;
    ctx.setLineDash([2, 3]);
    ctx.beginPath(); ctx.moveTo(bx, by); ctx.lineTo(ax, ay + 4 * zs); ctx.stroke();
    ctx.restore();
    const cy = ay + 4 * zs, body = up ? c.tower : c['node-off'];
    const arms = [[-8, -4], [8, -4], [8, 4], [-8, 4]];
    ctx.strokeStyle = body;
    ctx.lineWidth = 2 * zs;
    ctx.lineCap = 'round';
    ctx.beginPath();
    ctx.moveTo(ax + arms[0][0] * zs, cy + arms[0][1] * zs); ctx.lineTo(ax + arms[2][0] * zs, cy + arms[2][1] * zs);
    ctx.moveTo(ax + arms[1][0] * zs, cy + arms[1][1] * zs); ctx.lineTo(ax + arms[3][0] * zs, cy + arms[3][1] * zs);
    ctx.stroke();
    const spin = up && !this.still ? (this.t / 40 + i) % (2 * Math.PI) : 0.6;
    for (const [dx, dy] of arms) {
      const rx = ax + dx * zs, ry = cy + dy * zs - 1.5 * zs;
      ctx.fillStyle = body;
      ctx.globalAlpha = 0.18;
      ctx.beginPath(); ctx.ellipse(rx, ry, 5 * zs, 2.5 * zs, 0, 0, 2 * Math.PI); ctx.fill();
      ctx.globalAlpha = 0.9;
      ctx.lineWidth = 1.2 * zs;
      ctx.beginPath();
      ctx.moveTo(rx - Math.cos(spin) * 5 * zs, ry - Math.sin(spin) * 2.5 * zs);
      ctx.lineTo(rx + Math.cos(spin) * 5 * zs, ry + Math.sin(spin) * 2.5 * zs);
      ctx.stroke();
      ctx.globalAlpha = 1;
    }
    ctx.beginPath();
    ctx.roundRect(ax - 4 * zs, cy - 3 * zs, 8 * zs, 6 * zs, 2 * zs);
    ctx.fillStyle = body;
    ctx.fill();
    ctx.lineCap = 'butt';
  }

  /** Satellite: gold-foil bus, two ribbed solar wings on a boom, a dish. */
  satellite(ax, ay, up, zs) {
    const { ctx, colors: c } = this;
    const panel = up ? c['panel-blue'] : c['node-off'];
    ctx.strokeStyle = up ? c.star : c['node-off'];
    ctx.lineWidth = 1;
    ctx.beginPath(); ctx.moveTo(ax - 7 * zs, ay); ctx.lineTo(ax + 7 * zs, ay); ctx.stroke();
    for (const side of [-1, 1]) {
      // A wing: a parallelogram (the panel seen at the isometric angle) with cell ribs.
      const x0 = ax + side * 7 * zs, x1 = ax + side * 19 * zs;
      const P = [[x0, ay - 4 * zs], [x1, ay - 4 * zs + side * 2 * zs], [x1, ay + 4 * zs + side * 2 * zs], [x0, ay + 4 * zs]];
      ctx.beginPath();
      ctx.moveTo(P[0][0], P[0][1]);
      for (let k = 1; k < 4; k++) ctx.lineTo(P[k][0], P[k][1]);
      ctx.closePath();
      ctx.fillStyle = panel;
      ctx.fill();
      ctx.save();
      ctx.globalAlpha = 0.45;
      ctx.strokeStyle = c.star;
      ctx.lineWidth = 0.6;
      ctx.beginPath();
      for (let q = 1; q < 4; q++) {
        const f = q / 4;
        ctx.moveTo(P[0][0] + (P[1][0] - P[0][0]) * f, P[0][1] + (P[1][1] - P[0][1]) * f);
        ctx.lineTo(P[3][0] + (P[2][0] - P[3][0]) * f, P[3][1] + (P[2][1] - P[3][1]) * f);
      }
      ctx.moveTo((P[0][0] + P[3][0]) / 2, (P[0][1] + P[3][1]) / 2);
      ctx.lineTo((P[1][0] + P[2][0]) / 2, (P[1][1] + P[2][1]) / 2);
      ctx.stroke();
      ctx.restore();
    }
    const gold = up ? '#d4a72c' : c['node-off'];
    this.cube(ax, ay + 4 * zs, 5 * zs, 8 * zs, 0, up ? '#f0cf6a' : c['node-off'], gold, up ? '#a77f17' : c['node-off']);
    // Dish on top, facing the viewer.
    ctx.fillStyle = up ? '#f4f4f5' : c['node-off'];
    ctx.beginPath(); ctx.ellipse(ax + 1 * zs, ay - 6 * zs, 3.4 * zs, 1.8 * zs, -0.4, 0, 2 * Math.PI); ctx.fill();
  }

  /** Car: an oriented box with a glass cabin, coloured per vehicle, driving
   *  along its heading; a shark-fin antenna on the roof. */
  car(pos, i, up, zs) {
    const { colors: c } = this;
    const x = pos[4 * i], y = pos[4 * i + 1];
    const m = this.motion[i];
    const moved = m && (m.dx || m.dy);
    const dx = moved ? m.dx : 1, dy = moved ? m.dy : 0;
    const L = 8 * zs / this.c, W = 4 * zs / this.c; // half-length / half-width in metres (screen-sized)
    const corner = (fl, fw) => [x + dx * L * fl - dy * W * fw, y + dy * L * fl + dx * W * fw];
    const [gx, gy] = this.project(x, y, 0);
    this.shadowAt(gx, gy + 1, 10 * zs, 0.25);
    const paint = up ? CAR_PAINT[i % CAR_PAINT.length] : c['node-off'];
    this.prism([corner(1, 1), corner(1, -1), corner(-1, -1), corner(-1, 1)], 1 * zs, 4.5 * zs, paint);
    this.prism([corner(0.4, 0.8), corner(0.4, -0.8), corner(-0.6, -0.8), corner(-0.6, 0.8)], 4.5 * zs, 8 * zs,
      up ? (c.night ? '#1e293b' : '#334155') : c['node-off'], paint);
    const [ax, ay] = this.antenna(pos, i);
    this.ctx.strokeStyle = up ? c.tower : c['node-off'];
    this.ctx.lineWidth = 1;
    this.ctx.beginPath(); this.ctx.moveTo(gx, gy - 9 * zs); this.ctx.lineTo(ax, ay); this.ctx.stroke();
  }

  /** Extrude a ground polygon (world x, y) between screen heights h0 and h1. */
  prism(poly, h0, h1, fill, topFill) {
    const { ctx } = this;
    const pts = poly.map(([x, y]) => this.project(x, y, 0));
    const walls = pts.map((p, k) => [p, pts[(k + 1) % pts.length], this.depth(...poly[k]) + this.depth(...poly[(k + 1) % poly.length])]);
    walls.sort((a, b) => a[2] - b[2]);
    for (const [a, b] of walls) {
      ctx.beginPath();
      ctx.moveTo(a[0], a[1] - h0); ctx.lineTo(b[0], b[1] - h0); ctx.lineTo(b[0], b[1] - h1); ctx.lineTo(a[0], a[1] - h1);
      ctx.closePath();
      ctx.fillStyle = fill;
      ctx.fill();
      ctx.fillStyle = 'rgba(0,0,0,0.18)';
      ctx.fill();
    }
    ctx.beginPath();
    ctx.moveTo(pts[0][0], pts[0][1] - h1);
    for (let k = 1; k < pts.length; k++) ctx.lineTo(pts[k][0], pts[k][1] - h1);
    ctx.closePath();
    ctx.fillStyle = topFill || fill;
    ctx.fill();
  }

  /** Wi-Fi mesh router on a pole: a white box with two antennas. */
  router(bx, by, ay, up, zs) {
    const { ctx, colors: c } = this;
    this.shadowAt(bx, by, 6 * zs, 0.2);
    const pole = up ? c['tower-dark'] : c['node-off'];
    ctx.strokeStyle = pole;
    ctx.lineWidth = 2 * zs;
    ctx.beginPath(); ctx.moveTo(bx, by); ctx.lineTo(bx, by - 12 * zs); ctx.stroke();
    const e = 12 * zs;
    this.cube(bx, by, 6 * zs, 4 * zs, e, up ? '#f8fafc' : c['node-off'], up ? '#cbd5e1' : c['node-off'], up ? '#94a3b8' : c['node-off']);
    ctx.strokeStyle = up ? c.tower : c['node-off'];
    ctx.lineWidth = 1.4 * zs;
    ctx.lineCap = 'round';
    ctx.beginPath();
    ctx.moveTo(bx - 4 * zs, by - e - 3 * zs); ctx.lineTo(bx - 5 * zs, ay + 1 * zs);
    ctx.moveTo(bx + 4 * zs, by - e - 3 * zs); ctx.lineTo(bx + 5 * zs, ay + 1 * zs);
    ctx.stroke();
    ctx.lineCap = 'butt';
    if (up) { // status LEDs on the front face
      ctx.fillStyle = c.good;
      for (const q of [-2, 0, 2]) ctx.fillRect(bx + 1.5 * zs + q * zs, by - e - 1 * zs + q * 0.25 * zs, 1.1 * zs, 1.1 * zs);
    }
  }

  /** One ant, seen from above: abdomen, thorax and head, six legs in step,
   *  two antennae. The kind is the colour and also a shape (#94), so colour is
   *  never the only cue:
   *    reactive  a plain scout            backward  lays amber droplets behind it
   *    proactive winged                   repair    pincers and a banded abdomen
   *    linkfail  carries a warning flag   data      a worker carrying a crumb of leaf
   *  `step` counts strides (the legs alternate with it). Each kind is drawn
   *  once per stride frame and size into a small bitmap and stamped from
   *  there, so a busy world pays a blit per ant, not thirty path segments. */
  ant(kind, x, y, angle, step, failed, scale) {
    const { ctx, colors: c } = this;
    // Grows with zoom, within limits; smaller on a narrow (phone) map so ants do not bury it.
    const s = Math.round((scale || 1.05 * Math.min(1.7, Math.max(0.85, this.zoom)) * Math.min(1, Math.max(0.65, this.w / 620))) * 10) / 10;
    const frame = Math.floor((((step * 0.38) % 1) + 1) % 1 * ANT_FRAMES);
    const key = `${kind}|${frame}|${s}|${this.dpr || 1}`;
    let stamp = this.antStamps.get(key);
    if (!stamp) {
      if (this.antStamps.size > 400) this.antStamps.clear();
      const k = s * (this.dpr || 1);
      stamp = document.createElement('canvas');
      stamp.width = Math.ceil(ANT_BOX[2] * k); stamp.height = Math.ceil(ANT_BOX[3] * k);
      const g = stamp.getContext('2d');
      g.setTransform(k, 0, 0, k, -ANT_BOX[0] * k, -ANT_BOX[1] * k);
      this.antShape(g, kind, frame / ANT_FRAMES * 2 * Math.PI);
      this.antStamps.set(key, stamp);
    }
    ctx.save();
    ctx.translate(x, y);
    ctx.rotate(angle);
    ctx.drawImage(stamp, ANT_BOX[0] * s, ANT_BOX[1] * s, ANT_BOX[2] * s, ANT_BOX[3] * s);
    if (failed) {
      ctx.scale(s, s);
      ctx.strokeStyle = c.critical;
      ctx.lineWidth = 2;
      ctx.beginPath(); ctx.moveTo(-5, -5); ctx.lineTo(5, 5); ctx.moveTo(5, -5); ctx.lineTo(-5, 5); ctx.stroke();
    }
    ctx.restore();
  }

  /** The ant itself, head toward +x, at the origin of `ctx`; `ph` is the leg phase. */
  antShape(ctx, kind, ph) {
    const c = this.colors;
    const col = c[kind], edge = c['ant-edge'];
    ctx.lineCap = 'round';
    if (kind === 'proactive') { // wings, under the body
      ctx.fillStyle = edge; ctx.strokeStyle = col; ctx.lineWidth = 0.7;
      for (const side of [-1, 1]) {
        ctx.beginPath(); ctx.ellipse(-3.2, side * 3.6, 5.2, 2, side * 0.45, 0, 2 * Math.PI);
        ctx.globalAlpha = 0.8; ctx.fill(); ctx.globalAlpha = 1; ctx.stroke();
      }
    }
    // Legs: three pairs, each pair out of step with the next and with its other side.
    const legs = () => {
      ctx.beginPath();
      for (let i = -1; i <= 1; i++) {
        for (const side of [-1, 1]) {
          const sw = Math.sin(ph + i * 2.1 + (side > 0 ? 0 : Math.PI)) * 2;
          ctx.moveTo(i * 2.2, 0); ctx.lineTo(i * 2.5 + sw, side * 5.2);
        }
      }
      for (const side of [-1, 1]) { // antennae
        ctx.moveTo(5.4, side * 0.9); ctx.quadraticCurveTo(8.2, side * 2.2, 9.4, side * 3.8);
      }
      if (kind === 'repair') { // pincers
        ctx.moveTo(6.2, -1.2); ctx.lineTo(8.8, -0.5); ctx.moveTo(6.2, 1.2); ctx.lineTo(8.8, 0.5);
      }
      ctx.stroke();
    };
    const body = () => {
      ctx.beginPath();
      ctx.ellipse(-5.2, 0, 4.1, 2.9, 0, 0, 2 * Math.PI);
      ctx.moveTo(2.5, 0); ctx.ellipse(0, 0, 2.5, 1.9, 0, 0, 2 * Math.PI);
      ctx.moveTo(6.6, 0); ctx.arc(4.2, 0, 2.4, 0, 2 * Math.PI);
    };
    ctx.strokeStyle = col; ctx.lineWidth = 1.1; legs();
    body();
    ctx.strokeStyle = edge; ctx.lineWidth = 2; ctx.stroke();      // a rim, so the ant reads on any ground
    ctx.fillStyle = col; ctx.fill();
    if (kind === 'repair') { // bands across the abdomen
      ctx.strokeStyle = edge; ctx.lineWidth = 1;
      ctx.beginPath(); ctx.moveTo(-6.4, -2.3); ctx.lineTo(-6.4, 2.3); ctx.moveTo(-4, -2.5); ctx.lineTo(-4, 2.5); ctx.stroke();
    } else if (kind === 'backward') { // pheromone droplets laid behind
      ctx.fillStyle = c['ph-trail']; ctx.strokeStyle = edge; ctx.lineWidth = 0.6;
      for (const [dx, r] of [[-11.2, 1.7], [-15, 1.2]]) { ctx.beginPath(); ctx.arc(dx, 0, r, 0, 2 * Math.PI); ctx.fill(); ctx.stroke(); }
    } else if (kind === 'linkfail') { // a warning flag
      ctx.fillStyle = edge; ctx.strokeStyle = col; ctx.lineWidth = 1; ctx.lineJoin = 'round';
      ctx.beginPath(); ctx.moveTo(0.5, -9.5); ctx.lineTo(4.6, -3.2); ctx.lineTo(-3.6, -3.2); ctx.closePath(); ctx.fill(); ctx.stroke();
      ctx.beginPath(); ctx.moveTo(0.5, -7.4); ctx.lineTo(0.5, -5.4); ctx.stroke();
    } else if (kind === 'data') { // the crumb: a piece of leaf held over the thorax
      ctx.fillStyle = c.leaf; ctx.strokeStyle = edge; ctx.lineWidth = 0.7;
      ctx.beginPath(); ctx.ellipse(2.6, -4.6 + Math.sin(ph) * 0.4, 4.6, 2.9, -0.5, 0, 2 * Math.PI); ctx.fill(); ctx.stroke();
    }
  }

  /** A swatch canvas for the legend, drawn with the same sprites. */
  swatch(kind) {
    const cv = document.createElement('canvas');
    const dpr = window.devicePixelRatio || 1;
    const W = 38, H = 24;
    cv.width = W * dpr; cv.height = H * dpr;
    cv.style.width = W + 'px'; cv.style.height = H + 'px';
    cv.setAttribute('aria-hidden', 'true');
    const saved = this.ctx;
    const g = this.ctx = cv.getContext('2d');
    const c = this.colors;
    g.setTransform(dpr, 0, 0, dpr, 0, 0);
    g.lineCap = 'round';
    if (kind === 'hello') {
      g.strokeStyle = c.hello; g.lineWidth = 1.2;
      g.beginPath(); g.ellipse(W / 2, H / 2, 15, 7.5, 0, 0, 2 * Math.PI); g.stroke();
    } else if (kind === 'route') {
      g.setLineDash([5, 8]);
      g.strokeStyle = c['ant-edge']; g.lineWidth = 3.4;
      g.beginPath(); g.moveTo(5, H / 2); g.lineTo(W - 5, H / 2); g.stroke();
      g.strokeStyle = c.text; g.lineWidth = 1.6;
      g.beginPath(); g.moveTo(5, H / 2); g.lineTo(W - 5, H / 2); g.stroke();
    } else if (kind === 'pheromone') {
      for (const [h0, fill, alpha] of [[7, c['ph-glow'], 0.8], [3.4, c['ph-trail'], 1]]) {
        g.globalAlpha = alpha; g.fillStyle = fill;
        g.beginPath(); g.moveTo(4, H / 2 - h0); g.lineTo(W - 4, H / 2 - h0 * 0.6); g.lineTo(W - 4, H / 2 + h0 * 0.6); g.lineTo(4, H / 2 + h0);
        g.closePath(); g.fill();
      }
    } else if (kind === 'virtual') {
      g.strokeStyle = c['ph-virtual']; g.lineWidth = 2; g.lineCap = 'butt'; g.setLineDash([2, 4.5]);
      g.beginPath(); g.moveTo(5, H / 2); g.lineTo(W - 5, H / 2); g.stroke();
    } else {
      this.ant(kind, kind === 'backward' ? W / 2 + 5 : W / 2 - 1, kind === 'data' || kind === 'linkfail' ? H / 2 + 3 : H / 2, 0, 0.9, false, 1.3);
    }
    this.ctx = saved;
    return cv;
  }
}
