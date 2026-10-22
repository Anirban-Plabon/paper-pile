// Drag a note from the file tree or from a tab onto an editor (EditorPane._on_note_drop).
// Capture only: which note, which side; the drop is taken before CodeMirror sees it (it would
// insert the path as text). Split: the side under the pointer. One editor: its right half
// means "open in a split", the rest "open here".
(function () {
  let note = null; // {path} from a tree row, {doc} from a tab
  let lit = null;
  const unlight = () => {
    if (lit) lit.classList.remove('pp-drop-here', 'pp-drop-split');
    lit = null;
  };

  document.addEventListener('dragstart', (e) => {
    const row = e.target.closest && e.target.closest('.pp-tree-row');
    const tab = e.target.closest && e.target.closest('.pp-tab');
    if (row) note = row.dataset.dir === '1' ? null : { path: row.dataset.path };
    else note = tab ? { doc: tab.dataset.doc } : null;
  }, true);

  function zone(e) {
    if (!note || !e.target.closest) return null;
    const area = e.target.closest('.pp-editor-area');
    if (!area) return null;
    const split = area.querySelector('.pp-split.pp-split-on');
    if (split) {
      const panes = Array.from(split.querySelectorAll(':scope > .pp-split-pane'));
      const slot = panes.findIndex((p) => p.contains(e.target));
      return slot < 0 ? null : { el: panes[slot], cls: 'pp-drop-here', slot: slot, split: false };
    }
    const r = area.getBoundingClientRect();
    const empty = area.querySelector('.pp-empty');
    const right = !(empty && empty.offsetParent) && e.clientX > r.left + r.width / 2;
    return { el: area, cls: right ? 'pp-drop-split' : 'pp-drop-here', slot: 0, split: right };
  }

  document.addEventListener('dragover', (e) => {
    const z = zone(e);
    if (!z) { unlight(); return; }
    e.preventDefault();
    e.stopPropagation();
    e.dataTransfer.dropEffect = 'move';  // tree rows and tabs allow 'move' only: 'copy' would refuse the drop
    if (lit !== z.el || !lit.classList.contains(z.cls)) {
      unlight();
      lit = z.el;
      lit.classList.add(z.cls);
    }
  }, true);

  document.addEventListener('drop', (e) => {
    const z = zone(e);
    const what = note;
    note = null;
    unlight();
    if (!z) return;
    e.preventDefault();
    e.stopPropagation();
    emitEvent('pp_note_drop', Object.assign({ slot: z.slot, split: z.split }, what));
  }, true);

  document.addEventListener('dragend', () => { note = null; unlight(); }, true);
})();
