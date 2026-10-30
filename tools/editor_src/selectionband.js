// The selection, drawn as a layer of square rectangles kept inside the note's line box — the same
// left and right edges as the AI's target band and the diff's rows (aiband.js) — instead of
// CodeMirror's own selection layer, whose rectangles reach past the text into the margins
// (hidden in app.css). While the Ask box holds the selection's text in its band (the editor is not
// focused), the band alone shows it: one highlight at a time.
import { RectangleMarker, layer } from "@codemirror/view";
import { lineBox } from "./aiband.js";
import { askBandShown } from "./selectpopup.js";

export const selectionBand = layer({
  above: false,
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
    return out;
  },
  update: (u) => u.selectionSet || u.docChanged || u.viewportChanged || u.geometryChanged || u.focusChanged || u.transactions.some((tr) => tr.effects.length),
});
