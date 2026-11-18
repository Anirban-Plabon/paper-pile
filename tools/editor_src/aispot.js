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
// note's visible part, the note scrolls up by what is missing. Without a spot (a job not started
// from the Ask box: its chip sits at the bottom of the window, over the note), `pos` — the end of
// the text being written — is kept above that chip (user 2026-11-18: the text grew under it).
const ROOM = 8;

// The top of an AI chip that sits over the bottom of this note's scroller (none: its bottom).
function chipTop(box) {
  let top = box.bottom;
  for (const chip of document.querySelectorAll(".pp-aiprog")) {
    if (!chip.getClientRects().length || chip.style.visibility === "hidden") continue;
    if (chip.classList.contains("pp-aiprog-follow") && !chip.dataset.ppFree) continue; // on the spot
    const r = chip.getBoundingClientRect();
    if (r.right <= box.left || r.left >= box.right || r.top >= box.bottom || r.bottom <= box.top) continue;
    top = Math.min(top, r.top);
  }
  return top;
}

export function keepSpotInView(view, pos = null) {
  view.requestMeasure({
    key: "pp-aispot-keep",
    read(v) {
      const box = v.scrollDOM.getBoundingClientRect();
      const spot = v.dom.querySelector(".pp-aichip-spot");
      if (spot) return { below: spot.getBoundingClientRect().bottom + ROOM - box.bottom };
      if (pos === null) return { below: 0 };
      const at = Math.min(pos, v.state.doc.length);
      const limit = chipTop(box) - ROOM;
      const coords = v.coordsAtPos(at, -1);
      if (!coords) return { missing: true, at, margin: box.bottom - limit + ROOM };
      return { below: coords.bottom - limit };
    },
    write(m, v) {
      if (m.missing) {
        v.dispatch({ effects: EditorView.scrollIntoView(m.at, { y: "end", yMargin: Math.max(80, m.margin) }) });
      } else if (m.below > 0) {
        v.scrollDOM.scrollTop += m.below;
      }
    },
  });
}
