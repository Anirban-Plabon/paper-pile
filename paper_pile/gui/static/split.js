// Drag the divider between the two editors of a split view (capture only: no state on the
// server, the split is not restored on restart). Double-click: half and half again.
(() => {
  const MIN_PX = 200; // each side keeps at least this much room

  document.addEventListener("pointerdown", (e) => {
    const handle = e.target.closest && e.target.closest(".pp-split-handle");
    if (!handle || e.button !== 0) return;
    e.preventDefault();
    const box = handle.parentElement;
    const first = box.querySelector(".pp-split-pane");
    const rect = box.getBoundingClientRect();
    const move = (ev) => {
      const x = Math.min(Math.max(ev.clientX - rect.left, MIN_PX), rect.width - MIN_PX);
      first.style.flex = `0 0 ${((x / rect.width) * 100).toFixed(2)}%`;
    };
    const up = () => {
      handle.removeEventListener("pointermove", move);
      box.classList.remove("pp-split-dragging");
    };
    handle.setPointerCapture(e.pointerId);
    box.classList.add("pp-split-dragging");
    handle.addEventListener("pointermove", move);
    handle.addEventListener("pointerup", up, { once: true });
    handle.addEventListener("pointercancel", up, { once: true });
  });

  document.addEventListener("dblclick", (e) => {
    const handle = e.target.closest && e.target.closest(".pp-split-handle");
    if (handle) handle.parentElement.querySelector(".pp-split-pane").style.flex = "";
  });
})();

// The tab row lines the right side's tab up with the divider: keep the left side's width in
// --pp-split-left on the editor column (paper_pile/gui/components/tabs.py).
(() => {
  const sizes = new ResizeObserver((entries) => {
    entries.forEach((e) => {
      const column = e.target.closest(".pp-center");
      if (column) column.style.setProperty("--pp-split-left", `${e.target.getBoundingClientRect().width}px`);
    });
  });
  const watched = new WeakSet();
  const watch = () => {
    document.querySelectorAll(".pp-split > .pp-split-pane:first-child").forEach((pane) => {
      if (!watched.has(pane)) { watched.add(pane); sizes.observe(pane); }
    });
  };
  if (window.ppEachFrame) window.ppEachFrame(watch);
  else document.addEventListener("DOMContentLoaded", watch);
})();
