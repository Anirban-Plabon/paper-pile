// Keeps popup menus inside the part of the window the user can see (loaded by gui/app.py).
// 1. Quasar places a q-menu once, when it opens. A menu whose items Python fills on
//    "before-show" (chat +, model, ⋮) grows after that, downward past the window edge:
//    re-place it whenever its size changes.
// 2. Quasar (and our own context menu) measure against window.innerHeight, but a maximized
//    WSL window lies under the Windows taskbar (--pp-inset-bottom, native_boot.py): lift the
//    menu above that strip.
(function () {
  const inset = (name) =>
    parseFloat(getComputedStyle(document.documentElement).getPropertyValue(name)) || 0;
  const MARGIN = 4;

  function keepInside(el) {
    const r = el.getBoundingClientRect();
    if (!r.height) return; // closed
    const top = inset('--pp-inset-top') + MARGIN;
    const bottom = window.innerHeight - inset('--pp-inset-bottom') - MARGIN;
    if (r.top >= top && r.bottom <= bottom) return;
    const room = bottom - top;
    if (r.height > room) el.style.maxHeight = room + 'px';
    el.style.top = Math.max(top, Math.min(r.top, bottom - Math.min(r.height, room))) + 'px';
  }

  const sizes = new ResizeObserver((entries) => {
    for (const { target } of entries) {
      if (target.classList.contains('q-menu') && target.id) {
        const menu = getElement(target);
        if (menu && menu.updatePosition) menu.updatePosition();
      }
      keepInside(target);
    }
  });
  const watch = (node) => {
    if (!(node instanceof Element)) return;
    if (node.matches('.q-menu, .pp-ctxmenu')) sizes.observe(node);
    node.querySelectorAll('.q-menu, .pp-ctxmenu').forEach((el) => sizes.observe(el));
  };
  // menus are teleported straight into <body> (Quasar portals, ui.teleport)
  new MutationObserver((records) => {
    for (const rec of records) rec.addedNodes.forEach(watch);
  }).observe(document.body, { childList: true });
  watch(document.body);
})();
