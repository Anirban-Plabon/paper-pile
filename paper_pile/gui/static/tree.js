// Thin capture layer for the file tree (paper_pile/gui/components/tree.py).
// It only reports what happened (click, right-click, drop, outside-click, selection box);
// Python decides. Rows carry data-path / data-dir; the tree container is .pp-tree.
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

  // Dragging a selected row takes the whole selection along.
  let dragGroup = null;
  document.addEventListener('dragstart', (e) => {
    const row = rowOf(e.target);
    if (!row) return;
    dragPath = row.dataset.path;
    const picked = row.classList.contains('pp-tree-selected')
      ? [...treeOf(row).querySelectorAll('.pp-tree-row.pp-tree-selected')].map((r) => r.dataset.path)
      : [];
    dragGroup = picked.length > 1 ? picked : null;
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
    emitEvent('pp_tree_move', { src: src, srcs: dragGroup, dst: targetPath(t) });
  });
  document.addEventListener('dragend', () => { dragPath = null; setOver(null); });

  // Selection box: a drag that starts on blank tree space (not a row, not the scrollbar).
  // Rows under the box get .pp-tree-banded while dragging; Python gets the final list.
  let band = null; // {tree, box, x0, y0 (tree content coords), add, moved}
  const contentPos = (tree, e) => {
    const r = tree.getBoundingClientRect();
    return { x: e.clientX - r.left + tree.scrollLeft, y: e.clientY - r.top + tree.scrollTop };
  };
  function bandRows() {
    const { tree, x0, y0, x1, y1 } = band;
    const top = Math.min(y0, y1), bottom = Math.max(y0, y1);
    const left = Math.min(x0, x1), right = Math.max(x0, x1);
    const r = tree.getBoundingClientRect(); // the box is drawn in window coords, clipped to the tree
    const vTop = Math.max(r.top, top + r.top - tree.scrollTop);
    const vBottom = Math.min(r.bottom, bottom + r.top - tree.scrollTop);
    Object.assign(band.box.style, {
      left: Math.max(r.left, left + r.left - tree.scrollLeft) + 'px', top: vTop + 'px',
      width: Math.min(right, r.width) - Math.max(left, 0) + 'px',
      height: Math.max(0, vBottom - vTop) + 'px',
    });
    const hits = [];
    tree.querySelectorAll('.pp-tree-row').forEach((row) => {
      const b = row.getBoundingClientRect();
      const rt = b.top - r.top + tree.scrollTop, rl = b.left - r.left + tree.scrollLeft;
      const hit = rt < bottom && rt + b.height > top && rl < right && rl + b.width > left;
      row.classList.toggle('pp-tree-banded', hit);
      if (hit) hits.push(row.dataset.path);
    });
    return hits;
  }
  function bandMove(e) {
    const p = contentPos(band.tree, e);
    band.x1 = p.x; band.y1 = p.y;
    if (!band.moved && Math.hypot(band.x1 - band.x0, band.y1 - band.y0) < 4) return;
    if (!band.moved) { band.moved = true; document.body.appendChild(band.box); }
    const r = band.tree.getBoundingClientRect(); // past the top/bottom edge: scroll along
    if (e.clientY < r.top) band.tree.scrollTop -= r.top - e.clientY;
    else if (e.clientY > r.bottom) band.tree.scrollTop += e.clientY - r.bottom;
    bandRows();
  }
  function bandEnd(e) {
    document.removeEventListener('mousemove', bandMove);
    document.removeEventListener('mouseup', bandEnd);
    let paths = [];
    if (band.moved) {
      bandMove(e);
      paths = bandRows();
      band.box.remove();
      band.tree.querySelectorAll('.pp-tree-banded').forEach((r) => r.classList.remove('pp-tree-banded'));
    }
    const add = band.add;
    band = null;
    // a plain click on blank space clears the selection; Ctrl+click there keeps it
    if (paths.length || !add) emitEvent('pp_tree_band', { paths: paths, add: add });
  }
  document.addEventListener('mousedown', (e) => {
    const tree = treeOf(e.target);
    if (e.button !== 0 || !tree || e.target !== tree) return;
    if (e.offsetX >= tree.clientWidth || e.offsetY >= tree.clientHeight) return; // scrollbar
    e.preventDefault(); // no text selection
    const p = contentPos(tree, e);
    const box = document.createElement('div');
    box.className = 'pp-tree-band';
    band = { tree, box, x0: p.x, y0: p.y, x1: p.x, y1: p.y, add: e.ctrlKey || e.metaKey, moved: false };
    document.addEventListener('mousemove', bandMove);
    document.addEventListener('mouseup', bandEnd);
  });

  document.addEventListener('click', (e) => {
    const row = rowOf(e.target);
    if (row) {
      emitEvent('pp_tree_click', {
        path: row.dataset.path, isDir: row.dataset.dir === '1',
        toggle: e.ctrlKey || e.metaKey, range: e.shiftKey,
      });
      if (e.shiftKey) window.getSelection().removeAllRanges();
    }
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
