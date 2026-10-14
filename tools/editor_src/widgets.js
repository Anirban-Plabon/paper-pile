// Small inline widgets for Live Preview. Render-only; the only interaction is the task checkbox,
// which dispatches a one-character change through the normal editor path (undo, autosave).
import { WidgetType } from "@codemirror/view";
import katex from "katex";
import { editorContext } from "./context.js";

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

// Renders the inline markdown inside `node` (a table cell) between `from` and `to` as DOM:
// emphasis, strike, code, links (styled, not clickable), math, escapes. Syntax marks are skipped.
const MARKS = new Set(["EmphasisMark", "StrikethroughMark", "CodeMark", "LinkMark", "TableDelimiter"]);

function walk(state, node, from, to, out) {
  let pos = from;
  for (let c = node.firstChild; c; c = c.nextSibling) {
    if (c.to <= from || c.from >= to) continue;
    if (c.from > pos) out.append(state.sliceDoc(pos, c.from));
    pos = Math.max(pos, c.to);
    if (MARKS.has(c.name)) continue;
    const wrapped = { Emphasis: "em", StrongEmphasis: "strong", Strikethrough: "s" }[c.name];
    if (wrapped) {
      const el = document.createElement(wrapped);
      walk(state, c, c.from, c.to, el);
      out.append(el);
    } else if (c.name === "InlineCode") {
      const marks = c.getChildren("CodeMark");
      const el = document.createElement("code");
      el.textContent = state.sliceDoc(marks[0] ? marks[0].to : c.from, marks.length > 1 ? marks[marks.length - 1].from : c.to);
      out.append(el);
    } else if (c.name === "Link") {
      const marks = c.getChildren("LinkMark");
      const el = document.createElement("span");
      el.className = "pp-link";
      if (marks.length > 1) walk(state, c, marks[0].to, marks[1].from, el);
      out.append(el);
    } else if (c.name === "Image") {
      const marks = c.getChildren("LinkMark");
      out.append(marks.length > 1 ? state.sliceDoc(marks[0].to, marks[1].from).replace(/\|\d+$/, "") : "");
    } else if (c.name === "InlineMath") {
      const d = state.sliceDoc(c.from, c.from + 2) === "$$" ? 2 : 1;
      const el = document.createElement("span");
      el.innerHTML = katex.renderToString(state.sliceDoc(c.from + d, c.to - d), { throwOnError: false });
      out.append(el);
    } else if (c.name === "Escape") {
      out.append(state.sliceDoc(c.from + 1, c.to));
    } else if (c.name === "URL") {
      const el = document.createElement("span");
      el.className = "pp-link";
      el.textContent = state.sliceDoc(c.from, c.to);
      out.append(el);
    } else {
      out.append(state.sliceDoc(c.from, c.to));
    }
  }
  if (pos < to) out.append(state.sliceDoc(pos, to));
}

export function renderInline(state, cell) {
  const frag = document.createDocumentFragment();
  walk(state, cell, cell.from, cell.to, frag);
  return frag;
}

const REMOTE = /^([a-zA-Z][a-zA-Z0-9+.-]*:|\/\/)/;

// `![alt|300](.note.assets/x.png)`. Only vault images are loaded (through Python's /_pp/asset
// route); a remote URL is shown as a chip and never fetched (offline rule, no tracking pixels).
export class ImageWidget extends WidgetType {
  constructor(src, alt, width) {
    super();
    this.src = src;
    this.alt = alt;
    this.width = width;
    this.note = editorContext.notePath;
  }
  eq(other) {
    return other.src === this.src && other.alt === this.alt && other.width === this.width && other.note === this.note;
  }
  chip(text, title) {
    const el = document.createElement("span");
    el.className = "pp-image-chip";
    el.textContent = text;
    if (title) el.title = title;
    return el;
  }
  toDOM(view) {
    const wrap = document.createElement("span");
    wrap.className = "pp-image";
    if (REMOTE.test(this.src)) {
      wrap.appendChild(this.chip(this.alt || "remote image", `Remote image not loaded: ${this.src}`));
      return wrap;
    }
    const img = document.createElement("img");
    img.alt = this.alt;
    img.loading = "lazy";
    img.src = `/_pp/asset?note=${encodeURIComponent(this.note)}&path=${encodeURIComponent(this.src)}`;
    if (this.width) img.style.width = `${this.width}px`;
    img.addEventListener("load", () => view.requestMeasure());
    img.addEventListener("error", () => {
      wrap.replaceChildren(this.chip(`image not found: ${this.src}`));
      view.requestMeasure();
    });
    wrap.appendChild(img);
    return wrap;
  }
  ignoreEvent() {
    return false;
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
