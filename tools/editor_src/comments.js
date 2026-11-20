// Comments in the note (PLAN §4.38). A `%%comment%%` is hidden off the caret and its line gets one
// pin in the right margin (`CommentPin`, drawn by livepreview.js); a click on the pin opens a small
// window with that line's comments, each editable (Save / Enter) or deletable. What a change does
// to the text is Python's (`comment_set` -> core/formatting.py `set_comment`); JS only draws.
import { WidgetType } from "@codemirror/view";
import { rtOf } from "./context.js";

const COMMENT = /%%((?:[^\n%]|%(?!%))*)%%/g;
// a comment's pin colour (core/formatting.py COMMENT_COLORS): grey without a mark, else `%%{red} …%%`
export const COMMENT_COLORS = ["", "red", "yellow", "green"];
const COLOR_MARK = /^\{(red|yellow|green)\}\s*/;
const COLOR_NAME = { "": "Grey", red: "Red", yellow: "Yellow", green: "Green" };
let open = null; // {el, close}

// `{red} words` -> {color: "red", body: "words"}
export function splitComment(raw) {
  const t = raw.trim();
  const m = COLOR_MARK.exec(t);
  return m ? { color: m[1], body: t.slice(m[0].length).trim() } : { color: "", body: t };
}
const colorClass = (c) => `pp-cmt-c-${c || "gray"}`;

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
  for (const m of line.text.matchAll(COMMENT)) out.push({ from: line.from + m.index, ...splitComment(m[1]) });
  return out;
}

function openPopup(view, pin) {
  closeCommentPopup();
  const items = lineComments(view, pin);
  if (!items.length) return;
  const rt = rtOf(view.state);
  const box = el("div", "pp-cmt-pop");
  const head = el("div", "pp-cmt-head");
  // the comment icon in its tile, in the (first) comment's pin colour
  const tile = el("span", `pp-cmt-tile ${colorClass(items[0].color)}`);
  tile.append(icon("message-square"));
  head.append(tile, el("span", "pp-cmt-title", items.length > 1 ? `${items.length} comments` : "Comment"));
  const x = el("button", "pp-cmt-x");
  x.append(icon("x"));
  x.title = "Close (Esc)";
  head.append(x);
  box.append(head);
  const send = (i, body, color) => {
    const now = lineComments(view, pin)[i];
    if (now) rt.emit("comment_set", { docId: rt.getDocId(), from: now.from, body, color });
    close();
  };
  items.forEach((item, i) => {
    const row = el("div", "pp-cmt-item");
    const ta = el("textarea", "pp-cmt-text");
    ta.value = item.body;
    ta.rows = 1;
    ta.spellcheck = true;
    let color = item.color; // picked in the dots below, written with Save / Enter
    // as tall as its text (no border), scrolling only past 160 px
    const fit = () => {
      ta.style.height = "auto";
      const h = ta.scrollHeight;
      ta.style.height = `${Math.min(h, 160)}px`;
      ta.style.overflowY = h > 160 ? "auto" : "hidden";
    };
    ta.addEventListener("input", fit);
    ta.addEventListener("keydown", (e) => {
      if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(i, ta.value, color); }
      else if (e.key === "Escape") { e.preventDefault(); close(); view.focus(); }
    });
    const actions = el("div", "pp-cmt-actions");
    const dots = el("div", "pp-cmt-colors");
    for (const c of COMMENT_COLORS) {
      const dot = el("button", `pp-cmt-dot ${colorClass(c)}`);
      dot.title = COLOR_NAME[c];
      dot.setAttribute("aria-pressed", String(c === color));
      dot.addEventListener("mousedown", (e) => e.preventDefault()); // the text keeps the caret
      dot.addEventListener("click", () => {
        color = c;
        for (const d of dots.children) d.setAttribute("aria-pressed", String(d === dot));
        if (i === 0) tile.className = `pp-cmt-tile ${colorClass(c)}`;
      });
      dots.append(dot);
    }
    const del = el("button", "pp-cmt-btn pp-cmt-del", "Delete");
    const save = el("button", "pp-cmt-btn pp-cmt-save", "Save");
    del.addEventListener("click", () => send(i, "", color));
    save.addEventListener("click", () => send(i, ta.value, color));
    actions.append(dots, del, save);
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
    this.bodies = bodies; // the comments' insides as written (`{red} words`)
  }
  eq(other) {
    return other.bodies.join("\u0000") === this.bodies.join("\u0000");
  }
  // a zero-width inline anchor (where the caret at the line's end is measured) holding the pin,
  // which is placed against the line (the line is the positioned box, app.css)
  toDOM(view) {
    const anchor = el("span", "pp-cmt-anchor");
    const parts = this.bodies.map(splitComment);
    // the pin takes the first coloured comment's colour (grey when none has one)
    const pin = el("span", `pp-cmt-pin ${colorClass(parts.find((p) => p.color)?.color)}`);
    anchor.append(pin);
    pin.setAttribute("role", "button");
    pin.title = parts.map((p) => p.body).join("\n");
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
