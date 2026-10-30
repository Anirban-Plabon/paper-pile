// Full-width see-through bands over the text (PLAN §4.29): the text an AI command is about (the Ask box's
// target, pulsing while the AI works) and the lines a diff would remove. Drawn as a layer, like
// CodeMirror's own selection, never as marks in the text: they cover whole lines edge to edge —
// the same box as the diff's green rows — and whole rendered blocks (code, images, callouts,
// tables, math), they move with scrolling without touching the text's DOM, and corners are square.
import { syntaxTree } from "@codemirror/language";
import { BlockType, RectangleMarker, layer } from "@codemirror/view";

// Blocks a band covers whole when it covers any of their lines (they are drawn as one block).
const WHOLE = new Set(["FencedCode", "BlockMath", "Table", "Blockquote", "HTMLBlock"]);

// The top-level block at `pos` when it is one of WHOLE, else null.
function wholeBlock(state, pos, side) {
  let node = syntaxTree(state).resolveInner(pos, side);
  while (node.parent && node.parent.parent) node = node.parent;
  return node.parent && WHOLE.has(node.name) ? node : null;
}

// `from`..`to` grown to the whole blocks it touches at either end.
export function snapToBlocks(state, from, to) {
  const a = wholeBlock(state, from, 1);
  const b = wholeBlock(state, Math.max(from, to - 1), -1);
  return { from: a ? Math.min(from, a.from) : from, to: b ? Math.max(to, b.to) : to };
}

// The note's line box (left edge and width), in the layer's coordinates.
export function lineBox(view) {
  const line = view.contentDOM.querySelector(".cm-line");
  const scroller = view.scrollDOM.getBoundingClientRect();
  const r = (line || view.contentDOM).getBoundingClientRect();
  return { left: r.left - scroller.left + view.scrollDOM.scrollLeft, width: r.width };
}

// The text part of the line at `pos`: `lineBlockAt` also holds the block widgets on that line
// (a diff's added rows, its buttons), which a band must not cover.
function textBlockAt(view, pos) {
  const block = view.lineBlockAt(pos);
  if (!Array.isArray(block.type)) return block;
  const parts = block.type.filter((p) => p.type === BlockType.Text);
  return parts.find((p) => p.from <= pos && pos <= p.to) || parts[0] || block;
}

// One rectangle per run of whole lines `from`..`to` (a rendered block counts as its lines).
export function bandsFor(view, ranges, className) {
  if (!ranges.length) return [];
  const { left, width } = lineBox(view);
  const scroller = view.scrollDOM.getBoundingClientRect();
  const base = view.documentTop - scroller.top + view.scrollDOM.scrollTop;
  const len = view.state.doc.length;
  const out = [];
  for (const { from, to, cls } of ranges) {
    const a = Math.min(from, len);
    const b = Math.min(Math.max(a, to > a ? to - 1 : a), len);
    const top = textBlockAt(view, a).top;
    const bottom = textBlockAt(view, b).bottom;
    if (bottom > top) out.push(new RectangleMarker(cls ? `${className} ${cls}` : className, left, base + top, width, bottom - top));
  }
  return out;
}

// A band layer: `ranges(state, view)` gives the {from, to, cls?} to cover, `className` the look;
// `changed(update)` says when they may differ (besides edits and layout).
export function bandLayer(className, ranges, changed) {
  return layer({
    above: true, // over the text, see-through: rendered blocks with a background would hide it
    class: `${className}-layer`,
    markers: (view) => bandsFor(view, ranges(view.state, view), className),
    update: (u) => u.docChanged || u.viewportChanged || u.geometryChanged || u.focusChanged || changed(u),
  });
}
