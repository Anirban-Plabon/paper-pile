// The Ask box under a selection (PLAN §4.27; drawn by gui/components/ask_popup.py, loaded by
// gui/app.py). Here only: place it under the selection (above it when there is no room), drag the
// mini chat by its header, keep it inside the visible window as it grows (above --pp-inset-bottom),
// follow the note's scrolling until it was moved, move through the / list, and report Enter, a
// picked command and mouse-downs outside it. What any of that does is decided in Python.
(function () {
  const GAP = 8;
  const MARGIN = 6;
  const inset = (name) =>
    parseFloat(getComputedStyle(document.documentElement).getPropertyValue(name)) || 0;
  const box = () => document.querySelector('.pp-askpop');
  const shown = (el) => !!el && el.getClientRects().length > 0; // fixed: no offsetParent
  let anchor = null; // the selection's {left, top, bottom} while the box was not moved
  let moved = false;

  function bounds() {
    return {
      top: inset('--pp-inset-top') + MARGIN,
      bottom: window.innerHeight - inset('--pp-inset-bottom') - MARGIN,
      left: MARGIN,
      right: window.innerWidth - MARGIN,
    };
  }
  function put(el, x, y) {
    const b = bounds();
    const w = el.offsetWidth;
    const h = el.offsetHeight;
    el.style.left = Math.max(b.left, Math.min(x, b.right - w)) + 'px';
    el.style.top = Math.max(b.top, Math.min(y, b.bottom - h)) + 'px';
  }
  function place(el) {
    if (!shown(el)) return;
    if (moved || !anchor) {
      const r = el.getBoundingClientRect();
      put(el, r.left, r.top); // grown, or the window got smaller: stay inside
      return;
    }
    const b = bounds();
    const h = el.offsetHeight;
    let y = anchor.bottom + GAP;
    if (y + h > b.bottom && anchor.top - GAP - h >= b.top) y = anchor.top - GAP - h;
    put(el, anchor.left, y);
  }

  // the caret goes into the box as soon as it is there (once Python has shown it)
  window.ppAskFocus = function () {
    let tries = 0;
    const go = () => {
      const area = document.querySelector('.pp-askpop textarea');
      if (area && shown(box())) area.focus();
      else if (++tries < 20) requestAnimationFrame(go);
    };
    requestAnimationFrame(go);
  };

  window.ppAskPlace = function (rect) {
    anchor = rect && typeof rect.bottom === 'number' ? { ...rect } : null;
    moved = false;
    const el = box();
    if (el) requestAnimationFrame(() => place(el)); // the size observer places it when shown
    window.ppAskFocus();
  };

  // Ctrl+Enter: a new line (Enter sends), in the box and in the chat's composer
  window.ppNewLine = function (area) {
    if (!document.execCommand('insertText', false, '\n')) {
      const at = area.selectionStart;
      area.setRangeText('\n', at, area.selectionEnd, 'end');
      area.dispatchEvent(new Event('input', { bubbles: true }));
    }
  };

  // shown, grown into the mini chat, or the window resized
  const sizes = new ResizeObserver(() => place(box()));
  window.addEventListener('resize', () => place(box()));
  window.ppEachFrame(function () {
    const el = box();
    if (el && !el.dataset.ppWatched) {
      el.dataset.ppWatched = '1';
      sizes.observe(el);
    }
  });

  // until moved, the box goes with its text when the note scrolls
  const tops = new WeakMap();
  document.addEventListener('scroll', function (e) {
    const scroller = e.target;
    if (!(scroller instanceof Element) || !scroller.hasAttribute('data-pp-ask-anchor')) return;
    const before = tops.has(scroller) ? tops.get(scroller) : scroller.scrollTop;
    tops.set(scroller, scroller.scrollTop);
    const el = box();
    if (moved || !anchor || !shown(el)) return;
    const dy = before - scroller.scrollTop;
    anchor.top += dy;
    anchor.bottom += dy;
    place(el);
  }, true);
  document.addEventListener('mousedown', function (e) {
    const s = e.target && e.target.closest && e.target.closest('[data-pp-ask-anchor]');
    if (s) tops.set(s, s.scrollTop);
  }, true);

  // drag the mini chat by its header, not by the × on it
  document.addEventListener('pointerdown', function (e) {
    const el = box();
    const handle = e.target.closest && e.target.closest('.pp-askpop-chat .pp-askpop-head');
    if (!el || !handle || e.button !== 0 || e.target.closest('button')) return;
    e.preventDefault();
    const r = el.getBoundingClientRect();
    const dx = e.clientX - r.left;
    const dy = e.clientY - r.top;
    el.classList.add('pp-askpop-dragging');
    const move = (ev) => {
      moved = true;
      put(el, ev.clientX - dx, ev.clientY - dy);
    };
    const up = () => {
      el.classList.remove('pp-askpop-dragging');
      window.removeEventListener('pointermove', move, true);
      window.removeEventListener('pointerup', up, true);
    };
    window.addEventListener('pointermove', move, true);
    window.addEventListener('pointerup', up, true);
  }, true);

  // a mouse-down anywhere else closes it (its own menus and tooltips count as inside)
  document.addEventListener('mousedown', function (e) {
    const el = box();
    if (!shown(el) || el.contains(e.target)) return;
    if (e.target.closest && e.target.closest('.q-menu, .q-tooltip, .q-dialog, .q-notification')) return;
    emitEvent('pp_askpop_close', {});
  }, true);

  // keys in the box: Enter sends (Shift+Enter: new line), Esc closes, the / list moves
  document.addEventListener('keydown', function (e) {
    const area = e.target && e.target.closest && e.target.closest('.pp-askpop textarea');
    if (!area || e.isComposing) return;
    const rows = [...document.querySelectorAll('.pp-askpop-cmds .pp-askpop-cmd')];
    const active = rows.findIndex((r) => r.classList.contains('pp-askpop-cmd-active'));
    if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
      window.ppNewLine(area);
    } else if (e.key === 'Backspace' && !area.value && shown(document.querySelector('.pp-askpop-chip'))) {
      emitEvent('pp_askpop_unchip', {});
    } else if (e.key === 'Escape') {
      emitEvent('pp_askpop_close', { key: true });
    } else if (rows.length && (e.key === 'ArrowDown' || e.key === 'ArrowUp')) {
      const next = (active + (e.key === 'ArrowDown' ? 1 : -1) + rows.length) % rows.length;
      rows.forEach((r, i) => r.classList.toggle('pp-askpop-cmd-active', i === next));
      rows[next].scrollIntoView({ block: 'nearest' });
    } else if (rows.length && (e.key === 'Tab' || (e.key === 'Enter' && !e.shiftKey))) {
      emitEvent('pp_askpop_pick', { id: rows[Math.max(0, active)].dataset.id });
    } else if (e.key === 'Enter' && !e.shiftKey) {
      emitEvent('pp_askpop_send', {});
    } else {
      return;
    }
    e.preventDefault();
    e.stopPropagation();
  }, true);
})();
