// The note's buttons (split · AI · ⋯, built by Python in one box, `.pp-note-tools`) sit at the
// top right of the note, beside the properties block, and scroll away with it. Render-only:
//   * room: the properties block keeps space on its right (CSS on `.pp-fm-wrap`); the first
//     lines get that space too (`pp-tools-room`, a line class: padding, no margin) for when there
//     is no block on screen (no properties, page view hides them, Source mode or a click shows
//     them as text);
//   * anchor: each editor reports where the box goes (`pp-tools-anchor` event: the top of the
//     properties block or of the first shown line, and the right edge of the text column); the
//     page's static/panes.js places the box for the active side.
import { Decoration, EditorView, ViewPlugin } from "@codemirror/view";
import { firstShown, frontMatterEnd, pageViewFacet } from "./pageview.js";

const ROOM = Decoration.line({ class: "pp-tools-room" });
// the first of them: on a narrow side the room is above it instead (CSS container query)
const ROOM_FIRST = Decoration.line({ class: "pp-tools-room pp-tools-first" });
const SOURCE_LINES = 2; // Source mode: the box is about two lines tall

// live: the properties block is drawn (unless page view hides it)
function roomLines(state, live) {
  const hasProps = frontMatterEnd(state) >= 0;
  const paged = !!state.facet(pageViewFacet);
  // Live with properties: the drawn block keeps the room itself (`.pp-fm-wrap`); its first lines
  // get it too for while the block is opened as text (a line class under the block is not drawn)
  const doc = state.doc;
  const first = doc.lineAt(Math.min(paged ? firstShown(state) : 0, doc.length)).number;
  const count = live && !(hasProps && !paged) ? 1 : SOURCE_LINES;
  const out = [];
  for (let n = first; n < first + count && n <= doc.lines; n++) out.push((n === first ? ROOM_FIRST : ROOM).range(doc.line(n).from));
  return out;
}

const room = (live) => EditorView.decorations.compute(["doc", pageViewFacet], (state) => Decoration.set(roomLines(state, live)));

// Where the box goes, in viewport pixels: `{ top, right }`.
const anchor = ViewPlugin.fromClass(
  class {
    constructor(view) {
      this.view = view;
      this.post = () => this.measure();
      view.scrollDOM.addEventListener("scroll", this.post, { passive: true });
      view.contentDOM.addEventListener("focus", this.post);
      this.measure();
    }
    update(u) {
      if (u.docChanged || u.viewportChanged || u.geometryChanged || u.focusChanged) this.measure();
    }
    measure() {
      this.view.requestMeasure({
        key: this,
        read: (view) => {
          const state = view.state;
          const props = view.contentDOM.querySelector(".pp-fm-wrap");
          const pos = state.facet(pageViewFacet) ? firstShown(state) : 0;
          const top =
            props && !state.facet(pageViewFacet)
              ? props.getBoundingClientRect().top + 4 // the block's own top (inside its outer padding)
              : view.documentTop + view.lineBlockAt(Math.min(pos, state.doc.length)).top;
          const box = view.contentDOM.getBoundingClientRect();
          const pad = parseFloat(getComputedStyle(view.contentDOM).paddingRight) || 0;
          return { top, right: box.right - pad };
        },
        write: (where, view) => view.dom.dispatchEvent(new CustomEvent("pp-tools-anchor", { bubbles: true, detail: where })),
      });
    }
    destroy() {
      this.view.scrollDOM.removeEventListener("scroll", this.post);
      this.view.contentDOM.removeEventListener("focus", this.post);
    }
  },
);

export const noteToolsLive = [room(true), anchor];
export const noteToolsSource = [room(false), anchor];
