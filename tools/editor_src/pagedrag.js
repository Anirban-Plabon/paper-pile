// Dragging page breaks (PLAN §4.17): hold the left mouse button on a page break line, or on a
// "Page N" line of page view, and drop it on another line; the page then starts at that line.
//
// The editor only draws the drag (a line where the page would start) and reports the drop
// (event `page_break_move`: the break's line, or 0 for a page line no break made, and the target
// line); Python works out the new text (core/page_move.py). A page line no break made can only
// go up: lower down, the text no longer fits on the page and the layout breaks earlier anyway.
// A press that does not move is a click: the caret goes to the break (which shows it raw).
import { ViewPlugin } from "@codemirror/view";
import { rtOf } from "./context.js";
import { LINE } from "./pagebreak.js";

const DRAG_PX = 4;
const blank = (text) => /^[ \t]*$/.test(text);

// The break line that starts the page at line `number`, or 0: the first non-empty line above.
function breakAbove(doc, number) {
  let n = number - 1;
  while (n >= 1 && blank(doc.line(n).text)) n--;
  return n >= 1 && LINE.test(doc.line(n).text) ? n : 0;
}

// The line a page dropped at `y` starts at: the line under the pointer, or the next one when the
// pointer is in its lower half.
function targetLine(view, y) {
  const content = view.contentDOM.getBoundingClientRect();
  const pos = view.posAtCoords({ x: content.left + 2, y }, false);
  const line = view.state.doc.lineAt(pos);
  const block = view.lineBlockAt(line.from);
  const mid = view.documentTop + block.top + block.height / 2;
  return y > mid && line.number < view.state.doc.lines ? line.number + 1 : line.number;
}

function lineTop(view, number) {
  const block = view.lineBlockAt(view.state.doc.line(number).from);
  return view.documentTop + block.top;
}

export const pageDrag = ViewPlugin.fromClass(
  class {
    constructor(view) {
      this.view = view;
      this.drag = null;
      this.down = (e) => this.start(e);
      view.contentDOM.addEventListener("mousedown", this.down, true);
    }
    start(e) {
      if (e.button !== 0 || e.ctrlKey || e.shiftKey || e.altKey || e.metaKey) return;
      const el = e.target.closest && e.target.closest(".pp-page-line, .pp-page-break-line");
      if (!el || !this.view.contentDOM.contains(el)) return;
      const { view } = this;
      const pos = view.posAtDOM(el);
      const doc = view.state.doc;
      let line, from, label;
      if (el.classList.contains("pp-page-line")) {
        from = doc.lineAt(pos).number; // the page's first line
        line = breakAbove(doc, from);
        label = el.getAttribute("aria-label") || "Page";
      } else {
        line = doc.lineAt(pos).number;
        from = line;
        label = "Page break";
      }
      e.preventDefault();
      e.stopPropagation();
      this.drag = { el, line, from, label, x: e.clientX, y: e.clientY, moved: false, target: null, mark: null };
      this.move = (ev) => this.moved(ev);
      this.up = (ev) => this.drop(ev);
      document.addEventListener("mousemove", this.move, true);
      document.addEventListener("mouseup", this.up, true);
    }
    moved(e) {
      const d = this.drag;
      if (!d) return;
      if (!d.moved && Math.abs(e.clientY - d.y) < DRAG_PX && Math.abs(e.clientX - d.x) < DRAG_PX) return;
      e.preventDefault();
      if (!d.moved) {
        d.moved = true;
        document.body.classList.add("pp-page-dragging");
        d.el.classList.add("pp-page-drag-source");
        d.mark = document.createElement("div");
        d.mark.className = "pp-page-drag-mark";
        const tag = document.createElement("span");
        tag.textContent = d.label;
        d.mark.appendChild(tag);
        document.body.appendChild(d.mark);
      }
      let target = targetLine(this.view, e.clientY);
      if (!d.line && target >= d.from) target = null; // a layout page line only moves up
      d.target = target;
      const content = this.view.contentDOM.getBoundingClientRect();
      d.mark.style.display = target === null ? "none" : "";
      if (target !== null) {
        d.mark.style.left = `${content.left}px`;
        d.mark.style.width = `${content.width}px`;
        d.mark.style.top = `${lineTop(this.view, target)}px`;
      }
    }
    drop(e) {
      const d = this.drag;
      this.end();
      if (!d) return;
      const { view } = this;
      if (!d.moved) {
        // a click: the caret to the break (or the page's first line)
        const at = view.state.doc.line(d.line || d.from).from;
        view.focus();
        view.dispatch({ selection: { anchor: at }, scrollIntoView: true });
        return;
      }
      e.preventDefault();
      if (d.target === null || (d.line && d.target === d.line)) return;
      const rt = rtOf(view.state);
      rt.emit("page_break_move", { docId: rt.getDocId(), line: d.line, target: d.target });
    }
    end() {
      const d = this.drag;
      this.drag = null;
      document.removeEventListener("mousemove", this.move, true);
      document.removeEventListener("mouseup", this.up, true);
      document.body.classList.remove("pp-page-dragging");
      if (d) {
        d.el.classList.remove("pp-page-drag-source");
        d.mark?.remove();
      }
    }
    destroy() {
      this.end();
      this.view.contentDOM.removeEventListener("mousedown", this.down, true);
    }
  },
);
