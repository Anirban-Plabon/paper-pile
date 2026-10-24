// Dragging the edge of the file tree or the right pane on past its narrowest width folds that
// pane away (like Obsidian/VS Code); the edge is highlighted while it is held. A double-click on
// the edge folds the pane, or unfolds a folded one. Capture only: Python decides (events
// `pp_pane_collapse`, `pp_pane_toggle`).
(() => {
  const GRACE_PX = 48; // how far past the narrowest width the pointer must go
  const paneEdge = (el) => {
    const sep = el && el.closest && el.closest(".q-splitter__separator");
    const box = sep && sep.parentElement;
    if (!box || !box.classList.contains("pp-panesplit")) return null;
    return { sep, box, pane: box.classList.contains("pp-panesplit-left") ? "left" : "right" };
  };

  document.addEventListener("dblclick", (e) => {
    const edge = paneEdge(e.target);
    if (edge) emitEvent("pp_pane_toggle", { pane: edge.pane });
  });

  document.addEventListener(
    "pointerdown",
    (e) => {
      const edge = paneEdge(e.target);
      if (!edge || e.button !== 0) return;
      const { sep, box, pane } = edge;
      const min = Number(box.dataset.min || 0);
      if (!min) return; // already folded
      const rect = box.getBoundingClientRect();
      sep.classList.add("pp-sep-active");
      const move = (ev) => {
        const width = pane === "left" ? ev.clientX - rect.left : rect.right - ev.clientX;
        if (width < min - GRACE_PX) {
          stop();
          emitEvent("pp_pane_collapse", { pane });
        }
      };
      const stop = () => {
        sep.classList.remove("pp-sep-active");
        window.removeEventListener("pointermove", move);
        window.removeEventListener("pointerup", stop);
      };
      window.addEventListener("pointermove", move);
      window.addEventListener("pointerup", stop);
    },
    true,
  );
})();

// The handle above the Outline section (gui/components/outline.py): drag to set its height. The
// tree above keeps at least TREE_MIN px. Python stores the final height (event `pp_vsplit`).
(() => {
  const MIN_H = 80;
  const TREE_MIN = 120;
  document.addEventListener("pointerdown", (e) => {
    const handle = e.target.closest && e.target.closest(".pp-vsplit");
    if (!handle || e.button !== 0) return;
    const section = handle.parentElement;
    const list = section.querySelector(".pp-outline");
    const body = section.parentElement;
    if (!list || !body) return;
    e.preventDefault();
    const startY = e.clientY;
    const startH = list.getBoundingClientRect().height;
    const tree = body.querySelector(".pp-tree");
    const treeH = tree ? tree.getBoundingClientRect().height : 0;
    const maxH = Math.max(MIN_H, startH + treeH - TREE_MIN);
    let height = startH;
    handle.classList.add("pp-vsplit-active");
    const move = (ev) => {
      height = Math.round(Math.max(MIN_H, Math.min(maxH, startH + (startY - ev.clientY))));
      section.style.setProperty("--pp-outline-h", height + "px");
    };
    const stop = () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", stop);
      handle.classList.remove("pp-vsplit-active");
      emitEvent("pp_vsplit", { name: handle.dataset.name, height });
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", stop);
  });
})();
