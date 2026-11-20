// Drag a note from the file tree or from a tab onto an editor (EditorPane._on_note_drop), or onto
// the AI chat, which attaches it (EditorPane._on_chat_drop; user 2026-11-09).
// Capture only: which note, which side; the drop is taken before CodeMirror sees it (it would
// insert the path as text). Split: the side under the pointer. One editor: its right half
// means "open in a split", the rest "open here".
(function () {
  let note = null; // {path} from a tree row, {doc} from a tab
  let lit = null;
  const unlight = () => {
    if (lit) lit.classList.remove('pp-drop-here', 'pp-drop-split', 'pp-drop-chat');
    lit = null;
  };

  // Tree rows use HTML5 drag; tabs drag with the pointer (static/tabs.js, Chrome-like) and use
  // the same zones through `window.ppNoteZones`.
  document.addEventListener('dragstart', (e) => {
    const row = e.target.closest && e.target.closest('.pp-tree-row');
    note = row && row.dataset.dir !== '1' ? { path: row.dataset.path } : null;
  }, true);

  function zone(target, x) {
    if (!target || !target.closest) return null;
    const chat = target.closest('.pp-chat');
    if (chat) return { el: chat, cls: 'pp-drop-chat', chat: true };
    const area = target.closest('.pp-editor-area');
    if (!area) return null;
    const split = area.querySelector('.pp-split.pp-split-on');
    if (split) {
      const panes = Array.from(split.querySelectorAll(':scope > .pp-split-pane'));
      const slot = panes.findIndex((p) => p.contains(target));
      return slot < 0 ? null : { el: panes[slot], cls: 'pp-drop-here', slot: slot, split: false };
    }
    const r = area.getBoundingClientRect();
    const empty = area.querySelector('.pp-empty');
    const right = !(empty && empty.offsetParent) && x > r.left + r.width / 2;
    return { el: area, cls: right ? 'pp-drop-split' : 'pp-drop-here', slot: 0, split: right };
  }

  // Light the zone under the pointer; returns it (or null).
  function light(target, x) {
    const z = zone(target, x);
    if (!z) { unlight(); return null; }
    if (lit !== z.el || !lit.classList.contains(z.cls)) {
      unlight();
      lit = z.el;
      lit.classList.add(z.cls);
    }
    return z;
  }

  function send(z, what) {
    if (z.chat) emitEvent('pp_chat_note_drop', what);
    else emitEvent('pp_note_drop', Object.assign({ slot: z.slot, split: z.split }, what));
  }

  window.ppNoteZones = {
    over: (target, x) => !!light(target, x),
    drop: (target, x, what) => {
      const z = zone(target, x);
      unlight();
      if (!z) return false;
      send(z, what);
      return true;
    },
    end: unlight,
  };

  document.addEventListener('dragover', (e) => {
    if (!note) return;
    if (!light(e.target, e.clientX)) return;
    e.preventDefault();
    e.stopPropagation();
    e.dataTransfer.dropEffect = 'move';  // tree rows allow 'move' only: 'copy' would refuse the drop
  }, true);

  document.addEventListener('drop', (e) => {
    const what = note;
    note = null;
    const z = what ? zone(e.target, e.clientX) : null;
    unlight();
    if (!z) return;
    e.preventDefault();
    e.stopPropagation();
    send(z, what);
  }, true);

  document.addEventListener('dragend', () => { note = null; unlight(); }, true);
})();
