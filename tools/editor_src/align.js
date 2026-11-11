// Text alignment of the whole note and of single blocks (PLAN §4.34). Markdown has none, so it is
// view state kept by Python (core/alignment.py, .paper-pile/alignment.json); this module only
// draws it and follows blocks while the note is edited.
//
// A block is a top-level node of the markdown tree (paragraph, heading, list, quote, table, code,
// math…). The store knows a block by its key — its kind and first line, `#2`… for repeats — but
// while the note is open a block is followed by position: a mark at its first character, mapped
// through every change, so typing in a heading never loses its alignment. After edits the keys
// are made again and sent to Python (`align_blocks`), so the store follows the text.
import { StateField, StateEffect, Facet, RangeSet, RangeValue } from "@codemirror/state";
import { EditorView, Decoration, ViewPlugin, WidgetType } from "@codemirror/view";
import { syntaxTree, ensureSyntaxTree } from "@codemirror/language";
import { invertedEffects } from "@codemirror/commands";
import { rtOf, editorContext } from "./context.js";

export const ALIGNS = ["left", "center", "right", "justify"];
const SAVE_MS = 700;
const KEY_CHARS = 120;
const SKIP = new Set(["FrontMatter", "LinkReference", "CommentBlock", "ProcessingInstructionBlock"]);

// Every note's alignment when neither the note nor a block has its own (Settings, editor.align).
export const defaultAlign = Facet.define({ combine: (v) => v[0] ?? "left" });

class AlignMark extends RangeValue {
  constructor(align) {
    super();
    this.align = align;
    this.startSide = -1; // text typed at a block's start stays inside the block
  }
  eq(other) {
    return other.align === this.align;
  }
}
const marks = {};
const markOf = (align) => (marks[align] ??= new AlignMark(align));

// The note's top-level blocks as whole-line ranges, in order.
export function topBlocks(state) {
  const { doc } = state;
  const tree = ensureSyntaxTree(state, doc.length, 50) ?? syntaxTree(state);
  const out = [];
  for (let c = tree.topNode.firstChild; c; c = c.nextSibling) {
    if (SKIP.has(c.name)) continue;
    out.push({ name: c.name, from: doc.lineAt(c.from).from, to: doc.lineAt(c.to).to });
  }
  return out;
}

const kindOf = (name) => (name.startsWith("ATXHeading") || name.startsWith("SetextHeading") ? "Heading" : name);

// The store keys of `blocks`: kind + first line (trimmed, cut), `#n` from the second repeat on.
function keysOf(state, blocks) {
  const seen = new Map();
  return blocks.map((b) => {
    const first = state.doc.lineAt(b.from).text.trim().slice(0, KEY_CHARS);
    const base = `${kindOf(b.name)}:${first}`;
    const n = (seen.get(base) ?? 0) + 1;
    seen.set(base, n);
    return n === 1 ? base : `${base}#${n}`;
  });
}

const blockAt = (blocks, pos) => blocks.find((b) => b.from <= pos && pos <= b.to) ?? null;

function fromStore(state, entry) {
  const want = entry?.blocks ?? {};
  const blocks = topBlocks(state);
  const keys = keysOf(state, blocks);
  const ranges = [];
  blocks.forEach((b, i) => {
    const a = want[keys[i]];
    if (ALIGNS.includes(a)) ranges.push(markOf(a).range(b.from));
  });
  return { note: ALIGNS.includes(entry?.note) ? entry.note : null, marks: RangeSet.of(ranges, true) };
}

// Python's store changed: reload this note's alignment (`blocks: false` = only the note's own).
export const loadAlign = StateEffect.define();
// Align the blocks touching `ranges` [{from, to}] (`align` null: back to the note's alignment).
export const setBlockAlign = StateEffect.define({
  map: (v, ch) => ({ ...v, ranges: v.ranges.map((r) => ({ from: ch.mapPos(r.from, -1), to: ch.mapPos(r.to, 1) })) }),
});
// Put back exactly these marks in from..to (what Ctrl+Z / Ctrl+Y use: block alignment is an edit).
const restoreMarks = StateEffect.define({
  map: (v, ch) => ({ from: ch.mapPos(v.from, -1), to: ch.mapPos(v.to, 1), marks: v.marks.map((m) => ({ pos: ch.mapPos(m.pos, -1), align: m.align })) }),
});

export const alignField = StateField.define({
  create: (state) => fromStore(state, editorContext.align?.[rtOf(state).notePath]),
  update(value, tr) {
    let v = tr.docChanged ? { note: value.note, marks: value.marks.map(tr.changes) } : value;
    for (const e of tr.effects) {
      if (e.is(loadAlign)) {
        const entry = editorContext.align?.[rtOf(tr.state).notePath];
        v = e.value.blocks ? fromStore(tr.state, entry) : { note: ALIGNS.includes(entry?.note) ? entry.note : null, marks: v.marks };
      } else if (e.is(setBlockAlign)) {
        v = withBlocks(tr.state, v, e.value.ranges, e.value.align);
      } else if (e.is(restoreMarks)) {
        const { from, to, marks } = e.value;
        let set = v.marks.update({ filterFrom: from, filterTo: to, filter: () => false });
        set = set.update({ add: marks.map((m) => markOf(m.align).range(m.pos)), sort: true });
        v = { note: v.note, marks: set };
      }
    }
    return v;
  },
});

export const noteAlign = (state) => state.field(alignField, false)?.note ?? state.facet(defaultAlign);

function withBlocks(state, v, ranges, align) {
  const touched = topBlocks(state).filter((b) => ranges.some((r) => r.from <= b.to && r.to >= b.from));
  if (!touched.length) return v;
  const base = v.note ?? state.facet(defaultAlign);
  let set = v.marks;
  for (const b of touched) {
    set = set.update({ filterFrom: b.from, filterTo: b.to, filter: () => false });
    if (align && align !== base) set = set.update({ add: [markOf(align).range(b.from)] });
  }
  return { note: v.note, marks: set };
}

// The alignment of every block that has its own: [{from, to, align}], first mark of a block wins.
function alignedBlocks(state, blocks = topBlocks(state)) {
  const v = state.field(alignField, false);
  if (!v || !v.marks.size) return [];
  const out = [];
  const iter = v.marks.iter();
  for (; iter.value; iter.next()) {
    const b = blockAt(blocks, iter.from);
    if (b && !out.some((o) => o.from === b.from)) out.push({ ...b, align: iter.value.align });
  }
  return out;
}

// The alignment of the block at `pos` (its own, else the note's): block widgets ask for theirs.
export function alignAt(state, pos) {
  const v = state.field(alignField, false);
  if (v && v.marks.size) {
    const own = alignedBlocks(state).find((b) => b.from <= pos && pos <= b.to);
    if (own) return own.align;
  }
  return noteAlign(state);
}

const lineDecos = EditorView.decorations.compute(["doc", alignField], (state) => {
  const out = [];
  for (const b of alignedBlocks(state)) {
    const deco = Decoration.line({ class: `pp-al-${b.align}` });
    for (let n = state.doc.lineAt(b.from).number, last = state.doc.lineAt(b.to).number; n <= last; n++) {
      out.push(deco.range(state.doc.line(n).from));
    }
  }
  return Decoration.set(out);
});

// The note's own alignment on the content element; lines and widgets inherit it in app.css.
const noteAttr = EditorView.contentAttributes.compute([alignField, defaultAlign], (state) => ({ "data-pp-align": noteAlign(state) }));

// After edits (or a new block alignment) the keys are made again and sent to Python.
const saver = ViewPlugin.fromClass(
  class {
    constructor(view) {
      this.view = view;
      this.timer = null;
      // the note this state belongs to: Python changes the shared runtime's path before the next
      // note's state replaces this one, so a late save must not read it then
      this.path = rtOf(view.state).notePath;
      this.sent = JSON.stringify(this.keys());
    }
    keys() {
      const { state } = this.view;
      const blocks = topBlocks(state);
      const own = alignedBlocks(state, blocks);
      if (!own.length) return {};
      const keys = keysOf(state, blocks);
      const out = {};
      for (const o of own) out[keys[blocks.findIndex((b) => b.from === o.from)]] = o.align;
      return out;
    }
    update(u) {
      this.path = rtOf(u.state).notePath; // follows a rename
      const before = u.startState.field(alignField, false);
      const after = u.state.field(alignField, false);
      if (before === after && !(u.docChanged && after?.marks.size)) return;
      if (u.transactions.some((tr) => tr.effects.some((e) => e.is(loadAlign)))) {
        this.sent = JSON.stringify(this.keys()); // came from the store: nothing to send back
        return;
      }
      clearTimeout(this.timer);
      this.timer = setTimeout(() => this.flush(), SAVE_MS);
    }
    flush() {
      this.timer = null;
      const blocks = this.keys();
      const json = JSON.stringify(blocks);
      if (json === this.sent) return;
      this.sent = json;
      if (!this.path) return;
      const store = (editorContext.align ??= {});
      store[this.path] = { ...(store[this.path] ?? {}), blocks };
      rtOf(this.view.state).emit("align_blocks", { path: this.path, blocks });
    }
    destroy() {
      if (this.timer) this.flush(); // a note switch or close must not lose the last change
    }
  },
);

// A block widget (table, math, diagram, embed) drawn with its block's alignment on its root.
// Wrapping keeps blocks.js unaware of alignment; everything else is the inner widget's.
export class Aligned extends WidgetType {
  constructor(inner, align) {
    super();
    this.inner = inner;
    this.align = align;
  }
  eq(other) {
    return other.align === this.align && other.inner.constructor === this.inner.constructor && this.inner.eq(other.inner);
  }
  toDOM(view) {
    const dom = this.inner.toDOM(view);
    dom.setAttribute("data-pp-align", this.align);
    dom.ppInner = this.inner.constructor;
    return dom;
  }
  updateDOM(dom, view) {
    if (dom.ppInner !== this.inner.constructor || !this.inner.updateDOM || !this.inner.updateDOM(dom, view)) return false;
    dom.setAttribute("data-pp-align", this.align);
    return true;
  }
  get estimatedHeight() {
    return this.inner.estimatedHeight;
  }
  get lineBreaks() {
    return this.inner.lineBreaks;
  }
  ignoreEvent(e) {
    return this.inner.ignoreEvent(e);
  }
  coordsAt(dom, pos, side) {
    return this.inner.coordsAt(dom, pos, side);
  }
  destroy(dom) {
    this.inner.destroy(dom);
  }
}

// `widget` aligned like the block at `pos` (as is when that is left: no wrapper, no attribute).
export function alignedWidget(state, pos, widget) {
  const a = alignAt(state, pos);
  return a === "left" || !widget ? widget : new Aligned(widget, a);
}

export const isAlignChange = (tr) => tr.effects.some((e) => e.is(loadAlign) || e.is(setBlockAlign) || e.is(restoreMarks));

// The marks in from..to of `state` (to put them back later).
function marksIn(state, from, to) {
  const out = [];
  state.field(alignField, false)?.marks.between(from, to, (pos, _end, value) => {
    out.push({ pos, align: value.align });
  });
  return out;
}

// Block alignment is one undo step (the note's own alignment is not: it is a setting of the note).
// The inverse of a change is the marks its blocks had before; undoing that restores the new ones.
const alignHistory = invertedEffects.of((tr) => {
  const out = [];
  for (const e of tr.effects) {
    if (!e.is(setBlockAlign) && !e.is(restoreMarks)) continue;
    const ranges = e.is(setBlockAlign) ? e.value.ranges : [e.value];
    const touched = topBlocks(tr.startState).filter((b) => ranges.some((r) => r.from <= b.to && r.to >= b.from));
    if (!touched.length) continue;
    const from = Math.min(...touched.map((b) => b.from));
    const to = Math.max(...touched.map((b) => b.to));
    out.push(restoreMarks.of({ from, to, marks: marksIn(tr.startState, from, to) }));
  }
  return out;
});

export const alignment = [alignField, alignHistory, lineDecos, noteAttr, saver];
