// Dragging page breaks (PLAN §4.17): hold the left mouse button on a "Page N" line of page view
// (or, outside page view, on a page break line) and drop it on another line; the page then
// starts at that line.
//
// How far it can go: a page starts at least one line below the start of the page before it, and
// no lower than where that page would end by itself (it is full there). For a page a break of
// the user's starts, that place is found with a trial layout of the note without the break
// (asked when the drag starts; until it is known the next page's start is the limit). A page the
// layout started (no break above it) is already as low as it can be, so it only goes up. Outside
// page view nothing is laid out: a break stays between its neighbouring breaks.
//
// The editor only draws the drag (a line where the page would start, "furthest" / "earliest" at a
// limit; the note scrolls while the pointer is near its top or bottom edge) and reports the drop (event `page_break_move`: the break's line, or 0 for a page line no
// break made, and the target line); Python works out the new text (core/page_move.py). After the
// drop the note is laid out again; if the rest now needs more (or fewer) pages, the editor says so
// (event `page_count`). A press that does not move is a click: the caret goes to that line.
import { ViewPlugin } from "@codemirror/view";
import { rtOf } from "./context.js";
import { LINE } from "./pagebreak.js";
import { frontMatterEnd, pageStartLines, probeLayout, watchPageCount } from "./pageview.js";

const DRAG_PX = 4;
const EDGE_PX = 36; // near the editor's top / bottom edge the note scrolls (faster nearer)
const blank = (text) => /^[ \t]*$/.test(text);

// The break line that starts the page at line `number`, or 0: the first non-empty line above.
function breakAbove(doc, number) {
  let n = number - 1;
  while (n >= 1 && blank(doc.line(n).text)) n--;
  return n >= 1 && LINE.test(doc.line(n).text) ? n : 0;
}

// The note's text without the break on line `number` (and the empty line it needed), as
// core/page_move.py removes it; `removed` lines are gone from there on.
function withoutBreak(doc, number) {
  const lines = doc.toString().split("\n");
  let idx = number - 1;
  let removed = 1;
  lines.splice(idx, 1);
  if (idx < lines.length && blank(lines[idx]) && (idx === 0 || blank(lines[idx - 1]))) {
    lines.splice(idx, 1);
    removed++;
  }
  return { text: lines.join("\n"), removed };
}

// The first line on paper (the hidden properties are not).
function firstLine(state) {
  const end = frontMatterEnd(state);
  return end < 0 ? 1 : state.doc.lineAt(end).number + 1;
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

// Where a dragged page may start: `{ min, max }` (lines), and a trial layout that sets `max`.
function bounds(view, drag) {
  const { state } = view;
  const doc = state.doc;
  if (!drag.page) {
    // outside page view: between the neighbouring breaks
    let min = 1;
    let max = doc.lines;
    for (let n = drag.line - 1; n >= 1; n--) if (LINE.test(doc.line(n).text)) { min = n + 1; break; }
    for (let n = drag.line + 1; n <= doc.lines; n++) if (LINE.test(doc.line(n).text)) { max = n - 1; break; }
    return { min, max };
  }
  const starts = pageStartLines(state).map((s) => s.line);
  const k = starts.indexOf(drag.from);
  const prev = k > 0 ? starts[k - 1] : firstLine(state);
  const next = k >= 0 && k + 1 < starts.length ? starts[k + 1] : doc.lines;
  const out = { min: Math.min(prev + 1, drag.from), max: drag.line ? next : drag.from };
  if (drag.line) {
    // how far this page could reach without the break: lay the note out without it
    const { text, removed } = withoutBreak(doc, drag.line);
    out.probe = probeLayout(view, text).then((pages) => {
      if (!pages) return;
      const natural = pages.map((p) => (p.line >= drag.line ? p.line + removed : p.line)).filter((l) => l > prev).sort((a, b) => a - b)[0];
      out.max = Math.max(out.min, natural ?? doc.lines);
    });
  }
  return out;
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
      const page = el.classList.contains("pp-page-line");
      const from = doc.lineAt(pos).number; // the page's first line (or the break's line)
      const line = page ? breakAbove(doc, from) : from;
      e.preventDefault();
      e.stopPropagation();
      this.drag = { el, page, line, from, label: page ? el.getAttribute("aria-label") || "Page" : "Page break", x: e.clientX, y: e.clientY, moved: false, target: null, mark: null, limits: null };
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
        d.limits = bounds(this.view, d);
        d.limits.probe?.then(() => this.drag === d && d.lastY !== undefined && this.place(d.lastY));
        document.body.classList.add("pp-page-dragging");
        d.el.classList.add("pp-page-drag-source");
        d.mark = document.createElement("div");
        d.mark.className = "pp-page-drag-mark";
        d.tag = document.createElement("span");
        d.mark.appendChild(d.tag);
        document.body.appendChild(d.mark);
        this.autoScroll(d);
      }
      this.place(e.clientY);
    }
    // While dragging near the top or bottom edge, scroll the note and keep the mark under the pointer.
    autoScroll(d) {
      const step = () => {
        if (this.drag !== d) return;
        const box = this.view.scrollDOM.getBoundingClientRect();
        const y = d.lastY;
        const by = y < box.top + EDGE_PX ? -(box.top + EDGE_PX - y) : y > box.bottom - EDGE_PX ? y - (box.bottom - EDGE_PX) : 0;
        if (by) {
          this.view.scrollDOM.scrollTop += Math.max(-40, Math.min(40, by / 2));
          this.place(y);
        }
        d.frame = requestAnimationFrame(step);
      };
      d.frame = requestAnimationFrame(step);
    }
    place(y) {
      const d = this.drag;
      d.lastY = y;
      const want = targetLine(this.view, y);
      const { min, max } = d.limits;
      const target = Math.max(min, Math.min(max, want));
      d.target = target;
      const content = this.view.contentDOM.getBoundingClientRect();
      d.mark.style.left = `${content.left}px`;
      d.mark.style.width = `${content.width}px`;
      d.mark.style.top = `${lineTop(this.view, target)}px`;
      const edge = want > max ? " · furthest" : want < min ? " · earliest" : "";
      d.tag.textContent = d.label + edge;
      d.mark.classList.toggle("pp-page-drag-limit", edge !== "");
    }
    drop(e) {
      const d = this.drag;
      this.end();
      if (!d) return;
      const { view } = this;
      if (!d.moved) {
        // a click: the caret to the page's first line (the break itself is hidden in page view)
        const at = view.state.doc.line(d.from).from;
        view.focus();
        view.dispatch({ selection: { anchor: at }, scrollIntoView: true });
        return;
      }
      e.preventDefault();
      const unchanged = d.line ? d.target === d.line || d.target === d.from : d.target >= d.from;
      if (d.target === null || unchanged) return;
      if (d.page) watchPageCount(view);
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
        cancelAnimationFrame(d.frame);
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
