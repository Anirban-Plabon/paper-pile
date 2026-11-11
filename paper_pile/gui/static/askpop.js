// The Ask box under a selection (PLAN §4.27; drawn by gui/components/ask_popup.py, loaded by
// gui/app.py). Here only: place it, drag the mini chat by its header, follow the note's scrolling
// until it was moved, move through the / list, and report Enter, a picked command and mouse-downs
// outside it. What any of that does is decided in Python.
//
// Placing (user, 2026-10-31): the side is chosen ONCE, when the box opens — below the selection
// when the full mini chat (--pp-askpop-full) fits there, else above when it fits there, else the
// bigger side (the chat's height is then capped to it). The box is held by its edge next to the
// selection (top when it grows down, bottom when it grows up). The mini chat has one fixed height
// (user, 2026-11-04): its frame stays where it opened and the input is always at its bottom.
// The small box's / list opens on the growing side when the full chat fits there; otherwise
// where it fits (the growing side, else over the selection, else the bigger). In the chat the
// list is inside the frame, above the input.
(function () {
  const GAP = 8;
  const MARGIN = 6;
  const inset = (name) =>
    parseFloat(getComputedStyle(document.documentElement).getPropertyValue(name)) || 0;
  const box = () => document.querySelector('.pp-askpop');
  const shown = (el) => !!el && el.getClientRects().length > 0; // fixed: no offsetParent
  let anchor = null; // the selection's {left, top, bottom} while the box was not moved
  let moved = false;
  let side = null; // 'down' | 'up': where the box grows, chosen when it opens
  let full = false; // the whole mini chat fits on that side
  const CLEAR = 6; // between the selection and the box's edge
  const WIDEST = 384; // the mini chat's width: kept inside the window from the start
  const EDGE = 11; // the box's padding + border: its card starts this far in

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
  const row = (el) => el.querySelector('.pp-askpop-bottom');

  function choose(el) {
    // the side, once: where the full mini chat fits (its height is fixed, so known in advance)
    const b = bounds();
    const need = inset('--pp-askpop-full') || 480;
    const below = b.bottom - (anchor.bottom + CLEAR);
    const above = anchor.top - CLEAR - b.top;
    side = below >= need ? 'down' : above >= need ? 'up' : below >= above ? 'down' : 'up';
    full = (side === 'down' ? below : above) >= need;
    el.dataset.ppSide = side; // an attribute, not a class: Python rewrites the class list
    el.style.setProperty('--pp-askpop-room', Math.max(120, side === 'down' ? below : above) + 'px');
  }

  function fitList(el) {
    // the / list: on the growing side when the full chat fits there, else where it fits
    const list = el.querySelector('.pp-askpop-cmds');
    if (!list) return;
    delete list.dataset.ppFlip;
    list.style.maxHeight = '';
    if (full || !shown(list) || el.classList.contains('pp-askpop-chat')) return;
    const b = bounds();
    const r = row(el).getBoundingClientRect();
    const h = list.offsetHeight;
    // the room for it past the input, and over the selection (past the box's edge either way)
    const grow = (side === 'down' ? b.bottom - r.bottom : r.top - b.top) - EDGE - GAP;
    const back = (side === 'down' ? r.top - b.top : b.bottom - r.bottom) - EDGE - GAP;
    if (h <= grow) return;
    if (h <= back || back > grow) list.dataset.ppFlip = '1';
    list.style.maxHeight = Math.max(80, Math.max(grow, back)) + 'px';
  }

  function place(el) {
    if (!shown(el)) return;
    if (moved || !anchor) {
      const r = el.getBoundingClientRect();
      el.style.bottom = '';
      put(el, r.left, r.top); // grown, or the window got smaller: stay inside
      return;
    }
    if (!side) choose(el);
    fitList(el);
    const b = bounds();
    const x = Math.min(anchor.left - EDGE, b.right - Math.max(WIDEST, el.offsetWidth));
    el.style.left = Math.max(b.left - EDGE, x) + 'px'; // the card in line with the selection
    if (side === 'down') {
      el.style.bottom = '';
      el.style.top = anchor.bottom + CLEAR + 'px';
    } else {
      el.style.top = 'auto';
      el.style.bottom = window.innerHeight - (anchor.top - CLEAR) + 'px';
    }
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
    side = null; // chosen again for this selection, once the box is shown
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
    el.style.bottom = ''; // dragged: held by its top-left corner from now on
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

  // the note editor the user was last in: copy / cut / paste go back to it (below)
  let lastEditor = null;
  document.addEventListener('focusin', function (e) {
    const c = e.target && e.target.closest && e.target.closest('.cm-content');
    if (c) lastEditor = c;
  }, true);

  // keys in the box: Enter sends (Shift+Enter: new line), Esc closes, the / list moves
  document.addEventListener('keydown', function (e) {
    const area = e.target && e.target.closest && e.target.closest('.pp-askpop textarea');
    if (!area || e.isComposing) return;
    const k = (e.key || '').toLowerCase();
    if ((e.ctrlKey || e.metaKey) && !e.altKey && (k === 'c' || k === 'x' || k === 'v')
        && !area.value && box().classList.contains('pp-askpop-box')) {
      // nothing typed yet: copy / cut / paste are for the selected text in the note. The note
      // gets the focus now, before the browser acts, and the box closes; not prevented.
      const editor = lastEditor && lastEditor.isConnected ? lastEditor : document.querySelector('.pp-editor .cm-content');
      if (editor && !(window.ppFocusEditor && window.ppFocusEditor(editor))) editor.focus({ preventScroll: true });
      emitEvent('pp_askpop_close', { key: true });
      return;
    }
    const rows = [...document.querySelectorAll('.pp-askpop-cmds .pp-askpop-cmd')];
    const active = rows.findIndex((r) => r.classList.contains('pp-askpop-cmd-active'));
    if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
      window.ppNewLine(area);
    } else if (e.key === 'Backspace' && !area.value && shown(document.querySelector('.pp-askpop-chip'))) {
      emitEvent('pp_askpop_unchip', {});
    } else if ((e.key === 'Backspace' || e.key === 'Delete') && !area.value && box().classList.contains('pp-askpop-box')) {
      emitEvent('pp_askpop_delete', {}); // nothing typed yet: the key is for the selected text
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

// The AI chip of a job started from the Ask box (user 2026-11-10; gui/components/ai_progress.py
// `follow`): the box turns into the chip — the chip starts where the box's card was and slides to
// the note's AI spot (an empty block under the text being written, tools/editor_src/aispot.js),
// then goes down with it as the text streams in. Kept inside the note's visible part, so Stop is
// always reachable. Until a spot exists (reading a long note first) it stays where the box was.
// State lives in inline styles / data attributes: Python rewrites the chip's class list.
(function () {
  const HANDOFF_MS = 4000; // a chip appearing later than this after the box went: no slide
  const PAD = 4;
  let handoff = null; // {left, top, at}

  window.ppAskHandoff = function () {
    const card = document.querySelector('.pp-askpop .pp-askpop-card');
    if (!card || card.getClientRects().length === 0) return;
    const r = card.getBoundingClientRect();
    handoff = { left: r.left, top: r.top, at: performance.now() };
  };

  function target(chip) {
    const spot = [...document.querySelectorAll('.pp-aichip-spot')].find((s) => s.getClientRects().length);
    const h = chip.offsetHeight;
    if (!spot) return handoff ? { x: handoff.left, y: handoff.top, scroller: null } : null;
    const r = spot.getBoundingClientRect();
    const scroller = spot.closest('.cm-scroller');
    const box = scroller ? scroller.getBoundingClientRect() : { top: 0, bottom: window.innerHeight };
    const y = r.top + Math.max(0, (r.height - h) / 2);
    return {
      x: r.left,
      y: Math.max(box.top + PAD, Math.min(y, box.bottom - h - PAD)),
      scroller,
    };
  }

  let running = false;
  function follow() {
    const chips = [...document.querySelectorAll('.pp-aiprog-follow')];
    if (!chips.length) { running = false; return; }
    for (const chip of chips) {
      const t = target(chip);
      if (!t) { // nowhere to go (no box, no spot): the chip's usual place at the bottom
        if (!chip.dataset.ppPlaced) { chip.dataset.ppPlaced = '1'; chip.dataset.ppFree = '1'; }
        continue;
      }
      if (chip.dataset.ppFree) continue;
      const scrollTop = t.scroller ? t.scroller.scrollTop : 0;
      const to = `translate(${Math.round(t.x)}px, ${Math.round(t.y)}px)`;
      if (!chip.dataset.ppPlaced) {
        chip.dataset.ppPlaced = '1';
        const fresh = handoff && performance.now() - handoff.at < HANDOFF_MS;
        if (fresh) { // from the box's place, then a slide to the spot
          chip.style.transition = 'none';
          chip.style.transform = `translate(${Math.round(handoff.left)}px, ${Math.round(handoff.top)}px)`;
          chip.getBoundingClientRect();
        }
        chip.style.transition = '';
        chip.style.visibility = 'visible';
        handoff = null;
      } else if (+chip.dataset.ppScroll !== scrollTop) {
        chip.style.transition = 'none'; // the note scrolled: stay on the text, no lag
      } else if (chip.style.transition === 'none') {
        chip.style.transition = '';
      }
      chip.dataset.ppScroll = String(scrollTop);
      if (chip.style.transform !== to) chip.style.transform = to;
    }
    requestAnimationFrame(follow);
  }
  window.ppEachFrame(function () {
    if (!running && document.querySelector('.pp-aiprog-follow')) {
      running = true;
      requestAnimationFrame(follow);
    }
  });
})();
