// Thin capture layer for the tab bar (paper_pile/gui/components/tabs.py): drag-to-reorder only.
// Click, middle-click and the close button are plain NiceGUI events; Python decides everything.
(function () {
  const tabOf = (el) => (el && el.closest ? el.closest('.pp-tab') : null);
  const barOf = (el) => (el && el.closest ? el.closest('.pp-tabbar') : null);
  let dragId = null;
  let overEl = null;
  const clearOver = () => {
    if (overEl) overEl.classList.remove('pp-tab-drop-before', 'pp-tab-drop-after');
    overEl = null;
  };

  document.addEventListener('dragstart', (e) => {
    const tab = tabOf(e.target);
    if (!tab) return;
    dragId = tab.dataset.doc;
    e.dataTransfer.setData('text/plain', dragId);
    e.dataTransfer.effectAllowed = 'move';
  });
  document.addEventListener('dragover', (e) => {
    if (dragId === null) return;
    const tab = tabOf(e.target);
    clearOver();
    if (!tab) {
      if (barOf(e.target)) e.preventDefault(); // empty part of the bar = "move to the end"
      return;
    }
    e.preventDefault();
    e.dataTransfer.dropEffect = 'move';
    const r = tab.getBoundingClientRect();
    overEl = tab;
    tab.classList.add(e.clientX > r.left + r.width / 2 ? 'pp-tab-drop-after' : 'pp-tab-drop-before');
  });
  document.addEventListener('drop', (e) => {
    if (dragId === null) return;
    const src = dragId;
    dragId = null;
    const tab = tabOf(e.target);
    clearOver();
    if (tab) {
      const r = tab.getBoundingClientRect();
      e.preventDefault();
      emitEvent('pp_tab_move', { src: src, dst: tab.dataset.doc, after: e.clientX > r.left + r.width / 2 });
    } else if (barOf(e.target)) {
      const tabs = barOf(e.target).querySelectorAll('.pp-tab');
      if (!tabs.length) return;
      e.preventDefault();
      emitEvent('pp_tab_move', { src: src, dst: tabs[tabs.length - 1].dataset.doc, after: true });
    }
  });
  document.addEventListener('dragend', () => { dragId = null; clearOver(); });
})();

// Right pane tabs (paper_pile/gui/components/right_pane.py): when the titles do not all fit,
// every tab shows its icon only (`pp-rtabs-icons` on the bar) instead of cut-off text.
(function () {
  function room(bar) {
    const c = getComputedStyle(bar);
    return bar.clientWidth - parseFloat(c.paddingLeft) - parseFloat(c.paddingRight);
  }
  function fit(bar) {
    if (!bar.classList.contains('pp-rtabs-icons') || !bar.dataset.need) {
      bar.classList.remove('pp-rtabs-icons');  // measure with the titles shown
      let need = 0;
      bar.querySelectorAll('.pp-rtab').forEach(function (tab) {
        const title = tab.querySelector('.pp-rtab-title');  // it clips itself: add what it hides
        need += tab.offsetWidth + (title ? title.scrollWidth - title.clientWidth : 0);
      });
      bar.dataset.need = String(need);
    }
    const icons = Number(bar.dataset.need) > room(bar) + 0.5;
    bar.classList.toggle('pp-rtabs-icons', icons);
    // a name on hover only when it is not already written on the tab (static/tips.js)
    bar.querySelectorAll('.pp-rtab').forEach(function (tab) {
      if (icons && tab.dataset.name) tab.dataset.tip = tab.dataset.name; else delete tab.dataset.tip;
    });
  }
  const sizes = new ResizeObserver(function (entries) { entries.forEach(function (e) { fit(e.target); }); });
  const tabsChanged = new MutationObserver(function (records) {
    records.forEach(function (r) {
      const bar = r.target.closest ? r.target.closest('.pp-rtabbar') : null;
      if (bar) { delete bar.dataset.need; fit(bar); }
    });
  });
  const watched = new WeakSet();
  window.ppEachFrame(function () {  // after DOM changes, at most once per frame
    document.querySelectorAll('.pp-rtabbar').forEach(function (bar) {
      if (watched.has(bar)) return;
      watched.add(bar);
      sizes.observe(bar);
      tabsChanged.observe(bar, { childList: true });
      fit(bar);
    });
  });
})();

// Settings (paper_pile/gui/components/settings.py): while its section list is folded to icons
// (the same 560 px as the CSS container query), each icon gets its name as a hover tip.
(function () {
  const FOLD = 560;
  function label(set) {
    const folded = set.getBoundingClientRect().width <= FOLD;
    set.querySelectorAll('.pp-set-navitem').forEach(function (item) {
      const name = item.querySelector('.pp-set-navlabel');
      if (folded && name) item.dataset.tip = name.textContent; else delete item.dataset.tip;
    });
    const restore = set.querySelector('.pp-set-restore');
    if (restore) { if (folded) restore.dataset.tip = 'Restore defaults'; else delete restore.dataset.tip; }
  }
  // A row whose control dropped under its text is marked (its field then stretches). A group of
  // buttons that does not fit shows icons only, each with its text as a hover tip. Rows are
  // checked whenever their own size changes, so the mark always matches the settled layout.
  function fitRow(row) {
    const text = row.querySelector(':scope > .pp-set-text');
    const control = row.querySelector(':scope > .pp-set-control');
    if (text && control) {
      const below = control.getBoundingClientRect().top >= text.getBoundingClientRect().bottom - 2;
      if (row.classList.contains('pp-set-stacked') !== below) row.classList.toggle('pp-set-stacked', below);
    }
    row.querySelectorAll('.pp-set-control, .pp-instr-bar, .pp-set-blockhead').forEach(function (box) {
      box.classList.remove('pp-icons-only');
      const squeezed = box.scrollWidth > box.clientWidth + 1;
      box.classList.toggle('pp-icons-only', squeezed);
      box.querySelectorAll('.q-btn, .pp-seg-item').forEach(function (b) {
        if (!b.querySelector('.q-icon')) return;
        if (squeezed && !b.dataset.tip) { b.dataset.tip = b.textContent.trim(); b.dataset.tipAuto = '1'; }
        else if (!squeezed && b.dataset.tipAuto) { delete b.dataset.tip; delete b.dataset.tipAuto; }
      });
    });
  }
  const rowSizes = new ResizeObserver(function (entries) { entries.forEach(function (e) { fitRow(e.target); }); });
  const rows = new WeakSet();
  function fit(set) {
    set.querySelectorAll('.pp-set-row').forEach(function (row) {
      if (!rows.has(row)) { rows.add(row); rowSizes.observe(row); }
      fitRow(row);
    });
  }
  const sizes = new ResizeObserver(function (entries) { entries.forEach(function (e) { label(e.target); fit(e.target); }); });
  const watched = new WeakSet();
  window.ppEachFrame(function () {  // after DOM changes, at most once per frame
    document.querySelectorAll('.pp-set').forEach(function (set) {
      if (!watched.has(set)) { watched.add(set); sizes.observe(set); }
      label(set);
      fit(set);
    });
  });
})();

// Too many tabs (paper_pile/gui/components/tabs.py): the mouse wheel scrolls a tab row sideways,
// a ‹ / › arrow sits on an edge that hides tabs (a click scrolls most of a row's width), and the
// strip gets `pp-tabs-overflow` (shows the list button) while any row is cut off.
(function () {
  const arrows = new WeakMap(); // tab row → [left, right]
  function arrowsOf(bar) {
    let pair = arrows.get(bar);
    if (pair && pair[0].isConnected) return pair;
    pair = ['left', 'right'].map(function (side) {
      const a = document.createElement('div');
      a.className = 'pp-tabs-arrow pp-tabs-arrow-' + side;
      a.innerHTML = window.ppIconSvg('chevron-' + side, 's');
      a.addEventListener('mousedown', function (e) { e.preventDefault(); });
      a.addEventListener('click', function () {
        bar.scrollBy({ left: (side === 'left' ? -0.7 : 0.7) * bar.clientWidth, behavior: 'smooth' });
      });
      bar.parentElement.appendChild(a);
      return a;
    });
    arrows.set(bar, pair);
    return pair;
  }
  function update(bar) {
    const strip = bar.closest('.pp-tabstrip');
    if (!strip) return;
    const pair = arrowsOf(bar);
    const shown = bar.offsetParent !== null;
    const left = shown && bar.scrollLeft > 1;
    const right = shown && bar.scrollLeft + bar.clientWidth < bar.scrollWidth - 1;
    const sRect = strip.getBoundingClientRect();
    const bRect = bar.getBoundingClientRect();
    pair[0].style.left = bRect.left - sRect.left + 'px';
    pair[1].style.left = bRect.right - sRect.left - pair[1].offsetWidth + 'px';
    pair[0].classList.toggle('pp-on', left);
    pair[1].classList.toggle('pp-on', right);
    bar.classList.toggle('pp-cut-left', left);
    bar.classList.toggle('pp-cut-right', right);
    let over = false;
    strip.querySelectorAll('.pp-tabbar').forEach(function (b) {
      if (b.offsetParent !== null && b.scrollWidth > b.clientWidth + 1) over = true;
    });
    strip.classList.toggle('pp-tabs-overflow', over);
  }
  const sizes = new ResizeObserver(function (entries) { entries.forEach(function (e) { update(e.target); }); });
  const watched = new WeakSet();
  function watch() {
    document.querySelectorAll('.pp-tabstrip > .pp-tabbar').forEach(function (bar) {
      if (!watched.has(bar)) {
        watched.add(bar);
        sizes.observe(bar);
        bar.addEventListener('scroll', function () { update(bar); }, { passive: true });
        bar.addEventListener('wheel', function (e) {
          if (Math.abs(e.deltaX) >= Math.abs(e.deltaY) || bar.scrollWidth <= bar.clientWidth) return;
          e.preventDefault();
          bar.scrollLeft += e.deltaY;
        }, { passive: false });
      }
      update(bar); // tabs added or removed
    });
  }
  if (window.ppEachFrame) window.ppEachFrame(watch);
  else document.addEventListener('DOMContentLoaded', watch);
})();
