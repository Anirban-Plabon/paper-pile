// Page view (PLAN §4.17): the editor shows where the pages of the note's PDF begin. A mode the
// user turns on and off (Settings / the ⋯ menu); Python passes it in the editor options.
//
// The pages are not worked out here: a moment after typing stops the editor asks Python for the
// note's print page (event `print_layout`), loads it in a hidden frame, and the page lays itself
// out on sheets (print.js / paginate.js), exactly as the PDF will be. The frame reports the
// source line each page starts on. Typing that happens while a layout is under way is mapped
// through, so the pages land on the right text. Two styles show them:
//   * Page lines: a dashed "Page N" line above each page's first line;
//   * Real pages: the note on sheets of paper. The text column is a sheet (the paper's margins as
//     padding) on a grey desk; a widget at each page start draws the bottom margin of the sheet
//     before (with its page number), the desk between two sheets and the top margin of the next.
//     Each sheet is padded to the paper's height: the editor measures how tall each page's text is
//     on screen (CodeMirror's own line heights) and gives the widget below it the rest.
//
// The properties block (front matter) is not printed, so in page view it is hidden (blocks.js)
// and the caret and typing are kept out of it.
import { syntaxTree } from "@codemirror/language";
import { ChangeSet, EditorSelection, EditorState, Facet, StateEffect, StateField } from "@codemirror/state";
import { Decoration, EditorView, ViewPlugin, WidgetType } from "@codemirror/view";
import { rtOf } from "./context.js";

const LAYOUT_DELAY_MS = 500;
const LAYOUT_TIMEOUT_MS = 30000;
let seqCounter = 0; // across editors and states: an answer is only ever taken by its own request

// `{ style: "lines" | "pages", paper, textWidthMm, paperHeightMm, marginMm }` while page view is on,
// else null.
export const pageViewFacet = Facet.define({ combine: (v) => v[0] ?? null });

// Where the hidden properties block ends (the end of its closing `---` line), or -1 when there is
// nothing to hide: no front matter, or nothing after it (the caret must be able to go somewhere).
export function frontMatterEnd(state) {
  const node = syntaxTree(state).topNode.firstChild;
  if (!node || node.name !== "FrontMatter" || node.to >= state.doc.length) return -1;
  return node.to;
}

const setPages = StateEffect.define();

// Page starts as positions in the doc: `[{ pos, page }]` (page 2 onwards).
const pagesField = StateField.define({
  create: () => [],
  update(starts, tr) {
    for (const e of tr.effects) if (e.is(setPages)) return e.value;
    if (!tr.docChanged || !starts.length) return starts;
    return starts.map((s) => ({ pos: tr.changes.mapPos(s.pos, -1), page: s.page }));
  },
});

// The page starts as line starts, in order (pages 2 onwards; one per line).
function pageStarts(state) {
  const seen = new Set();
  const out = [];
  for (const { pos, page } of state.field(pagesField)) {
    const from = state.doc.lineAt(Math.min(pos, state.doc.length)).from;
    if (seen.has(from)) continue;
    seen.add(from);
    out.push({ from, page });
  }
  return out.sort((a, b) => a.from - b.from);
}

class PageLineWidget extends WidgetType {
  constructor(page) {
    super();
    this.page = page;
  }
  eq(other) {
    return other.page === this.page;
  }
  toDOM() {
    const el = document.createElement("div");
    el.className = "pp-page-line";
    el.setAttribute("aria-label", `Page ${this.page}`);
    const label = document.createElement("span");
    label.className = "pp-page-line-label";
    label.textContent = `Page ${this.page}`;
    el.appendChild(label);
    return el;
  }
  get estimatedHeight() {
    return 22;
  }
}

const pageLines = EditorView.decorations.compute([pagesField], (state) =>
  Decoration.set(
    pageStarts(state).map(({ from, page }) => Decoration.widget({ widget: new PageLineWidget(page), block: true, side: -1 }).range(from)),
    true,
  ),
);

// ---- Real pages ------------------------------------------------------------------------------

const PX_PER_MM = 96 / 25.4;
const DESK_PX = 28; // the grey desk between two sheets

function geometry(state) {
  const cfg = state.facet(pageViewFacet);
  return { margin: Math.round(cfg.marginMm * PX_PER_MM), inner: (cfg.paperHeightMm - 2 * cfg.marginMm) * PX_PER_MM };
}

// The first line on paper (the hidden properties are not).
const firstShown = (state) => {
  const end = frontMatterEnd(state);
  return end < 0 ? 0 : end + 1;
};

// How much each sheet is padded, `[page 1, page 2, …]` in px (see `sizer`).
const setFillers = StateEffect.define();
const fillerField = StateField.define({
  create: () => [],
  update: (v, tr) => tr.effects.reduce((acc, e) => (e.is(setFillers) ? e.value : acc), v),
});

const sheetPart = (cls, height) => {
  const el = document.createElement("div");
  el.className = cls;
  el.style.height = `${height}px`;
  return el;
};

// The bottom of a sheet: its padding, its bottom margin and its page number.
function sheetEnd(page, total, filler, margin) {
  const end = sheetPart("pp-sheet-end", filler + margin);
  if (total > 1) {
    const num = document.createElement("span");
    num.className = "pp-sheet-num";
    num.textContent = String(page);
    end.appendChild(num);
  }
  return end;
}

// Above page 1: the top margin of the first sheet.
class SheetTopWidget extends WidgetType {
  constructor(margin) {
    super();
    this.margin = margin;
  }
  eq(other) {
    return other.margin === this.margin;
  }
  toDOM() {
    const el = sheetPart("pp-sheet-top", this.margin);
    el.setAttribute("aria-hidden", "true");
    return el;
  }
  get estimatedHeight() {
    return this.margin;
  }
}

// Where a page starts: the end of the sheet before, the desk, the top of the next sheet.
class SheetGapWidget extends WidgetType {
  constructor(page, total, filler, margin) {
    super();
    Object.assign(this, { page, total, filler, margin });
  }
  eq(o) {
    return o.page === this.page && o.total === this.total && o.filler === this.filler && o.margin === this.margin;
  }
  toDOM() {
    const el = document.createElement("div");
    el.className = "pp-sheet-gap";
    el.setAttribute("aria-label", `Page ${this.page + 1}`);
    el.append(sheetEnd(this.page, this.total, this.filler, this.margin), sheetPart("pp-sheet-desk", DESK_PX), sheetPart("pp-sheet-top", this.margin));
    return el;
  }
  get estimatedHeight() {
    return this.filler + 2 * this.margin + DESK_PX;
  }
}

// Below the last page: the end of the last sheet.
class SheetEndWidget extends WidgetType {
  constructor(page, total, filler, margin) {
    super();
    Object.assign(this, { page, total, filler, margin });
  }
  eq(o) {
    return o.page === this.page && o.total === this.total && o.filler === this.filler && o.margin === this.margin;
  }
  toDOM() {
    const el = document.createElement("div");
    el.className = "pp-sheet-last";
    el.appendChild(sheetEnd(this.page, this.total, this.filler, this.margin));
    return el;
  }
  get estimatedHeight() {
    return this.filler + this.margin;
  }
}

// The page starts that get a gap (a start on the first line shown has none).
const sheetStarts = (state) => pageStarts(state).filter((s) => s.from > firstShown(state));

const sheets = EditorView.decorations.compute([pagesField, fillerField, "doc"], (state) => {
  const { margin } = geometry(state);
  const fillers = state.field(fillerField);
  const starts = sheetStarts(state);
  const total = starts.length + 1;
  const out = [Decoration.widget({ widget: new SheetTopWidget(margin), block: true, side: -1 }).range(firstShown(state))];
  starts.forEach((s, i) => {
    const widget = new SheetGapWidget(i + 1, total, fillers[i] ?? 0, margin);
    out.push(Decoration.widget({ widget, block: true, side: -1 }).range(s.from));
  });
  const last = new SheetEndWidget(total, total, fillers[starts.length] ?? 0, margin);
  out.push(Decoration.widget({ widget: last, block: true, side: 1 }).range(state.doc.length));
  return Decoration.set(out, true);
});

// Pads each sheet to the paper's height: measures each page's text with CodeMirror's line heights
// (the widgets' own heights are known, so they are left out) and hands the rest to the widget
// below it. Measured outside CodeMirror's update cycle; a change of 1 px or less is ignored, so
// it settles (the text's height does not depend on the padding).
const sizer = ViewPlugin.fromClass(
  class {
    constructor(view) {
      this.view = view;
      this.timer = null;
      this.recent = [];
      this.schedule();
    }
    update(u) {
      if (u.heightChanged || u.geometryChanged || u.docChanged || u.startState.field(pagesField) !== u.state.field(pagesField)) this.schedule();
    }
    schedule() {
      clearTimeout(this.timer);
      this.timer = setTimeout(() => this.measure(), 0);
    }
    measure() {
      const { view } = this;
      const { state } = view;
      if (!view.dom.isConnected || state.facet(pageViewFacet)?.style !== "pages") return;
      const { margin, inner } = geometry(state);
      const fillers = state.field(fillerField);
      const tops = [firstShown(state), ...sheetStarts(state).map((s) => s.from)];
      const next = tops.map((from, i) => {
        const own = i === 0 ? margin : (fillers[i - 1] ?? 0) + 2 * margin + DESK_PX;
        const textTop = view.lineBlockAt(from).top + own;
        const textEnd = i + 1 < tops.length ? view.lineBlockAt(tops[i + 1]).top : view.lineBlockAt(state.doc.length).bottom - ((fillers[i] ?? 0) + margin);
        return Math.max(0, Math.round(inner - (textEnd - textTop)));
      });
      if (next.length === fillers.length && next.every((f, i) => Math.abs(f - fillers[i]) <= 1)) return;
      // never chase our own tail: at most a few corrections a second
      const now = performance.now();
      this.recent = this.recent.filter((t) => now - t < 1000);
      if (this.recent.length >= 6) {
        clearTimeout(this.timer);
        this.timer = setTimeout(() => this.measure(), 300);
        return;
      }
      this.recent.push(now);
      view.dispatch({ effects: setFillers.of(next) });
    }
    destroy() {
      clearTimeout(this.timer);
    }
  },
);

// Asks for a layout after each pause in typing and applies the answer.
const controller = ViewPlugin.fromClass(
  class {
    constructor(view) {
      this.view = view;
      this.pending = null; // { seq, doc, changes }: the request in flight and typing since
      this.timer = null;
      this.frame = null;
      this.schedule(50);
    }
    update(u) {
      // another paper size: the plugin is kept across the reconfigure, so ask again here
      const was = u.startState.facet(pageViewFacet);
      const now = u.state.facet(pageViewFacet);
      if (was && now && was.paper !== now.paper) {
        this.pending = null;
        this.schedule(0);
        return;
      }
      if (!u.docChanged) return;
      if (this.pending) this.pending.changes = this.pending.changes.compose(u.changes);
      this.schedule(LAYOUT_DELAY_MS);
    }
    schedule(ms) {
      clearTimeout(this.timer);
      this.timer = setTimeout(() => this.request(), ms);
    }
    request() {
      const { state } = this.view;
      const rt = rtOf(state);
      const seq = ++seqCounter;
      this.pending = { seq, doc: state.doc, changes: ChangeSet.empty(state.doc.length) };
      rt.emit("print_layout", { docId: rt.getDocId(), seq, text: state.doc.toString() });
    }
    // Python's answer: the URL of the print page for request `seq`.
    async ready(seq, url) {
      if (!this.pending || this.pending.seq !== seq) return;
      let pages;
      try {
        pages = await this.layout(url);
      } catch {
        return; // the lines stay as they were; the next pause in typing tries again
      }
      const pending = this.pending;
      if (!pending || pending.seq !== seq) return;
      const starts = pages
        .filter((p) => p.page > 1 && p.line > 0 && p.line <= pending.doc.lines)
        .map((p) => ({ pos: pending.changes.mapPos(pending.doc.line(p.line).from, -1), page: p.page }));
      this.pending = null;
      this.view.dispatch({ effects: setPages.of(starts) });
    }
    layout(url) {
      if (!this.frame) {
        this.frame = document.createElement("iframe");
        this.frame.className = "pp-print-frame";
        this.frame.setAttribute("aria-hidden", "true");
        this.frame.tabIndex = -1;
        document.body.appendChild(this.frame);
      }
      const frame = this.frame;
      return new Promise((resolve, reject) => {
        const timer = setTimeout(() => reject(new Error("layout timed out")), LAYOUT_TIMEOUT_MS);
        frame.onload = async () => {
          try {
            const result = await frame.contentWindow.ppPrintReady;
            clearTimeout(timer);
            if (!result || result.error) reject(new Error(result ? result.error : "no layout"));
            else resolve(result.pages);
          } catch (err) {
            clearTimeout(timer);
            reject(err);
          }
        };
        frame.src = url;
      });
    }
    destroy() {
      clearTimeout(this.timer);
      this.frame?.remove();
    }
  },
);

// The properties block is folded away (in Live Preview and in Source mode alike).
const hiddenProperties = StateField.define({
  create: (state) => hide(state),
  update: (value, tr) => (tr.docChanged || tr.reconfigured || syntaxTree(tr.startState) !== syntaxTree(tr.state) ? hide(tr.state) : value),
  provide: (f) => EditorView.decorations.from(f),
});

function hide(state) {
  const end = frontMatterEnd(state);
  return end < 0 ? Decoration.none : Decoration.set([Decoration.replace({ block: true }).range(0, end)]);
}

// The caret and selections never enter the hidden properties block.
const keepOutOfProperties = EditorState.transactionFilter.of((tr) => {
  if (!tr.selection) return tr;
  const end = frontMatterEnd(tr.state);
  if (end < 0) return tr;
  const min = end + 1;
  if (tr.selection.ranges.every((r) => r.from >= min)) return tr;
  const ranges = tr.selection.ranges.map((r) => EditorSelection.range(Math.max(min, r.anchor), Math.max(min, r.head)));
  return [tr, { selection: EditorSelection.create(ranges, tr.selection.mainIndex), sequential: true }];
});

// Typing and deleting cannot reach into it either (Backspace at the start of the first line would
// otherwise join that line to the closing `---`). Changes made by the app (renames, tidy) pass.
const protectProperties = EditorState.changeFilter.of((tr) => {
  if (!tr.isUserEvent("input") && !tr.isUserEvent("delete")) return true;
  const end = frontMatterEnd(tr.startState);
  return end < 0 ? true : [0, end + 1];
});

export function pageView(config) {
  const real = config.style === "pages";
  return [
    pageViewFacet.of(config),
    pagesField,
    real ? [fillerField, sheets, sizer] : pageLines,
    hiddenProperties,
    controller,
    keepOutOfProperties,
    protectProperties,
    EditorView.editorAttributes.of({
      class: real ? "pp-page-view pp-real-pages" : "pp-page-view",
      style: `--pp-page-text: ${config.textWidthMm}mm; --pp-margin: ${config.marginMm}mm`,
    }),
  ];
}

// Python's answer to a `print_layout` request (the editor's API calls this).
export function printLayoutReady(view, seq, url) {
  view.plugin(controller)?.ready(seq, url);
}
