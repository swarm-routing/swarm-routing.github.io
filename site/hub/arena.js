// Colony Arena: day/night, the map's focus card, copy buttons, the reference filter, ants walking the trails.
// SPDX-License-Identifier: GPL-2.0-only
// Copyright (c) 2026 Daniel Joppi (https://github.com/swarm-routing)
// Everything here is decoration on static HTML: without it the map, the cards
// and the diagrams all still work. Ant positions come from a fixed seed, so
// the map looks the same on every visit.
(function () {
  'use strict';
  var root = document.documentElement;
  var btn = document.getElementById('theme');
  function dark() {
    return root.dataset.theme ? root.dataset.theme === 'dark'
      : window.matchMedia('(prefers-color-scheme: dark)').matches;
  }
  function paint() { if (btn) btn.textContent = dark() ? '☀' : '☾'; }
  if (btn) {
    btn.addEventListener('click', function () {
      root.dataset.theme = dark() ? 'light' : 'dark';
      try { localStorage.setItem('arena-theme', root.dataset.theme); } catch (e) { /* private mode */ }
      paint();
    });
  }
  paint();

  var card = document.getElementById('map-card');
  var places = document.querySelectorAll('.place');
  function show(a) {
    if (!card) return;
    places.forEach(function (p) { p.classList.toggle('on', p === a); });
    var parts = (a.getAttribute('aria-label') || '').split(': ');
    card.innerHTML = '';
    var k = document.createElement('p'); k.className = 'mc-k'; k.textContent = 'Place';
    var t = document.createElement('p'); t.className = 'mc-t'; t.textContent = parts[0];
    var s = document.createElement('p'); s.className = 'mc-s'; s.textContent = parts.slice(1).join(': ') + ' Press Enter to visit.';
    card.append(k, t, s);
  }
  places.forEach(function (a) {
    a.addEventListener('mouseenter', function () { show(a); });
    a.addEventListener('focus', function () { show(a); });
  });

  // Copy buttons (a citation, a reference's BibTeX): the text is in data-copy.
  document.querySelectorAll('[data-copy]').forEach(function (b) {
    var label = b.textContent;
    b.addEventListener('click', function () {
      if (!navigator.clipboard) return;
      navigator.clipboard.writeText(b.getAttribute('data-copy')).then(function () {
        b.textContent = 'Copied';
        b.setAttribute('aria-live', 'polite');
        setTimeout(function () { b.textContent = label; }, 1400);
      }, function () { /* no permission: the text is on the page to select */ });
    });
  });
  // A filter over a long reference list (more than ten entries).
  document.querySelectorAll('.reflist').forEach(function (sec) {
    var items = sec.querySelectorAll('.refs li');
    if (items.length <= 10) return;
    var q = document.createElement('input');
    q.type = 'search'; q.className = 'ref-q'; q.placeholder = 'Filter: author, title, year…';
    q.setAttribute('aria-label', 'Filter the ' + items.length + ' references');
    q.addEventListener('input', function () {
      var t = q.value.toLowerCase();
      items.forEach(function (li) { li.hidden = li.textContent.toLowerCase().indexOf(t) < 0; });
      sec.querySelectorAll('.refs').forEach(function (ul) {
        var none = !ul.querySelector('li:not([hidden])');
        ul.hidden = none;
        if (ul.previousElementSibling && ul.previousElementSibling.tagName === 'H3') ul.previousElementSibling.hidden = none;
      });
    });
    var first = sec.querySelector('h3, .refs');
    sec.insertBefore(q, first);
  });

  // Ants: a few per live trail, none when the visitor asked for less motion.
  if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;
  var layer = document.querySelector('.ants');
  if (!layer || !layer.ownerSVGElement) return;
  var NS = 'http://www.w3.org/2000/svg';
  var seed = 7;
  function rnd() { seed = (seed * 1103515245 + 12345) % 2147483648; return seed / 2147483648; }
  var trails = document.querySelectorAll('.trail');
  var ants = [];
  trails.forEach(function (path) {
    var n = path.classList.contains('trail-live') ? 3 : 1;
    var len = path.getTotalLength();
    for (var i = 0; i < n; i++) {
      var c = document.createElementNS(NS, 'circle');
      c.setAttribute('r', '3.2');
      layer.appendChild(c);
      ants.push({ el: c, path: path, len: len, at: rnd() * len, v: 18 + rnd() * 14, dir: rnd() < 0.5 ? 1 : -1 });
    }
  });
  var last = null, running = false;
  function step(ts) {
    running = true;
    var dt = last === null ? 0 : Math.min(0.05, (ts - last) / 1000);
    last = ts;
    for (var i = 0; i < ants.length; i++) {
      var a = ants[i];
      a.at += a.dir * a.v * dt;
      if (a.at > a.len) { a.at = a.len; a.dir = -1; }
      if (a.at < 0) { a.at = 0; a.dir = 1; }
      var p = a.path.getPointAtLength(a.at);
      a.el.setAttribute('cx', p.x.toFixed(1));
      a.el.setAttribute('cy', p.y.toFixed(1));
    }
    if (!document.hidden) requestAnimationFrame(step); else { last = null; running = false; }
  }
  document.addEventListener('visibilitychange', function () {
    if (!document.hidden && !running) { running = true; requestAnimationFrame(step); }
  });
  running = true;
  requestAnimationFrame(step);
})();
