// Chat input: Enter sends, Shift+Enter or Ctrl+Enter makes a new line (the textarea is Quasar's, so this is
// done with one delegated listener). The chat log keeps itself scrolled to the newest text.
// The list over the box (@ notes, / commands; drawn by chat.py): ↑ / ↓ move its highlight,
// Enter or Tab picks the highlighted row, Esc closes it. What a pick does is decided in Python.
document.addEventListener('keydown', function (e) {
  const area = e.target && e.target.closest && e.target.closest('.pp-chat-input textarea');
  if (!area || area.closest('.pp-askpop') || e.isComposing) return;
  const compose = area.closest('.pp-chat-compose');
  const list = compose && compose.querySelector('.pp-chat-mentions');
  if (!list || list.getClientRects().length === 0) return;
  const rows = [...list.querySelectorAll('.pp-chat-pick')];
  const at = rows.findIndex((r) => r.classList.contains('pp-chat-pick-active'));
  if (rows.length && (e.key === 'ArrowDown' || e.key === 'ArrowUp')) {
    const next = (at + (e.key === 'ArrowDown' ? 1 : -1) + rows.length) % rows.length;
    rows.forEach((r, i) => r.classList.toggle('pp-chat-pick-active', i === next));
    rows[next].scrollIntoView({ block: 'nearest' });
  } else if (rows.length && (e.key === 'Tab' || (e.key === 'Enter' && !e.shiftKey && !e.ctrlKey))) {
    const row = rows[Math.max(0, at)];
    emitEvent('pp_chat_pick', { kind: row.dataset.kind, id: row.dataset.id });
  } else if (e.key === 'Escape') {
    emitEvent('pp_chat_pick', { kind: 'close' });
  } else {
    return;
  }
  e.preventDefault();
  e.stopImmediatePropagation();
}, true);
document.addEventListener('mouseover', function (e) {  // the mouse moves the highlight too
  const row = e.target && e.target.closest && e.target.closest('.pp-chat-mentions .pp-chat-pick');
  if (!row || row.classList.contains('pp-chat-pick-active')) return;
  row.parentElement.querySelectorAll('.pp-chat-pick').forEach((r) => r.classList.toggle('pp-chat-pick-active', r === row));
});
document.addEventListener('keydown', function (e) {
  const area = e.target && e.target.closest && e.target.closest('.pp-chat-input textarea');
  if (!area || area.closest('.pp-askpop') || e.key !== 'Enter' || e.shiftKey || e.isComposing) return;
  e.preventDefault();
  if (e.ctrlKey || e.metaKey) {  // Ctrl+Enter: a new line (askpop.js)
    e.stopPropagation();
    window.ppNewLine(area);
    return;
  }
  emitEvent('pp_chat_send', {});
}, true);
window.ppChatScroll = function (id) {
  const el = document.getElementById(id);
  if (el) el.scrollTop = el.scrollHeight;
};
// The floating jump buttons: smooth scroll; each one shows only when there is somewhere to go
// (checked on scroll and every 400 ms, since new or streamed messages do not scroll the log).
window.ppChatJump = function (id, where) {
  const el = document.getElementById(id);
  if (el) el.scrollTo({ top: where === 'top' ? 0 : el.scrollHeight, behavior: 'smooth' });
};
(function () {
  const ROOM = 120;
  const update = function (el) {
    const wrap = el.parentElement;
    if (!wrap) return;
    wrap.classList.toggle('pp-can-up', el.scrollTop > ROOM);
    wrap.classList.toggle('pp-can-down', el.scrollHeight - el.clientHeight - el.scrollTop > ROOM);
  };
  document.addEventListener('scroll', function (e) {
    if (e.target && e.target.classList && e.target.classList.contains('pp-chat-log')) update(e.target);
  }, true);
  setInterval(function () { document.querySelectorAll('.pp-chat-log').forEach(update); }, 400);
})();
// A click anywhere outside the attached-selection chips folds the open one.
document.addEventListener('mousedown', function (e) {
  if (e.target && e.target.closest && e.target.closest('.pp-chat-chips, .pp-chat-preview')) return;
  if (document.querySelector('.pp-chat-chip-open')) emitEvent('pp_chip_close', {});
}, true);
// The composer is one line (+ · text · model · send) until the text needs more room; then the
// text takes the full width above the buttons (`pp-chat-multi` on the card). An empty box is
// measured by its placeholder, so a narrow pane never squeezes "Ask, or @ a note" onto 2 lines.
// It is re-checked when the pane is resized.
(function () {
  const ctx = document.createElement('canvas').getContext('2d');
  function inlineWidth(row) {
    let w = row.clientWidth - 24;  // the row's padding and gaps, plus the text's own padding
    row.querySelectorAll('.pp-chat-plus, .pp-chat-model, .pp-chat-send').forEach(function (el) { w -= el.offsetWidth; });
    return w;
  }
  function singleLine(area) {  // an empty box is one line high, whatever its placeholder does
    const c = getComputedStyle(area);
    return parseFloat(c.lineHeight) + parseFloat(c.paddingTop) + parseFloat(c.paddingBottom);
  }
  window.ppChatFit = function (area) {
    const card = area.closest('.pp-chat-card');
    const row = area.closest('.pp-chat-row');
    if (!card || !row) return;
    const text = area.value || area.placeholder || '';
    let multi = area.value.indexOf('\n') >= 0;
    if (!multi && text) {
      ctx.font = getComputedStyle(area).font;
      multi = ctx.measureText(text).width > inlineWidth(row);
    }
    card.classList.toggle('pp-chat-multi', multi);
    // always re-measure: a height left from a narrower moment (or a wrapped placeholder) must
    // not stay behind, or the one-line box keeps a second, empty line
    area.style.height = 'auto';
    area.style.height = (area.value ? area.scrollHeight : area.scrollHeight && singleLine(area)) + 'px';
  };
  document.addEventListener('input', function (e) {
    const area = e.target && e.target.closest && e.target.closest('.pp-chat-input textarea');
    if (area) window.ppChatFit(area);
  }, true);
  // follow the card's width (pane resized, opened, the window resized)
  const sizes = new ResizeObserver(function (entries) {
    entries.forEach(function (entry) {
      const area = entry.target.querySelector('.pp-chat-input textarea');
      if (area) window.ppChatFit(area);
    });
  });
  const watched = new WeakSet();
  window.ppEachFrame(function () {  // after DOM changes, at most once per frame
    document.querySelectorAll('.pp-chat-card').forEach(function (card) {
      if (!watched.has(card)) { watched.add(card); sizes.observe(card); }
    });
  });
})();
// A code block in any chat (the chat pane, the Ask box's mini chat) gets a Copy button in its
// corner on hover. It is added on the first hover, so a re-drawn answer needs nothing else.
(function () {
  const ICON_MS = 1200;
  document.addEventListener('mouseover', function (e) {
    const pre = e.target && e.target.closest && e.target.closest('.pp-msg-body pre');
    if (!pre || pre.querySelector(':scope > .pp-code-copy')) return;
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'pp-code-copy';
    button.dataset.tip = 'Copy code';
    button.innerHTML = window.ppIconSvg('copy', 's');
    button.addEventListener('mousedown', function (ev) { ev.preventDefault(); }); // keep the selection
    button.addEventListener('click', function (ev) {
      ev.stopPropagation();
      const code = pre.querySelector('code');
      const text = code ? code.textContent : [...pre.childNodes].filter((n) => n !== button).map((n) => n.textContent).join('');
      if (navigator.clipboard) navigator.clipboard.writeText(text.replace(/\n$/, ''));
      button.innerHTML = window.ppIconSvg('check', 's');
      setTimeout(function () { button.innerHTML = window.ppIconSvg('copy', 's'); }, ICON_MS);
    });
    pre.appendChild(button);
  });
})();
// Mentions in the chat box are shown in the accent colour (user 2026-11-06). A textarea cannot
// colour part of its text, so a copy of the text is drawn right behind it (same font, padding,
// wrapping and scroll) with the mentions marked, and the textarea's own text is see-through (its
// caret and selection stay). Painted on input and every 250 ms (Python sets the value too).
(function () {
  const TOKEN = /@\[\[[^\[\]\n]+\]\]|(^|[^\w@])(@(?:[^\s@\[\]]|\u00a0)+)/g;  // a name's spaces are no-break ones
  const COPY = ['fontFamily', 'fontSize', 'fontWeight', 'lineHeight', 'letterSpacing', 'wordSpacing',
    'paddingTop', 'paddingRight', 'paddingBottom', 'paddingLeft', 'tabSize'];
  const esc = (s) => s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  const marked = (text) => esc(text).replace(TOKEN, function (all, before, word) {
    if (word === undefined) return '<span class="pp-at">' + all + '</span>';
    return before + '<span class="pp-at">' + word + '</span>';
  });
  function paint(area) {
    let back = area.previousElementSibling;
    if (!back || !back.classList.contains('pp-chat-back')) {
      back = document.createElement('div');
      back.className = 'pp-chat-back';
      back.setAttribute('aria-hidden', 'true');
      area.before(back);
      area.dataset.ppBack = '1';
      area.addEventListener('scroll', function () { back.scrollTop = area.scrollTop; });
    }
    const st = getComputedStyle(area);
    COPY.forEach(function (k) { if (back.style[k] !== st[k]) back.style[k] = st[k]; });
    back.style.left = area.offsetLeft + 'px';
    back.style.top = area.offsetTop + 'px';
    back.style.width = area.clientWidth + 'px';
    back.style.height = area.clientHeight + 'px';
    if (back.dataset.v !== area.value) {
      back.dataset.v = area.value;
      back.innerHTML = marked(area.value) + '​';  // a closing newline still takes a line
    }
    back.scrollTop = area.scrollTop;
  }
  const all = function () { document.querySelectorAll('.pp-chat-input textarea').forEach(paint); };
  document.addEventListener('input', function (e) {
    const area = e.target && e.target.closest && e.target.closest('.pp-chat-input textarea');
    if (area) requestAnimationFrame(function () { paint(area); });  // after ppChatFit's height
  }, true);
  setInterval(all, 250);
})();
