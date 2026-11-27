// The selection, drawn as a layer of square rectangles kept inside the note's line box — the same
// left and right edges as the AI's target band and the diff's rows (aiband.js) — instead of
// CodeMirror's own selection layer, whose rectangles reach past the text into the margins
// (hidden in app.css). While the Ask box holds the selection's text in its band (the editor is not
// focused), the band alone shows it: one highlight at a time. It is drawn OVER the text,
// see-through (as the AI band): under it, real pages' sheet (the content's own background) and
// rendered blocks with a background would hide it while the mouse is still selecting.
// CodeMirror's rectangles skip rendered blocks (a table, code, math, an image: one replaced block
// to the editor), so a selection across one showed a gap there and nothing said the block was in
// it: each rendered block the selection overlaps is covered whole, edge to edge like a line.
import { BlockType, RectangleMarker, layer } from "@codemirror/view";
import { lineBox } from "./aiband.js";
import { askBandShown } from "./selectpopup.js";

export const selectionBand = layer({
  above: true,
  class: "pp-sel-layer",
  markers(view) {
    if (askBandShown(view)) return [];
    const box = lineBox(view);
    const right = box.left + box.width;
    const out = [];
    for (const range of view.state.selection.ranges) {
      if (range.empty) continue;
      for (const m of RectangleMarker.forRange(view, "pp-sel", range)) {
        const left = Math.max(m.left, box.left);
        const end = Math.min(m.left + m.width, right);
        if (end > left) out.push(new RectangleMarker("pp-sel", left, m.top, end - left, m.height));
      }
    }
    return withBlocks(out, renderedBlocks(view, box));
  },
  update: (u) => u.selectionSet || u.docChanged || u.viewportChanged || u.geometryChanged || u.focusChanged || u.transactions.some((tr) => tr.effects.length),
});

// The rendered blocks (replaced block widgets) in view that a non-empty selection range overlaps.
function renderedBlocks(view, box) {
  const ranges = view.state.selection.ranges.filter((r) => !r.empty);
  if (!ranges.length) return [];
  const scroller = view.scrollDOM.getBoundingClientRect();
  const base = view.documentTop - scroller.top + view.scrollDOM.scrollTop;
  const out = [];
  for (const line of view.viewportLineBlocks) {
    for (const b of Array.isArray(line.type) ? line.type : [line]) {
      if (b.type !== BlockType.WidgetRange || b.height <= 0 || b.to <= b.from) continue;
      if (!ranges.some((r) => r.from < b.to && r.to > b.from)) continue;
      out.push(new RectangleMarker("pp-sel pp-sel-block", box.left, base + b.top, box.width, b.height));
    }
  }
  return out;
}

// `rects` with the blocks added: whatever part of a rectangle lies beside a block is cut away (the
// two would overlap and tint it twice).
function withBlocks(rects, blocks) {
  for (const b of blocks) {
    const top = b.top;
    const bottom = b.top + b.height;
    rects = rects.flatMap((m) => {
      if (m.top >= bottom || m.top + m.height <= top) return [m];
      const parts = [];
      if (m.top < top) parts.push(new RectangleMarker("pp-sel", m.left, m.top, m.width, top - m.top));
      if (m.top + m.height > bottom) parts.push(new RectangleMarker("pp-sel", m.left, bottom, m.width, m.top + m.height - bottom));
      return parts;
    });
  }
  return rects.concat(blocks);
}
