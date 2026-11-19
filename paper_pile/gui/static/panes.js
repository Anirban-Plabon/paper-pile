// Dragging the edge of the file tree or the right pane on past its narrowest width folds that
// pane away (like Obsidian/VS Code); the edge is highlighted while it is held. A double-click on
// the edge folds the pane, or unfolds a folded one; a folded file tree also opens when its edge is
// pulled to the right. Capture only: Python decides (events
// `pp_pane_collapse`, `pp_pane_toggle`).
(() => {
  const FOLD_RATIO = 0.3; // pulled this share of its narrowest width past it, the pane slides shut
  // Animate the pane's max-width (Quasar owns `width`) to 0, then call `done`. The cap stays until
  // Python has folded the splitter, or the pane would show for a frame at full width.
  const slideShut = (el, done) => {
    if (!el) return done();
    const ms = parseFloat(getComputedStyle(document.documentElement).getPropertyValue("--pp-motion") || "1") * 160;
    el.style.setProperty("max-width", el.getBoundingClientRect().width + "px", "important");
    el.style.setProperty("overflow", "hidden", "important");
    el.dataset.ppSliding = "1"; // app.css: no scrollbars inside while it narrows
    void el.offsetWidth; // start the transition from the current width
    el.style.setProperty("transition", `max-width ${ms}ms ease`, "important");
    el.style.setProperty("max-width", "0px", "important");
    setTimeout(() => {
      done();
      setTimeout(() => {
        ["max-width", "overflow", "transition"].forEach((k) => el.style.removeProperty(k));
        delete el.dataset.ppSliding;
      }, 600);
    }, ms);
  };
  const OPEN_PX = 24; // how far a folded file tree's edge must be pulled to open it
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
      if (!min) {
        // the folded file tree: dragging its edge to the right opens it
        if (pane !== "left") return;
        const x0 = e.clientX;
        sep.classList.add("pp-sep-active");
        const pull = (ev) => {
          if (ev.clientX - x0 > OPEN_PX) {
            done();
            emitEvent("pp_pane_toggle", { pane });
          }
        };
        const done = () => {
          sep.classList.remove("pp-sep-active");
          window.removeEventListener("pointermove", pull);
          window.removeEventListener("pointerup", done);
        };
        window.addEventListener("pointermove", pull);
        window.addEventListener("pointerup", done);
        return;
      }
      const rect = box.getBoundingClientRect();
      const el = box.querySelector(
        pane === "left" ? ":scope > .q-splitter__before" : ":scope > .q-splitter__after",
      );
      sep.classList.add("pp-sep-active");
      // The splitter stops at the narrowest width; pulled on past FOLD_RATIO of it, the pane
      // slides shut (an animation, not a jump) and Python folds it once the slide has ended.
      const move = (ev) => {
        const width = pane === "left" ? ev.clientX - rect.left : rect.right - ev.clientX;
        if (width < min * (1 - FOLD_RATIO)) {
          stop();
          slideShut(el, () => emitEvent("pp_pane_collapse", { pane }));
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
