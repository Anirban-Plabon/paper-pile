// The formatting menu (gui/components/format_menu.py, PLAN §4.38): place it at the point it was
// opened from (kept inside the window and above the taskbar strip, --pp-inset-bottom), place it
// again when its content changes (More, Customize, Colour…), and report a mouse-down outside it
// or Esc. What any item does is Python's.
(function () {
  const MARGIN = 6;
  let at = null; // {x, y}: where it was opened
  const menu = () => document.querySelector('.pp-fmenu');
  const shown = (el) => !!el && el.getClientRects().length > 0; // fixed: no offsetParent
  const inset = (name) =>
    parseFloat(getComputedStyle(document.documentElement).getPropertyValue(name)) || 0;

  function place() {
    const el = menu();
    if (!el || !at) return;
    const w = el.offsetWidth, h = el.offsetHeight;
    const top = inset('--pp-inset-top') + MARGIN;
    const bottom = window.innerHeight - inset('--pp-inset-bottom') - MARGIN;
    let x = at.x, y = at.y + 2;
    if (x + w > window.innerWidth - MARGIN) x = Math.max(MARGIN, window.innerWidth - MARGIN - w);
    if (y + h > bottom) y = Math.max(top, at.y - h - 2 >= top ? at.y - h - 2 : bottom - h);
    el.style.left = `${Math.round(x)}px`;
    el.style.top = `${Math.round(y)}px`;
  }

  window.ppFmenuPlace = (x, y) => {
    at = { x, y };
    requestAnimationFrame(place);
  };
  // the content changed (a sub-view): keep the corner it opened at, but stay inside the window
  window.ppFmenuReplace = () => requestAnimationFrame(() => requestAnimationFrame(place));

  document.addEventListener('mousedown', (e) => {
    const el = menu();
    if (shown(el) && !el.contains(e.target)) emitEvent('pp_fmenu_close', {});
  }, true);
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && shown(menu())) {
      e.preventDefault();
      e.stopPropagation();
      emitEvent('pp_fmenu_close', {});
    }
  }, true);
  window.addEventListener('resize', () => requestAnimationFrame(place));
})();
