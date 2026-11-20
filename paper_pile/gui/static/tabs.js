// Thin capture layer for the tab bar (paper_pile/gui/components/tabs.py): dragging only.
// Click, middle-click and the close button are plain NiceGUI events; Python decides everything.
//
// Dragging is Chrome-like (user 2026-11-20), with pointer events (not HTML5 drag, whose image
// cannot follow the strip): inside its bar the tab follows the pointer and the others slide aside;
// on release it glides into its slot and Python is told (`pp_tab_move`), whose reorder lands with
// no jump (the transforms go in the frame the new order arrives). Pulled away from the bar, a copy
// of the tab follows the pointer: onto an editor / the chat it is a note drop (notedrop.js zones),
// onto the other split bar a move there (accent marker).
(function () {
  const tabOf = (el) => (el && el.closest ? el.closest('.pp-tab') : null);
  const barOf = (el) => (el && el.closest ? el.closest('.pp-tabbar') : null);
  const START_PX = 5;   // a press becomes a drag after this much movement
  const DETACH_PX = 28; // this far above / below the bar, the tab leaves it
  const EDGE_PX = 28;   // autoscroll the bar when the pointer is this close to its edge

  // ---- the accent marker between two tabs (a drop on the other split bar) ----
  let marker = null;
  let markKey = null;
  const showMarker = (tab, after) => {
    if (!marker) {
      marker = document.createElement('div');
      marker.className = 'pp-tab-marker';
      document.body.appendChild(marker);
      marker.addEventListener('animationend', () => marker.classList.remove('pp-jump'));
    }
    const key = tab.dataset.doc + (after ? '>' : '<');
    if (key === markKey) return;
    markKey = key;
    const r = tab.getBoundingClientRect();
    const line = getComputedStyle(tab, '::after');
    const top = parseFloat(line.top) || 10, bottom = parseFloat(line.bottom) || 9;
    const fresh = !marker.classList.contains('pp-on');
    if (fresh) marker.style.transition = 'none';
    marker.style.left = `${(after ? r.right : r.left) - 1.5}px`;  // centre on the 1 px divider
    marker.style.top = `${r.top + top - 2}px`;
    marker.style.height = `${r.height - top - bottom + 4}px`;
    if (fresh) { void marker.offsetWidth; marker.style.transition = ''; }
    marker.classList.add('pp-on');
    marker.classList.remove('pp-jump');
    void marker.offsetWidth;  // restart the bounce
    marker.classList.add('pp-jump');
  };
  const hideMarker = () => {
    markKey = null;
    if (marker) marker.classList.remove('pp-on', 'pp-jump');
  };

  let press = null;     // {tab, bar, x, y, id} until the pointer moves far enough
  let drag = null;      // the drag in progress
  let swallowClick = false;

  function begin(p) {
    const tabs = [...p.bar.querySelectorAll(':scope > .pp-tab')];
    const from = tabs.indexOf(p.tab);
    drag = {
      tab: p.tab, bar: p.bar, tabs, from, to: from,
      rects: tabs.map((t) => t.getBoundingClientRect()),
      startX: p.x, scroll0: p.bar.scrollLeft, x: p.x, y: p.y,
      out: false, ghost: null, ghostDx: 0, ghostDy: 0, raf: 0,
    };
    p.tab.style.transition = 'none';
    p.tab.style.zIndex = '3';
    p.tab.dataset.ppDragging = '1';
    for (const t of tabs) if (t !== p.tab) t.style.transition = `transform var(--pp-dur) var(--pp-ease)`;
    document.documentElement.classList.add('pp-tab-dragging');
    drag.raf = requestAnimationFrame(tick);
  }

  // where the dragged tab would go and how everything is drawn, from the pointer
  function layout() {
    const d = drag;
    const w = d.rects[d.from].width;
    const shift = d.x - d.startX + (d.bar.scrollLeft - d.scroll0);
    const first = d.rects[0].left, last = d.rects[d.rects.length - 1].right;
    const left = Math.min(Math.max(d.rects[d.from].left + shift, first), last - w);
    const dx = left - d.rects[d.from].left;
    const centre = left + w / 2;
    let to = d.from;
    while (to < d.tabs.length - 1 && centre > d.rects[to + 1].left + d.rects[to + 1].width / 2) to++;
    while (to > 0 && centre < d.rects[to - 1].left + d.rects[to - 1].width / 2) to--;
    d.to = to;
    d.tab.style.transform = `translateX(${dx}px)`;
    d.tabs.forEach((t, i) => {
      if (t === d.tab) return;
      const moveBy = d.from < to && i > d.from && i <= to ? -w : d.from > to && i >= to && i < d.from ? w : 0;
      t.style.transform = moveBy ? `translateX(${moveBy}px)` : '';
    });
  }

  // the slot's offset from the tab's own place (where it glides on release)
  function slotOffset(d) {
    let off = 0;
    if (d.to > d.from) for (let i = d.from + 1; i <= d.to; i++) off += d.rects[i].width;
    else for (let i = d.to; i < d.from; i++) off -= d.rects[i].width;
    return off;
  }

  function tick() {
    const d = drag;
    if (!d) return;
    if (!d.out) {  // the pointer near an edge of an overflowing bar: scroll it
      const r = d.bar.getBoundingClientRect();
      const step = d.x < r.left + EDGE_PX ? -8 : d.x > r.right - EDGE_PX ? 8 : 0;
      if (step) { d.bar.scrollLeft += step; layout(); }
    }
    d.raf = requestAnimationFrame(tick);
  }

  function detach() {
    const d = drag;
    d.out = true;
    d.tabs.forEach((t) => { if (t !== d.tab) t.style.transform = ''; });
    d.tab.style.transition = `transform var(--pp-dur) var(--pp-ease), opacity var(--pp-dur) var(--pp-ease)`;
    d.tab.style.transform = '';
    d.tab.style.opacity = '.35';
    if (!d.ghost) {
      const r = d.rects[d.from];
      d.ghost = d.tab.cloneNode(true);
      d.ghost.removeAttribute('id');
      d.ghost.removeAttribute('data-pp-dragging');
      d.ghost.className = d.tab.className + ' pp-tab-ghost';
      d.ghost.style.cssText = `width:${r.width}px;height:${r.height}px;transform:none;opacity:1`;
      d.ghostDx = d.startX - r.left;
      d.ghostDy = r.height / 2;
      document.body.appendChild(d.ghost);
    }
    d.ghost.style.display = '';
  }

  function attach() {
    const d = drag;
    d.out = false;
    d.tab.style.transition = 'none';
    d.tab.style.opacity = '';
    if (d.ghost) d.ghost.style.display = 'none';
    window.ppNoteZones && window.ppNoteZones.end();
    hideMarker();
    layout();
  }

  // outside its bar: what is under the pointer (the ghost takes no pointer events)
  function overOutside() {
    const d = drag;
    d.ghost.style.left = `${d.x - d.ghostDx}px`;
    d.ghost.style.top = `${d.y - d.ghostDy}px`;
    const target = document.elementFromPoint(d.x, d.y);
    const bar = barOf(target);
    if (bar && bar !== d.bar) {
      window.ppNoteZones && window.ppNoteZones.end();
      const tab = tabOf(target);
      const tabs = bar.querySelectorAll('.pp-tab');
      if (tab) {
        const r = tab.getBoundingClientRect();
        showMarker(tab, d.x > r.left + r.width / 2);
      } else if (tabs.length) showMarker(tabs[tabs.length - 1], true);
      return;
    }
    hideMarker();
    window.ppNoteZones && window.ppNoteZones.over(target, d.x);
  }

  function inBand(d) {
    const r = d.bar.getBoundingClientRect();
    return d.y > r.top - DETACH_PX && d.y < r.bottom + DETACH_PX;
  }

  // forget every inline style the drag set (at once, no transition)
  function reset(tabs) {
    for (const t of tabs) {
      t.style.transition = 'none';
      t.style.transform = '';
      t.style.opacity = '';
      t.style.zIndex = '';
      delete t.dataset.ppDragging;
    }
    void document.body.offsetWidth;
    for (const t of tabs) t.style.transition = '';
  }

  function finish(cancelled) {
    const d = drag;
    drag = null;
    cancelAnimationFrame(d.raf);
    document.documentElement.classList.remove('pp-tab-dragging');
    if (d.ghost) d.ghost.remove();
    const src = d.tab.dataset.doc;
    if (cancelled) { window.ppNoteZones && window.ppNoteZones.end(); hideMarker(); reset(d.tabs); return; }
    if (d.out) {
      const target = document.elementFromPoint(d.x, d.y);
      const bar = barOf(target);
      hideMarker();
      if (bar && bar !== d.bar) {
        window.ppNoteZones && window.ppNoteZones.end();
        const tab = tabOf(target);
        const tabs = bar.querySelectorAll('.pp-tab');
        if (tab) {
          const r = tab.getBoundingClientRect();
          emitEvent('pp_tab_move', { src, dst: tab.dataset.doc, after: d.x > r.left + r.width / 2 });
        } else if (tabs.length) emitEvent('pp_tab_move', { src, dst: tabs[tabs.length - 1].dataset.doc, after: true });
      } else if (window.ppNoteZones) window.ppNoteZones.drop(target, d.x, { doc: src });
      reset(d.tabs);
      return;
    }
    if (d.to === d.from) {  // back where it was: glide home
      d.tab.style.transition = `transform var(--pp-dur) var(--pp-ease)`;
      d.tab.style.transform = '';
      const motion = parseFloat(getComputedStyle(document.documentElement).getPropertyValue('--pp-motion')) || 1;
      setTimeout(() => reset(d.tabs), 160 * motion + 60);  // after the glide (--pp-dur)
      return;
    }
    // glide into the slot, then wait for Python's new order and drop the transforms in that frame
    d.tab.style.transition = `transform var(--pp-dur) var(--pp-ease)`;
    d.tab.style.transform = `translateX(${slotOffset(d)}px)`;
    const dst = d.tabs[d.to].dataset.doc;
    const done = () => { mo.disconnect(); clearTimeout(timer); reset(d.tabs); };
    const mo = new MutationObserver(done);
    mo.observe(d.bar, { childList: true });
    const timer = setTimeout(done, 1500);  // no answer (nothing changed): put everything back
    emitEvent('pp_tab_move', { src, dst, after: d.to > d.from });
  }

  document.addEventListener('pointerdown', (e) => {
    if (e.button !== 0 || drag) return;
    const tab = tabOf(e.target);
    const bar = barOf(tab);
    if (!tab || !bar || (e.target.closest && e.target.closest('.pp-tab-close'))) return;
    press = { tab, bar, x: e.clientX, y: e.clientY, id: e.pointerId };
  }, true);

  document.addEventListener('pointermove', (e) => {
    if (press && !drag && e.pointerId === press.id) {
      if (Math.hypot(e.clientX - press.x, e.clientY - press.y) < START_PX) return;
      try { press.tab.setPointerCapture(e.pointerId); } catch (_) { /* gone */ }
      begin(press);
      press = null;
    }
    if (!drag) return;
    e.preventDefault();
    drag.x = e.clientX;
    drag.y = e.clientY;
    const inside = inBand(drag);
    if (inside && drag.out) attach();
    else if (!inside && !drag.out) detach();
    if (drag.out) overOutside();
    else layout();
  }, true);

  document.addEventListener('pointerup', (e) => {
    press = null;
    if (!drag) return;
    drag.x = e.clientX;
    drag.y = e.clientY;
    swallowClick = true;  // the click after a drag must not also switch tabs
    setTimeout(() => { swallowClick = false; }, 0);
    finish(false);
  }, true);

  document.addEventListener('pointercancel', () => { press = null; if (drag) finish(true); }, true);
  document.addEventListener('keydown', (e) => { if (e.key === 'Escape' && drag) finish(true); }, true);
  document.addEventListener('click', (e) => {
    if (swallowClick && tabOf(e.target)) { e.stopPropagation(); e.preventDefault(); swallowClick = false; }
  }, true);
  // no HTML5 drag of a tab (tabs.py also leaves `draggable` off)
  document.addEventListener('dragstart', (e) => { if (tabOf(e.target)) e.preventDefault(); }, true);
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
  // Where a control sits (beside or under the text) is pure CSS (a container query on the box,
  // app.css). Here only: a group of buttons that does not fit shows icons only, each with its
  // text as a hover tip. Rows are checked whenever their own size changes.
  function fitRow(row) {
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

// Too many tabs (paper_pile/gui/components/tabs.py): the mouse wheel scrolls a tab row sideways.
// While a row overflows it gets `pp-tabs-scroll`: a ‹ and a › button, each in its own area at an
// edge of the row with a vertical line between it and the tabs (the row is padded by that area,
// so no tab hides under it). A click brings the next hidden tab on that side fully into view (one
// tab per click); an arrow with nothing more on its side is dimmed. The strip gets
// `pp-tabs-overflow` (shows the list button) while any row is cut off. The last row's › sits right
// after the + button (user 2026-11-06), not over the row's end: that row is padded on the left only
// (`pp-tabs-end`).
(function () {
  const AREA = 34; // px each arrow takes (keep in sync with .pp-tabs-arrow in app.css)
  const arrows = new WeakMap(); // tab row → [left, right]
  // The tabs' positions in the row's scrolled content, and the part of it that is in view.
  function tabBoxes(bar) {
    const origin = bar.getBoundingClientRect().left - bar.scrollLeft;
    return [...bar.querySelectorAll(':scope > .pp-tab')].map(function (t) {
      const r = t.getBoundingClientRect();
      return { left: r.left - origin, right: r.right - origin };
    });
  }
  const endArea = (bar) => (bar.classList.contains('pp-tabs-end') ? 0 : AREA); // the › area
  function step(bar, side) {
    const right = endArea(bar);
    const view = { left: bar.scrollLeft + AREA, right: bar.scrollLeft + bar.clientWidth - right };
    const tabs = tabBoxes(bar);
    let to = null;
    if (side === 'right') {
      const next = tabs.find(function (t) { return t.right > view.right + 1; });
      if (next) to = next.right - (bar.clientWidth - right);
    } else {
      const prev = tabs.slice().reverse().find(function (t) { return t.left < view.left - 1; });
      if (prev) to = prev.left - AREA;
    }
    if (to !== null) bar.scrollTo({ left: Math.max(0, to), behavior: window.ppMotion === 0 ? 'auto' : 'smooth' });
  }
  function arrowsOf(bar) {
    let pair = arrows.get(bar);
    if (pair && pair[0].isConnected) return pair;
    pair = ['left', 'right'].map(function (side) {
      const a = document.createElement('div');
      a.className = 'pp-tabs-arrow pp-tabs-arrow-' + side;
      a.innerHTML = window.ppIconSvg('chevron-' + side, 'm');
      a.dataset.tip = side === 'left' ? 'Previous tab' : 'Next tab';
      a.addEventListener('mousedown', function (e) { e.preventDefault(); });
      a.addEventListener('click', function () { step(bar, side); });
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
    const plus = strip.querySelector(':scope > .pp-tab-new');
    const bars = [...strip.querySelectorAll(':scope > .pp-tabbar')].filter((b) => b.offsetParent !== null);
    const last = !!plus && bars[bars.length - 1] === bar;
    if (last !== bar.classList.contains('pp-tabs-end')) bar.classList.toggle('pp-tabs-end', last);
    pair[1].classList.toggle('pp-tabs-arrow-after', last);
    if (last && plus.nextElementSibling !== pair[1]) plus.after(pair[1]);
    const padded = bar.classList.contains('pp-tabs-scroll');
    // overflow without the arrows' own padding, so showing them never decides whether they show
    const over = shown && bar.scrollWidth - (padded ? AREA + endArea(bar) : 0) > bar.clientWidth + 1;
    if (over !== padded) bar.classList.toggle('pp-tabs-scroll', over);
    const sRect = strip.getBoundingClientRect();
    const bRect = bar.getBoundingClientRect();
    pair[0].style.left = bRect.left - sRect.left + 'px';
    pair[1].style.left = last ? '' : bRect.right - sRect.left - AREA + 'px';
    pair.forEach(function (a) { a.classList.toggle('pp-on', over); });
    pair[0].classList.toggle('pp-off', bar.scrollLeft <= 1);
    pair[1].classList.toggle('pp-off', bar.scrollLeft + bar.clientWidth >= bar.scrollWidth - 1);
    // which edges cut a tab off (they fade, app.css); data-*: Python rewrites the class list
    const cut = (over && bar.scrollLeft > 1 ? 'l' : '') + (over && !pair[1].classList.contains('pp-off') ? 'r' : '');
    if ((bar.dataset.ppCut || '') !== cut) bar.dataset.ppCut = cut;
    let any = false;
    strip.querySelectorAll('.pp-tabbar').forEach(function (b) {
      if (b.offsetParent !== null && b.scrollWidth > b.clientWidth + 1) any = true;
    });
    strip.classList.toggle('pp-tabs-overflow', any);
  }
  // Bring each row's active tab fully into view (tabs.py calls it after every redraw). Not
  // scrollIntoView: that stops at the tab's box, so its corner ramps (outside the box) and the
  // edge fade cut the tab, and it may scroll the page too. The tab keeps FADE px clear of a cut
  // edge; Vue draws the new tabs after this call arrives, so it waits for the next frame.
  const FADE = 28; // keep in sync with the fade in .pp-tabbar[data-pp-cut] (app.css)
  function reveal(bar) {
    const tab = bar.querySelector(':scope > :is(.pp-tab-active, .pp-tab-shown)');
    if (!tab || bar.scrollWidth <= bar.clientWidth + 1) return;
    const scroll = bar.classList.contains('pp-tabs-scroll');
    const lead = scroll ? AREA : 0;
    const tail = scroll ? endArea(bar) : 0;
    const origin = bar.getBoundingClientRect().left - bar.scrollLeft;
    const r = tab.getBoundingClientRect();
    const left = r.left - origin - lead - FADE;
    const right = r.right - origin - (bar.clientWidth - tail) + FADE;
    let to = bar.scrollLeft;
    if (left < to) to = left; else if (right > to) to = right;
    to = Math.max(0, Math.min(to, bar.scrollWidth - bar.clientWidth));
    if (Math.abs(to - bar.scrollLeft) > 0.5) bar.scrollLeft = to;
  }
  window.ppRevealTabs = function () {
    requestAnimationFrame(function () {
      document.querySelectorAll('.pp-tabstrip > .pp-tabbar').forEach(function (bar) {
        if (bar.offsetParent === null) return;
        update(bar); // arrows / padding first: they decide the room
        reveal(bar);
        update(bar);
      });
    });
  };
  const sizes = new ResizeObserver(function (entries) { entries.forEach(function (e) { update(e.target); reveal(e.target); }); });
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
