// Ctrl + mouse wheel zooms the text of the note on screen (PLAN §4.34): per note, not saved
// (gone when the app restarts), 50–300 %; Ctrl+0 back to 100 %. Each side of a split shows its
// own note's zoom. The factor goes on the editor's root as a font-size, so everything sized in
// em (headings, code, widgets) follows.
import { EditorView, ViewPlugin } from "@codemirror/view";
import { rtOf, measureAgain } from "./context.js";

const MIN = 0.5;
const MAX = 3;
const STEP = 0.1;
// per note path, shared by both editors of a split on purpose: it is the note's zoom
const zooms = new Map();

function apply(view) {
  const z = zooms.get(rtOf(view.state).notePath) ?? 1;
  const size = z === 1 ? "" : `${Math.round(z * 100)}%`;
  if (view.dom.style.fontSize === size) return;
  view.dom.style.fontSize = size;
  measureAgain(view);
}

function zoomBy(view, delta) {
  const path = rtOf(view.state).notePath;
  const now = zooms.get(path) ?? 1;
  const next = delta === 0 ? 1 : Math.min(MAX, Math.max(MIN, Math.round((now + delta) * 10) / 10));
  if (next === 1) zooms.delete(path);
  else zooms.set(path, next);
  apply(view);
  // the same note in the other side of a split follows
  for (const el of document.querySelectorAll(".cm-editor")) {
    const other = EditorView.findFromDOM(el);
    if (other && other !== view && rtOf(other.state).notePath === path) apply(other);
  }
}

export const resetZoom = (view) => {
  zoomBy(view, 0);
  return true;
};

export const noteZoom = ViewPlugin.fromClass(
  class {
    constructor(view) {
      this.view = view;
      this.path = rtOf(view.state).notePath;
      // not passive: the wheel must not also scroll the note (or zoom the whole web view)
      this.onWheel = (e) => {
        if (!e.ctrlKey || e.deltaY === 0) return;
        e.preventDefault();
        zoomBy(view, e.deltaY < 0 ? STEP : -STEP);
      };
      view.dom.addEventListener("wheel", this.onWheel, { passive: false });
      apply(view);
    }
    update() {
      const path = rtOf(this.view.state).notePath;
      if (path !== this.path) {
        this.path = path;
        apply(this.view);
      }
    }
    destroy() {
      this.view.dom.removeEventListener("wheel", this.onWheel);
    }
  },
);
