// One icon style everywhere: Lucide line icons served by Python (paper_pile/gui/icons.py).
// ppIcon(name)          -> Quasar icon name ("svguse:...") for icon props
// ppIconSvg(name, size) -> inline <svg> markup for plain DOM (editor widgets, slash menu)
// Quasar's own icons (select arrows, clear crosses, uploader, notifications) are Material names;
// iconMapFn maps them to the same line icons so nothing filled is left.
(function () {
  const cfg = window.__pp_icons || { base: "/_pp/icon", v: "0" };
  const url = (name) => `${cfg.base}/${name}.svg?v=${cfg.v}#i`;
  window.ppIcon = (name) => `svguse:${url(name)}`;
  window.ppIconSvg = (name, size) =>
    `<svg class="pp-i pp-i-${size || "m"}" viewBox="0 0 24 24" aria-hidden="true"><use href="${url(name)}"></use></svg>`;

  const QUASAR = {
    arrow_drop_down: "chevron-down", keyboard_arrow_down: "chevron-down", expand_more: "chevron-down",
    keyboard_arrow_up: "chevron-up", arrow_drop_up: "chevron-up", expand_less: "chevron-up",
    chevron_left: "chevron-left", chevron_right: "chevron-right",
    keyboard_arrow_left: "chevron-left", keyboard_arrow_right: "chevron-right",
    arrow_upward: "arrow-up", arrow_downward: "arrow-down", arrow_back: "arrow-left", arrow_forward: "arrow-right",
    cancel: "x", close: "x", clear: "x", clear_all: "list-x",
    check: "check", check_circle: "circle-check", done: "check", done_all: "check-check",
    error: "circle-alert", warning: "triangle-alert", report_problem: "triangle-alert", info: "info",
    add: "plus", add_box: "square-plus", remove: "minus", cloud_upload: "upload",
    search: "search", menu: "menu", more_vert: "ellipsis-vertical", more_horiz: "ellipsis",
    first_page: "chevrons-left", last_page: "chevrons-right",
    colorize: "pipette", tune: "sliders-horizontal", style: "swatch-book", palette: "palette",
  };
  function install() {
    const plugin = window.Quasar && window.Quasar.IconSet;
    if (!plugin) return;
    plugin.iconMapFn = (name) => (QUASAR[name] ? { icon: window.ppIcon(QUASAR[name]) } : undefined);
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", install);
  else install();
})();

// ppEachFrame(fn): run fn after DOM changes, batched to once per animation frame (the other
// capture scripts use it to find the elements they watch without scanning on every mutation).
window.ppEachFrame = function (fn) {
  let queued = false;
  new MutationObserver(function () {
    if (queued) return;
    queued = true;
    requestAnimationFrame(function () { queued = false; fn(); });
  }).observe(document.documentElement, { childList: true, subtree: true });
  fn();
};
