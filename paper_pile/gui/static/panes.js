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

// The note's buttons (split · AI · ⋯, gui/components/editor_pane.py `.pp-note-tools`): each
// editor reports where they go (`pp-tools-anchor`: the top of its properties block or first line,
// the right edge of its text; tools/editor_src/notetools.js); the box is placed for the active
// side (the one whose name island is marked, or the only one) and clipped at the top of the
// editor area as the note scrolls up.
(() => {
  const anchors = new WeakMap(); // pane → { top, right }
  function activePane(area) {
    const marked = area.querySelector(".pp-split-head-active");
    return (marked && marked.closest(".pp-split-pane")) || area.querySelector(".pp-split-pane");
  }
  function place(area) {
    const box = area.querySelector(":scope > .pp-note-tools");
    const pane = activePane(area);
    const at = pane && anchors.get(pane);
    if (!box || !at) return;
    const a = area.getBoundingClientRect();
    const top = at.top - a.top;
    box.style.transform = `translate(${Math.round(at.right - a.left - box.offsetWidth)}px, ${Math.round(top)}px)`;
    box.style.clipPath = top < 0 ? `inset(${Math.ceil(-top)}px 0 0 0)` : "";
    if (!box.classList.contains("pp-placed")) box.classList.add("pp-placed");
  }
  document.addEventListener("pp-tools-anchor", (e) => {
    const pane = e.target.closest && e.target.closest(".pp-split-pane");
    const area = pane && pane.closest(".pp-editor-area");
    if (!area) return;
    anchors.set(pane, e.detail);
    place(area);
  });
  // the active side changed (a click on the other side, a split opened / closed)
  new MutationObserver((records) => {
    for (const r of records) {
      if (!r.target.matches || !r.target.matches(".pp-split-head, .pp-split-pane, .pp-split")) continue;
      const area = r.target.closest(".pp-editor-area");
      if (area) place(area);
    }
  }).observe(document.body, { subtree: true, attributes: true, attributeFilter: ["class"] });
})();
