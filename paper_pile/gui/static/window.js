// Thin capture layer for the frameless native window (paper_pile/gui/window.py).
// A press on an empty part of a top row (.pp-dragzone) or on an edge strip (.pp-resize) is
// reported; the compositor then moves/resizes the window (see native_boot.py).
(function () {
  const SKIP = '.pp-tab, .pp-rtab, button, input, .q-btn, .pp-rtab-close';
  const maxed = () => document.body.classList.contains('pp-maximized');
  const send = (op, extra) => emitEvent('pp_win', Object.assign({ op: op, max: maxed() }, extra || {}));
  const zoneOf = (el) => (el && el.closest ? el.closest('.pp-dragzone') : null);

  document.addEventListener('mousedown', (e) => {
    if (e.button !== 0) return;
    const edge = e.target.closest ? e.target.closest('.pp-resize') : null;
    if (edge) send('gesture', { edge: edge.dataset.edge });
    else if (zoneOf(e.target) && !e.target.closest(SKIP)) send('gesture', { edge: 'move' });
    else return;
    e.preventDefault();
  });

  document.addEventListener('dblclick', (e) => {
    if (zoneOf(e.target) && !e.target.closest(SKIP)) send('maximize');
  });
})();
