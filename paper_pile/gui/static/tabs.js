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
