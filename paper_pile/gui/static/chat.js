// Chat input: Enter sends, Shift+Enter makes a new line (the textarea is Quasar's, so this is
// done with one delegated listener). The chat log keeps itself scrolled to the newest text.
document.addEventListener('keydown', function (e) {
  const area = e.target && e.target.closest && e.target.closest('.pp-chat-input textarea');
  if (!area || e.key !== 'Enter' || e.shiftKey || e.isComposing) return;
  e.preventDefault();
  emitEvent('pp_chat_send', {});
}, true);
window.ppChatScroll = function (id) {
  const el = document.getElementById(id);
  if (el) el.scrollTop = el.scrollHeight;
};
// A click anywhere outside the attached-selection chips folds the open one.
document.addEventListener('mousedown', function (e) {
  if (e.target && e.target.closest && e.target.closest('.pp-chat-chips, .pp-chat-preview')) return;
  if (document.querySelector('.pp-chat-chip-open')) emitEvent('pp_chip_close', {});
}, true);
// The composer is one line (+ · text · model · send) until the text needs more room; then the
// text takes the full width above the buttons (`pp-chat-multi` on the card).
(function () {
  const ctx = document.createElement('canvas').getContext('2d');
  function inlineWidth(row) {
    let w = row.clientWidth - 24;  // the row's padding and gaps, plus the text's own padding
    row.querySelectorAll('.pp-chat-plus, .pp-chat-model, .pp-chat-send').forEach(function (el) { w -= el.offsetWidth; });
    return w;
  }
  window.ppChatFit = function (area) {
    const card = area.closest('.pp-chat-card');
    const row = area.closest('.pp-chat-row');
    if (!card || !row) return;
    let multi = area.value.indexOf('\n') >= 0;
    if (!multi && area.value) {
      ctx.font = getComputedStyle(area).font;
      multi = ctx.measureText(area.value).width > inlineWidth(row);
    }
    if (card.classList.contains('pp-chat-multi') === multi) return;
    card.classList.toggle('pp-chat-multi', multi);
    area.style.height = 'auto';  // its width changed: let autogrow measure again
    area.style.height = area.scrollHeight + 'px';
  };
  document.addEventListener('input', function (e) {
    const area = e.target && e.target.closest && e.target.closest('.pp-chat-input textarea');
    if (area) window.ppChatFit(area);
  }, true);
})();
