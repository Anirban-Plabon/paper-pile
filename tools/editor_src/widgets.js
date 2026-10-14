// Small inline widgets for Live Preview. Render-only; the only interaction is the task checkbox,
// which dispatches a one-character change through the normal editor path (undo, autosave).
import { WidgetType } from "@codemirror/view";
import katex from "katex";

export class MathWidget extends WidgetType {
  constructor(src) {
    super();
    this.src = src;
  }
  eq(other) {
    return other.src === this.src;
  }
  toDOM() {
    const el = document.createElement("span");
    el.className = "pp-math";
    el.innerHTML = katex.renderToString(this.src, { throwOnError: false });
    return el;
  }
  ignoreEvent() {
    return false;
  }
}

// Replaces a bullet list marker (`-`, `*`, `+`); one character wide, so columns do not move.
export class BulletWidget extends WidgetType {
  constructor(glyph) {
    super();
    this.glyph = glyph;
  }
  eq(other) {
    return other.glyph === this.glyph;
  }
  toDOM() {
    const el = document.createElement("span");
    el.className = "pp-bullet";
    el.textContent = this.glyph;
    return el;
  }
}

// Replaces `- [ ]` / `- [x]`. `offset` is where the state character sits relative to the widget.
export class CheckboxWidget extends WidgetType {
  constructor(checked, offset) {
    super();
    this.checked = checked;
    this.offset = offset;
  }
  eq(other) {
    return other.checked === this.checked && other.offset === this.offset;
  }
  toDOM(view) {
    const el = document.createElement("span");
    el.className = "pp-task" + (this.checked ? " pp-task-checked" : "");
    el.setAttribute("role", "checkbox");
    el.setAttribute("aria-checked", String(this.checked));
    const box = document.createElement("span");
    box.className = "pp-box";
    el.appendChild(box);
    el.addEventListener("mousedown", (e) => {
      e.preventDefault(); // the caret must not jump into the line
      const pos = view.posAtDOM(el) + this.offset;
      view.dispatch({ changes: { from: pos, to: pos + 1, insert: this.checked ? " " : "x" } });
      view.focus(); // preventDefault kept focus where it was; Ctrl+Z must reach the editor
    });
    return el;
  }
  ignoreEvent() {
    return true; // handled above; keep the editor from also acting on the click
  }
}

export class HrWidget extends WidgetType {
  eq() {
    return true;
  }
  toDOM() {
    const el = document.createElement("span");
    el.className = "pp-hr";
    return el;
  }
}
