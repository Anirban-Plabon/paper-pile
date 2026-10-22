// Dragging the edge of the file tree or the right pane on past its narrowest width folds that
// pane away (like Obsidian/VS Code). Capture only: Python decides (event `pp_pane_collapse`).
(() => {
  const GRACE_PX = 48; // how far past the narrowest width the pointer must go

  document.addEventListener(
    "pointerdown",
    (e) => {
      const sep = e.target.closest && e.target.closest(".q-splitter__separator");
      const box = sep && sep.parentElement;
      if (!box || e.button !== 0 || !box.classList.contains("pp-panesplit")) return;
      const pane = box.classList.contains("pp-panesplit-left") ? "left" : "right";
      const min = Number(box.dataset.min || 0);
      if (!min) return; // already folded
      const rect = box.getBoundingClientRect();
      const move = (ev) => {
        const width = pane === "left" ? ev.clientX - rect.left : rect.right - ev.clientX;
        if (width < min - GRACE_PX) {
          stop();
          emitEvent("pp_pane_collapse", { pane });
        }
      };
      const stop = () => {
        window.removeEventListener("pointermove", move);
        window.removeEventListener("pointerup", stop);
      };
      window.addEventListener("pointermove", move);
      window.addEventListener("pointerup", stop);
    },
    true,
  );
})();
