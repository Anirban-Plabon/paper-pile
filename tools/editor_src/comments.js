// Comments in the note (PLAN §4.38). A `%%comment%%` is hidden off the caret and its line gets one
// pin in the right margin (`CommentPin`, drawn by livepreview.js); a click on the pin opens a small
// window with that line's comments, each editable (Save / Enter) or deletable. What a change does
// to the text is Python's (`comment_set` -> core/formatting.py `set_comment`); JS only draws.
import { WidgetType } from "@codemirror/view";
import { rtOf } from "./context.js";

const COMMENT = /%%((?:[^\n%]|%(?!%))*)%%/g;
let open = null; // {el, close}

function el(tag, cls, text) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text !== undefined) e.textContent = text;
  return e;
}

const icon = (name) => {
  const s = el("span", "pp-cmt-icon");
  if (window.ppIconSvg) s.innerHTML = window.ppIconSvg(name);
  return s;
};

export function closeCommentPopup() {
  if (open) open.close();
}

// The `%%…%%` of the line holding `pin`, found again now (the text may have moved since drawing).
function lineComments(view, pin) {
  let pos;
  try {
    pos = view.posAtDOM(pin);
  } catch (_) {
    return [];
  }
  const line = view.state.doc.lineAt(pos);
  const out = [];
  for (const m of line.text.matchAll(COMMENT)) out.push({ from: line.from + m.index, body: m[1].trim() });
  return out;
}

function openPopup(view, pin) {
  closeCommentPopup();
  const items = lineComments(view, pin);
  if (!items.length) return;
  const rt = rtOf(view.state);
  const box = el("div", "pp-cmt-pop");
  const head = el("div", "pp-cmt-head");
  head.append(icon("message-square"), el("span", "pp-cmt-title", items.length > 1 ? `${items.length} comments` : "Comment"));
  const x = el("button", "pp-cmt-x");
  x.append(icon("x"));
  x.title = "Close (Esc)";
  head.append(x);
  box.append(head);
  const send = (i, body) => {
    const now = lineComments(view, pin)[i];
    if (now) rt.emit("comment_set", { docId: rt.getDocId(), from: now.from, body });
    close();
  };
  items.forEach((item, i) => {
    const row = el("div", "pp-cmt-item");
    const ta = el("textarea", "pp-cmt-text");
    ta.value = item.body;
    ta.rows = 1;
    ta.spellcheck = true;
    // as tall as its text (border-box: + the 2 px border), scrolling only past 160 px
    const fit = () => {
      ta.style.height = "auto";
      const h = ta.scrollHeight + 2;
      ta.style.height = `${Math.min(h, 160)}px`;
      ta.style.overflowY = h > 160 ? "auto" : "hidden";
    };
    ta.addEventListener("input", fit);
    ta.addEventListener("keydown", (e) => {
      if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(i, ta.value); }
      else if (e.key === "Escape") { e.preventDefault(); close(); view.focus(); }
    });
    const actions = el("div", "pp-cmt-actions");
    const del = el("button", "pp-cmt-btn pp-cmt-del", "Delete");
    const save = el("button", "pp-cmt-btn pp-cmt-save", "Save");
    del.addEventListener("click", () => send(i, ""));
    save.addEventListener("click", () => send(i, ta.value));
    actions.append(del, save);
    row.append(ta, actions);
    box.append(row);
    requestAnimationFrame(fit);
  });
  document.body.appendChild(box);
  // under the pin, its right edge at the pin's right; kept inside the window (and above the
  // taskbar strip, --pp-inset-bottom)
  const r = pin.getBoundingClientRect();
  const inset = parseFloat(getComputedStyle(document.documentElement).getPropertyValue("--pp-inset-bottom")) || 0;
  const b = box.getBoundingClientRect();
  const left = Math.max(8, Math.min(r.right - b.width, innerWidth - b.width - 8));
  let top = r.bottom + 6;
  if (top + b.height > innerHeight - inset - 8) top = Math.max(8, r.top - b.height - 6);
  box.style.left = `${left}px`;
  box.style.top = `${top}px`;
  const outside = (e) => { if (!box.contains(e.target) && !pin.contains(e.target)) close(); };
  const keys = (e) => { if (e.key === "Escape") { close(); view.focus(); } };
  function close() {
    if (!open || open.el !== box) return;
    document.removeEventListener("mousedown", outside, true);
    document.removeEventListener("keydown", keys, true);
    box.remove();
    open = null;
  }
  x.addEventListener("click", () => { close(); view.focus(); });
  document.addEventListener("mousedown", outside, true);
  document.addEventListener("keydown", keys, true);
  open = { el: box, close };
  const first = box.querySelector("textarea");
  if (first) { first.focus(); first.setSelectionRange(first.value.length, first.value.length); }
}

// One pin per line with comments, in the line's right margin (app.css `.pp-cmt-pin`).
export class CommentPin extends WidgetType {
  constructor(bodies) {
    super();
    this.bodies = bodies; // the comments' texts (the tooltip)
  }
  eq(other) {
    return other.bodies.join("\u0000") === this.bodies.join("\u0000");
  }
  // a zero-width inline anchor (where the caret at the line's end is measured) holding the pin,
  // which is placed against the line (the line is the positioned box, app.css)
  toDOM(view) {
    const anchor = el("span", "pp-cmt-anchor");
    const pin = el("span", "pp-cmt-pin");
    anchor.append(pin);
    pin.setAttribute("role", "button");
    pin.title = this.bodies.join("\n");
    pin.append(icon("message-square"));
    if (this.bodies.length > 1) pin.append(el("span", "pp-cmt-count", String(this.bodies.length)));
    pin.addEventListener("mousedown", (e) => { e.preventDefault(); e.stopPropagation(); });
    pin.addEventListener("click", (e) => { e.preventDefault(); e.stopPropagation(); openPopup(view, pin); });
    return anchor;
  }
  ignoreEvent() {
    return true;
  }
}
