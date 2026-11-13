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
  window.arenaTheme = { key: KEY, saved: saved, save: save };
})();
