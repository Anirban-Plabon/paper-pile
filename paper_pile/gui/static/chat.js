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
  if (e.target && e.target.closest && e.target.closest('.pp-chat-chips')) return;
  if (document.querySelector('.pp-chat-chip-open')) emitEvent('pp_chip_close', {});
}, true);
