// Copyright (c) 2026 Daniel Joppi (https://github.com/swarm-routing)
// SPDX-License-Identifier: GPL-2.0-only
// The site's one day/night choice (#97), applied before the first paint. A
// plain script in <head> on every page (the hub, the game, the docs, the
// API): it owns the storage key, so no page keeps its own.
//
// The choice is 'light' or 'dark' under 'arena-theme'; no entry means "follow
// the system". Until #97 the game, the docs and the API kept theirs under
// 'ahn-theme': a visitor who only has that one keeps it (it is copied over
// once and removed).
(function () {
  'use strict';
  var KEY = 'arena-theme', OLD = 'ahn-theme';
  var ok = function (t) { return t === 'light' || t === 'dark' ? t : null; };
  function saved() {
    try {
      var t = ok(localStorage.getItem(KEY));
      var old = ok(localStorage.getItem(OLD));
      if (!t && old) { localStorage.setItem(KEY, old); t = old; }
      if (old) localStorage.removeItem(OLD);
      return t;
    } catch (e) { return null; }  // storage blocked: the system decides
  }
  function save(t) {
    try { localStorage.setItem(KEY, t); } catch (e) { /* private mode: this page only */ }
  }
  var root = document.documentElement;
  var t = saved();
  if (t) root.dataset.theme = t;
  root.classList.add('js');  // shell.css folds the bar's menu on a phone only when script runs
  // The script that folds the bar also opens it: the Menu button works as soon
  // as this <head> script has run, whether shell.js, the page's modules or its
  // translations are slow, failed or blocked. Delegated, so it needs no element
  // to exist yet; shell.js's initMenu defers to it (root.dataset.menu).
  root.dataset.menu = 'theme';
  function setMenu(bar, btn, open) {
    bar.classList.toggle('ahn-open', open);
    btn.setAttribute('aria-expanded', String(open));
  }
  document.addEventListener('click', function (e) {
    var btn = e.target && e.target.closest && e.target.closest('#ahn-menu');
    var bar = btn && btn.closest('.ahn-bar');
    if (bar) setMenu(bar, btn, !bar.classList.contains('ahn-open'));
  });
  document.addEventListener('keydown', function (e) {
    if (e.key !== 'Escape') return;
    var bar = document.querySelector('.ahn-bar.ahn-open');
    var btn = bar && bar.querySelector('#ahn-menu');
    if (btn && bar.contains(e.target)) { setMenu(bar, btn, false); btn.focus(); }
  });
  window.arenaTheme = { key: KEY, saved: saved, save: save };
})();
