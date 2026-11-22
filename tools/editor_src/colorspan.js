// Coloured text (PLAN §4.38; user 2026-11-22). In the file a colour is
// `<span style="color:red">words</span>` (other apps show it coloured); in the editor only the
// coloured words are ever seen:
//  * the two tags are hidden always (livepreview.js) and atomic here: the caret never stops
//    inside a hidden tag, and Backspace / Delete next to one deletes the character beyond it
//    instead of the tag (a lone tag would show as raw text);
//  * the colour carries on: typing right after the coloured words goes inside the span (as in a
//    word processor) — except right after `=r … r=` turned into a span, or after → stepped out
//    of it, where the words go after it;
//  * typing `=r words r=` (also `=R`, `=red`, `=Red`, `=RED`, for the 8 colours; any spelling of
//    the same colour closes it) turns into the span at once (`colorShortcut`).
// Which colours exist and how a span is written: core/formatting.py (COLORS, `_open`).

import { syntaxTree } from "@codemirror/language";
import { EditorSelection, Prec, StateEffect, StateField } from "@codemirror/state";
import { Decoration, EditorView, ViewPlugin, keymap } from "@codemirror/view";
import { pairFormatTags } from "./format.js";

// one letter or the whole name, any case (Python: core/formatting.py COLORS)
const NAMES = ["gray", "red", "orange", "yellow", "green", "blue", "purple", "pink"];
const LETTER = { a: "gray", r: "red", o: "orange", y: "yellow", g: "green", b: "blue", p: "purple", k: "pink" };
export const colorOf = (word) => {
  const w = word.toLowerCase();
  if (w === "grey") return "gray";
  return LETTER[w] ?? (NAMES.includes(w) ? w : null);
};
export const spanOpen = (name) => `<span style="color:${name}">`;
export const SPAN_CLOSE = "</span>";

// ---- hidden tags: atomic, and the closing tags' places ------------------------------------------

const atom = Decoration.mark({});

const spanTags = ViewPlugin.fromClass(
  class {
    constructor(view) {
      this.read(view);
    }
    update(u) {
      if (u.docChanged || u.viewportChanged || syntaxTree(u.startState) !== syntaxTree(u.state)) this.read(u.view);
    }
    read(view) {
      const ranges = [];
      this.closes = []; // {from, to} of each colour span's closing tag
      for (const { from, to } of view.visibleRanges) {
        for (const p of pairFormatTags(view.state, from, to)) {
          if (p.kind !== "span") continue;
          ranges.push(atom.range(p.open.from, p.open.to), atom.range(p.close.from, p.close.to));
          if (p.close.from > p.open.to) this.closes.push(p.close);
        }
      }
      this.atoms = Decoration.set(ranges, true);
    }
  },
);

const closeAt = (view, pos, side) => {
  const plugin = view.plugin(spanTags);
  return plugin ? plugin.closes.find((c) => (side === "end" ? c.to : c.from) === pos) : undefined;
};
const tagEndingAt = (view, pos) => {
  const plugin = view.plugin(spanTags);
  let found = null;
  plugin?.atoms.between(pos - 1, pos, (from, to) => { if (to === pos) found = { from, to }; });
  return found;
};
const tagStartingAt = (view, pos) => {
  const plugin = view.plugin(spanTags);
  let found = null;
  plugin?.atoms.between(pos, pos + 1, (from, to) => { if (from === pos) found = { from, to }; });
  return found;
};

// `outside`: the place right after a closing tag where typing stays outside the colour (set by the
// shortcut and by → stepping out; gone as soon as the caret moves elsewhere)
const setOutside = StateEffect.define();
const outsideField = StateField.define({
  create: () => null,
  update(value, tr) {
    for (const e of tr.effects) if (e.is(setOutside)) return e.value;
    if (value === null) return null;
    if (tr.docChanged) value = tr.changes.mapPos(value, 1);
    const sel = tr.state.selection.main;
    return sel.empty && sel.head === value ? value : null;
  },
});

// typing right after a span's closing tag goes inside it (the colour carries on)
const carryOn = EditorView.inputHandler.of((view, from, to, text) => {
  if (from !== to || view.state.selection.ranges.length !== 1) return false;
  if (view.state.field(outsideField, false) === from) return false;
  const close = closeAt(view, from, "end");
  if (!close) return false;
  view.dispatch({
    changes: { from: close.from, insert: text },
    selection: { anchor: close.from + text.length },
    userEvent: "input.type",
  });
  return true;
});

// → at the end of the coloured words steps out (the next words are not coloured)
function stepOut(view) {
  const sel = view.state.selection.main;
  if (!sel.empty) return false;
  const close = closeAt(view, sel.head, "start");
  if (!close) return false;
  view.dispatch({ selection: { anchor: close.to }, effects: setOutside.of(close.to), scrollIntoView: true, userEvent: "select" });
  return true;
}

// Backspace / Delete next to hidden tags: the character beyond them (never half of a pair); an
// empty pair (`<span …></span>`) goes as a whole
const EMPTY_PAIR = /^<span style="color:[^"]*"><\/span>$/;
const deleteBeyond = (forward) => (view) => {
  const sel = view.state.selection.main;
  if (!sel.empty || view.state.selection.ranges.length !== 1) return false;
  let pos = sel.head;
  let tag = forward ? tagStartingAt(view, pos) : tagEndingAt(view, pos);
  if (!tag) return false;
  while (tag) {
    pos = forward ? tag.to : tag.from;
    tag = forward ? tagStartingAt(view, pos) : tagEndingAt(view, pos);
  }
  const doc = view.state.doc;
  const [a, b] = forward ? [sel.head, pos] : [pos, sel.head];
  if (EMPTY_PAIR.test(doc.sliceString(a, b))) { // the colour's last letter is gone: drop its tags
    view.dispatch({ changes: { from: a, to: b }, userEvent: forward ? "delete.forward" : "delete.backward" });
    return true;
  }
  if (forward ? pos >= doc.length : pos <= 0) return true;
  const line = doc.lineAt(pos);
  if (forward ? pos === line.to : pos === line.from) return false; // joining lines: the default
  const range = forward ? { from: pos, to: pos + 1 } : { from: pos - 1, to: pos };
  view.dispatch({
    changes: range,
    selection: EditorSelection.cursor(forward ? sel.head : sel.head - 1),
    userEvent: forward ? "delete.forward" : "delete.backward",
  });
  return true;
};

// the live-preview part (hidden tags only exist there)
export const colorSpans = [
  spanTags,
  outsideField,
  carryOn,
  EditorView.atomicRanges.of((view) => view.plugin(spanTags)?.atoms ?? Decoration.none),
  Prec.high(keymap.of([
    { key: "ArrowRight", run: stepOut },
    { key: "Backspace", run: deleteBeyond(false) },
    { key: "Delete", run: deleteBeyond(true) },
  ])),
];

// ---- `=r words r=` ------------------------------------------------------------------------------

// before the `=` being typed: `=<colour> words <colour>` (not after another `=`: `==` is a highlight).
// The closing colour follows a space or punctuation (`words b=`, `words:b=`, `words.red=`), never a
// letter or digit (`=b herb=` is not closed by the `b` of "herb").
const SHORTCUT = /(^|[^=\\])=([A-Za-z]+) (\S(?:[^\n]*?\S)?)(?: |(?<=[^\sA-Za-z0-9]))([A-Za-z]+)$/;
const NO_SHORTCUT = new Set(["InlineCode", "FencedCode", "CodeBlock", "CodeText", "InlineMath", "BlockMath", "URL", "Link", "HTMLTag", "FormatTag", "Comment"]);

export const colorShortcut = EditorView.inputHandler.of((view, from, to, text) => {
  if (text !== "=" || from !== to || view.state.selection.ranges.length !== 1) return false;
  const line = view.state.doc.lineAt(from);
  const m = SHORTCUT.exec(line.text.slice(0, from - line.from));
  if (!m) return false;
  const color = colorOf(m[2]);
  if (!color || colorOf(m[4]) !== color) return false;
  const start = line.from + m.index + m[1].length;
  for (let n = syntaxTree(view.state).resolveInner(start, 1); n; n = n.parent) if (NO_SHORTCUT.has(n.name)) return false;
  const insert = spanOpen(color) + m[3] + SPAN_CLOSE;
  view.dispatch({
    changes: { from: start, to: from, insert },
    selection: { anchor: start + insert.length },
    effects: setOutside.of(start + insert.length),
    userEvent: "input.type",
  });
  return true;
});
export const colorShortcutExt = [outsideField, colorShortcut];
