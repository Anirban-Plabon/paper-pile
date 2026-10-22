// Thin capture layer for the frameless native window (paper_pile/gui/window.py).
// A press on an empty part of a top row (.pp-dragzone) or on an edge strip (.pp-resize) is
// reported; the compositor then moves/resizes the window (see native_boot.py).
(function () {
  const SKIP = '.pp-tab, .pp-rtab, button, input, .q-btn, .pp-rtab-close';
  const maxed = () => document.body.classList.contains('pp-maximized');
  const send = (op, extra) => emitEvent('pp_win', Object.assign({ op: op, max: maxed() }, extra || {}));
  const zoneOf = (el) => (el && el.closest ? el.closest('.pp-dragzone') : null);
  const TABS = '.pp-tabstrip, .pp-rtabbar';

  document.addEventListener('mousedown', (e) => {
    if (e.button !== 0) return;
    const edge = e.target.closest ? e.target.closest('.pp-resize') : null;
    if (edge) send('gesture', { edge: edge.dataset.edge });
    else if (zoneOf(e.target) && !e.target.closest(SKIP)) {
      // the second press of a double-click on a tab row starts no move (a compositor may take a
      // double-click on a move gesture as "maximize")
      if (e.detail > 1 && e.target.closest(TABS)) return;
      send('gesture', { edge: 'move' });
    }
    else return;
    e.preventDefault();
  });

  // a double-click on an empty part of a top row maximizes / restores; never on a tab row (tabs
  // and the space beside them: double-clicking tabs is for tabs)
  document.addEventListener('dblclick', (e) => {
    if (zoneOf(e.target) && !e.target.closest(SKIP) && !e.target.closest(TABS)) send('maximize');
  });
})();
