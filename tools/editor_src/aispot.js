// The AI chip's spot in the note (user 2026-11-10): while an AI job started from the Ask box
// writes into the note, an empty block under the text being written keeps room for the chip
// ("Writing…" with Stop), which static/askpop.js lays over it — so the chip goes down with the
// text and never covers it. Live proposals (proposal.js) and streams with a chip (stream.js)
// place it.
import { EditorView, WidgetType } from "@codemirror/view";

class Spot extends WidgetType {
  eq() {
    return true;
  }
  toDOM() {
    const el = document.createElement("div");
    el.className = "pp-aichip-spot";
    el.setAttribute("aria-hidden", "true");
    return el;
  }
  get estimatedHeight() {
    return 56;
  }
  ignoreEvent() {
    return false;
  }
}

export const spotWidget = new Spot();

// While the AI writes, the text being written and the chip under it stay on screen
// (user 2026-11-10: text going out of sight while it streams): when the spot is below the
// note's visible part, the note scrolls up by what is missing. `pos` (a doc position) is
// scrolled into view instead when the spot is not drawn (far outside the viewport).
const ROOM = 8;
export function keepSpotInView(view, pos = null) {
  view.requestMeasure({
    key: "pp-aispot-keep",
    read(v) {
      const spot = v.dom.querySelector(".pp-aichip-spot");
      if (!spot) return { missing: true };
      const box = v.scrollDOM.getBoundingClientRect();
      const r = spot.getBoundingClientRect();
      return { below: r.bottom + ROOM - box.bottom };
    },
    write(m, v) {
      if (m.missing) {
        if (pos !== null) v.dispatch({ effects: EditorView.scrollIntoView(Math.min(pos, v.state.doc.length), { y: "end", yMargin: 80 }) });
      } else if (m.below > 0) {
        v.scrollDOM.scrollTop += m.below;
      }
    },
  });
}
