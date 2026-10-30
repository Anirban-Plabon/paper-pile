// Chat input: Enter sends, Shift+Enter or Ctrl+Enter makes a new line (the textarea is Quasar's, so this is
// done with one delegated listener). The chat log keeps itself scrolled to the newest text.
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
