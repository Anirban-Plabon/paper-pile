// Thin capture layer for the file tree (paper_pile/gui/components/tree.py).
// It only reports what happened (click, right-click, drop, outside-click); Python decides.
// Rows carry data-path / data-dir; the tree container is .pp-tree.
(function () {
  const rowOf = (el) => (el && el.closest ? el.closest('.pp-tree-row') : null);
  const treeOf = (el) => (el && el.closest ? el.closest('.pp-tree') : null);
  const menuOpen = () => document.querySelector('.pp-ctxmenu-open');
  let dragPath = null;
  let overEl = null;

  // A folder row is a drop target; so is the tree background (= vault root, path "").
  function dropTarget(el) {
    const row = rowOf(el);
    if (row) return row.dataset.dir === '1' ? row : null;
    const tree = treeOf(el);
    return tree && el === tree ? tree : null;
  }
  const targetPath = (t) => (t.classList.contains('pp-tree-row') ? t.dataset.path : '');
  function setOver(t) {
    if (overEl === t) return;
    if (overEl) overEl.classList.remove('pp-drop-target');
    overEl = t;
    if (overEl) overEl.classList.add('pp-drop-target');
  }

  document.addEventListener('dragstart', (e) => {
    const row = rowOf(e.target);
    if (!row) return;
    dragPath = row.dataset.path;
    e.dataTransfer.setData('text/plain', dragPath);
    e.dataTransfer.effectAllowed = 'move';
  });
  document.addEventListener('dragover', (e) => {
    if (dragPath === null) return;
    const t = dropTarget(e.target);
    if (!t) { setOver(null); return; }
    e.preventDefault();
    e.dataTransfer.dropEffect = 'move';
    setOver(t);
  });
  document.addEventListener('dragleave', (e) => {
    if (dragPath !== null && !treeOf(e.relatedTarget)) setOver(null);
  });
  document.addEventListener('drop', (e) => {
    if (dragPath === null) return;
    const t = dropTarget(e.target);
    const src = dragPath;
    dragPath = null;
    setOver(null);
    if (!t) return;
    e.preventDefault();
    emitEvent('pp_tree_move', { src: src, dst: targetPath(t) });
  });
  document.addEventListener('dragend', () => { dragPath = null; setOver(null); });

  document.addEventListener('click', (e) => {
    const row = rowOf(e.target);
    if (row) emitEvent('pp_tree_click', { path: row.dataset.path, isDir: row.dataset.dir === '1' });
    else if (menuOpen() && !e.target.closest('.pp-ctxmenu')) emitEvent('pp_ctx_close', {});
  });
  document.addEventListener('contextmenu', (e) => {
    if (!treeOf(e.target)) return;
    e.preventDefault();
    const row = rowOf(e.target);
    emitEvent('pp_tree_context', {
      path: row ? row.dataset.path : '',
      isDir: row ? row.dataset.dir === '1' : true,
      onRow: !!row,
      x: e.clientX, y: e.clientY,
      vw: window.innerWidth, vh: window.innerHeight,
    });
  });
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && menuOpen()) emitEvent('pp_ctx_close', {});
  });
})();
