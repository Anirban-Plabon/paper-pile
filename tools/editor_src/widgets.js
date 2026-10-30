// Small inline widgets for Live Preview. Render-only; the only interaction is the task checkbox,
// which dispatches a one-character change through the normal editor path (undo, autosave).
import { WidgetType } from "@codemirror/view";
import katex from "katex";
import { measureAgain, rtOf } from "./context.js";

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
    el.setAttribute("role", "checkbox");
    const box = document.createElement("span");
    box.className = "pp-box";
    el.appendChild(box);
    el.addEventListener("mousedown", (e) => {
      e.preventDefault(); // the caret must not jump into the line
      const pos = view.posAtDOM(el) + el._offset;
      view.dispatch({ changes: { from: pos, to: pos + 1, insert: el._checked ? " " : "x" } });
      view.focus(); // preventDefault kept focus where it was; Ctrl+Z must reach the editor
    });
    this.updateDOM(el);
    return el;
  }
  // Kept in place on a toggle, so only a box the user just ticked plays its tick (`pp-task-pop`),
  // never one that merely scrolls into view.
  updateDOM(el) {
    const ticked = el._checked === false && this.checked;
    el._checked = this.checked;
    el._offset = this.offset;
    el.className = "pp-task" + (this.checked ? " pp-task-checked" : "") + (ticked ? " pp-task-pop" : "");
    el.setAttribute("aria-checked", String(this.checked));
    return true;
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
      el.className = "pp-code"; // the same chip as inline code outside a table
      el.textContent = state.sliceDoc(marks[0] ? marks[0].to : c.from, marks.length > 1 ? marks[marks.length - 1].from : c.to);
      out.append(el);
    } else if (c.name === "Link") {
      const marks = c.getChildren("LinkMark");
      const el = document.createElement("span");
      el.className = "pp-link";
      if (marks.length > 1) walk(state, c, marks[0].to, marks[1].from, el);
      out.append(el);
    } else if (c.name === "WikiLink") {
      const inner = state.sliceDoc(c.from + 2, c.to - 2);
      const bar = inner.indexOf("|");
      const el = document.createElement("span");
      el.className = "pp-wikilink";
      el.textContent = bar < 0 ? inner.trim() : inner.slice(bar + 1).trim() || inner.slice(0, bar).trim();
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

const MIN_IMAGE_WIDTH = 20;
const REMOTE = /^([a-zA-Z][a-zA-Z0-9+.-]*:|\/\/)/;

// `![alt|300](.note.assets/x.png)`. Only vault images are loaded (through Python's /_pp/asset
// route); a remote URL is shown as a chip and never fetched (offline rule, no tracking pixels).
export class ImageWidget extends WidgetType {
  constructor(src, alt, width, note) {
    super();
    this.src = src;
    this.alt = alt;
    this.width = width;
    this.note = note;
  }
  eq(other) {
    return other.src === this.src && other.alt === this.alt && other.width === this.width && other.note === this.note;
  }
  chip(text, title) {
    const el = document.createElement("span");
    el.className = "pp-image-chip";
    el.textContent = text;
    if (title) el.dataset.tip = title;
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
    img.addEventListener("load", () => measureAgain(view));
    img.addEventListener("error", () => {
      wrap.replaceChildren(this.chip(`image not found: ${this.src}`));
      measureAgain(view);
    });
    wrap.appendChild(img);
    wrap.appendChild(this.handle(wrap, img, view));
    return wrap;
  }
  // Drag the bottom-right corner to resize; only the `|width` number in the source changes
  // (Python makes the edit: `image_resize`).
  handle(wrap, img, view) {
    const handle = document.createElement("span");
    handle.className = "pp-image-handle";
    handle.dataset.tip = "Drag to resize";
    handle.addEventListener("mousedown", (e) => {
      if (e.button !== 0) return;
      e.preventDefault();
      e.stopPropagation();
      const startX = e.clientX;
      const startWidth = img.getBoundingClientRect().width;
      const limit = Math.max(MIN_IMAGE_WIDTH, view.contentDOM.clientWidth - 24);
      const widthAt = (x) => Math.round(Math.max(MIN_IMAGE_WIDTH, Math.min(limit, startWidth + x - startX)));
      wrap.classList.add("pp-image-resizing");
      const move = (ev) => {
        img.style.width = `${widthAt(ev.clientX)}px`;
      };
      const up = (ev) => {
        document.removeEventListener("mousemove", move, true);
        document.removeEventListener("mouseup", up, true);
        wrap.classList.remove("pp-image-resizing");
        const width = widthAt(ev.clientX);
        if (Math.abs(width - startWidth) < 2) return;
        rtOf(view.state).emit("image_resize", { docId: rtOf(view.state).getDocId(), from: view.posAtDOM(wrap), width });
      };
      document.addEventListener("mousemove", move, true);
      document.addEventListener("mouseup", up, true);
    });
    return handle;
  }
  ignoreEvent(event) {
    return !!(event && event.target && event.target.closest && event.target.closest(".pp-image-handle"));
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

// A manual page break (`<div style="page-break-after: always;"></div>`, PLAN §4.17): a dashed
// line with its name in the middle.
export class PageBreakWidget extends WidgetType {
  eq() {
    return true;
  }
  toDOM() {
    const el = document.createElement("span");
    el.className = "pp-page-break-line";
    const label = document.createElement("span");
    label.className = "pp-page-break-label";
    label.textContent = "Page break";
    el.appendChild(label);
    return el;
  }
}

// The `[!note]` of an Obsidian/GitHub callout header, drawn as the bold `Note:` label that a
// `> **Note:**` callout shows, so both spellings look the same.
export class CalloutLabelWidget extends WidgetType {
  constructor(label) {
    super();
    this.label = label;
  }
  eq(other) {
    return other.label === this.label;
  }
  toDOM() {
    const el = document.createElement("span");
    el.className = "pp-strong";
    el.textContent = `${this.label}:`;
    return el;
  }
}
