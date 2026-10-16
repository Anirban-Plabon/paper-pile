// Block widgets for Live Preview: display math ($$...$$) and ```mermaid fences.
// CM6 only allows block / line-spanning replace decorations from a StateField, so these
// live apart from the inline ViewPlugin in livepreview.js. Render-only: no logic here.
import { ensureSyntaxTree, syntaxTree } from "@codemirror/language";
import { Facet, StateEffect, StateField } from "@codemirror/state";
import { Decoration, EditorView, WidgetType } from "@codemirror/view";
import katex from "katex";
import { copyButton } from "./blockactions.js";
import { EmbedWidget } from "./embedwidget.js";
import { TablePreview, TableWidget } from "./tablewidget.js";
import { parseWikilink } from "./wikilink.js";

export const themeFacet = Facet.define({ combine: (v) => v[0] ?? "light" });

const CACHE_MAX = 100;
const svgCache = new Map(); // `${theme}\0${src}` -> svg string
let mermaidPromise = null;
let renderChain = Promise.resolve();
let renderCount = 0;

const loadMermaid = () => (mermaidPromise ??= import("mermaid").then((m) => m.default));

// Renders are serialized: mermaid keeps global state (initialize + temp DOM nodes).
// `parse` runs first and throws on invalid input, so mermaid never injects its error graphic.
export function renderMermaid(src, theme) {
  const key = `${theme}\0${src}`;
  if (svgCache.has(key)) return Promise.resolve(svgCache.get(key));
  const job = renderChain.then(async () => {
    const mermaid = await loadMermaid();
    mermaid.initialize({ startOnLoad: false, securityLevel: "strict", theme: theme === "dark" ? "dark" : "default" });
    await mermaid.parse(src);
    const { svg } = await mermaid.render(`pp-mmd-${++renderCount}`, src);
    if (svgCache.size >= CACHE_MAX) svgCache.delete(svgCache.keys().next().value);
    svgCache.set(key, svg);
    return svg;
  });
  renderChain = job.catch(() => {});
  return job;
}

function revealOnMouseDown(dom, view) {
  dom.addEventListener("mousedown", (e) => {
    e.preventDefault();
    view.dispatch({ selection: { anchor: view.posAtDOM(dom) } });
    view.focus();
  });
}

function showError(el, message) {
  el.className = "pp-render-error";
  el.textContent = message;
}

class DisplayMathWidget extends WidgetType {
  constructor(src) {
    super();
    this.src = src;
  }
  eq(other) {
    return other.src === this.src;
  }
  toDOM(view) {
    const el = document.createElement("div");
    el.className = "pp-math-block";
    el.innerHTML = katex.renderToString(this.src, { displayMode: true, throwOnError: false });
    el.appendChild(copyButton("math", "", this.src));
    revealOnMouseDown(el, view);
    return el;
  }
  ignoreEvent() {
    return false;
  }
}

// YAML front matter as a compact properties block. Logic stays in Python: this only splits
// `key: value` lines for display (continuation lines are appended to the previous value).
class FrontMatterWidget extends WidgetType {
  constructor(text) {
    super();
    this.text = text;
  }
  eq(other) {
    return other.text === this.text;
  }
  rows() {
    const rows = [];
    for (const line of this.text.split("\n")) {
      if (!line.trim()) continue;
      const m = /^([^\s:#-][^:]*):\s*(.*)$/.exec(line);
      if (m) rows.push([m[1], m[2]]);
      else if (rows.length) rows[rows.length - 1][1] += (rows[rows.length - 1][1] ? " " : "") + line.trim();
    }
    return rows;
  }
  toDOM(view) {
    const el = document.createElement("div");
    el.className = "pp-frontmatter";
    const rows = this.rows();
    if (!rows.length) el.textContent = "properties";
    for (const [k, v] of rows) {
      const row = document.createElement("div");
      row.className = "pp-fm-row";
      const key = document.createElement("span");
      key.className = "pp-fm-key";
      key.textContent = k;
      const val = document.createElement("span");
      val.className = "pp-fm-val";
      val.textContent = v;
      row.append(key, val);
      el.appendChild(row);
    }
    revealOnMouseDown(el, view);
    return el;
  }
  ignoreEvent() {
    return false;
  }
}

class MermaidWidget extends WidgetType {
  constructor(src, theme) {
    super();
    this.src = src;
    this.theme = theme;
  }
  eq(other) {
    return other.src === this.src && other.theme === this.theme;
  }
  get estimatedHeight() {
    return 200;
  }
  toDOM(view) {
    const el = document.createElement("div");
    el.className = "pp-mermaid";
    const body = document.createElement("div");
    el.appendChild(body);
    el.appendChild(copyButton("diagram", "mermaid", this.src));
    const cached = svgCache.get(`${this.theme}\0${this.src}`);
    if (cached) {
      body.innerHTML = cached; // no "Rendering…" flash when a known diagram comes back
    } else {
      body.textContent = "Rendering diagram…";
      renderMermaid(this.src, this.theme).then(
        (svg) => {
          body.innerHTML = svg;
          view.requestMeasure();
        },
        (err) => {
          showError(body, `Mermaid: ${String(err?.message ?? err).split("\n")[0]}`);
          view.requestMeasure();
        },
      );
    }
    revealOnMouseDown(el, view);
    return el;
  }
  ignoreEvent() {
    return false;
  }
}

// Block containers whose insides can never hold a block widget: skip them while walking the tree.
const INLINE_ONLY = new Set(["Paragraph", "SetextHeading1", "SetextHeading2", "LinkReference"]);
const isInlineOnly = (name) => INLINE_ONLY.has(name) || name.startsWith("ATXHeading");

// Every block that could be shown as a widget, as whole-line ranges. Rebuilt only when the
// document, the syntax tree or the theme changes; the selection never triggers a tree walk.
function candidates(state) {
  const { doc } = state;
  const theme = state.facet(themeFacet);
  const out = [];
  // `editing`: a widget shown above the source while the selection touches the block
  const push = (node, widget, editing = null) => {
    out.push({ from: doc.lineAt(node.from).from, to: doc.lineAt(node.to).to, widget, editing });
  };
  const tree = ensureSyntaxTree(state, doc.length, 50) ?? syntaxTree(state);
  tree.iterate({
    enter(node) {
      if (node.name === "Paragraph") {
        // a line of its own that is just `![[note]]` is an embed (the note's content, not a link),
        // also inside a paragraph of several lines
        for (let n = doc.lineAt(node.from).number; n <= doc.lineAt(node.to).number; n++) {
          const line = doc.line(n);
          const m = /^!\[\[([^\[\]\n]+)\]\]$/.exec(line.text.trim());
          const target = m ? parseWikilink(m[1]) : null;
          if (target && target.note) out.push({ from: line.from, to: line.to, widget: new EmbedWidget(target.note, target.heading), editing: null });
        }
        return false;
      }
      if (isInlineOnly(node.name)) return false;
      if (node.name === "Table") {
        const src = doc.sliceString(node.from, node.to);
        push(node, new TableWidget(src, state, node.node), new TablePreview(src, state, node.node));
        return false; // its cells are rendered by the widget
      } else if (node.name === "FrontMatter") {
        const marks = node.node.getChildren("FrontMatterMark");
        push(node, new FrontMatterWidget(doc.sliceString(marks[0].to, marks[1].from).trim()));
      } else if (node.name === "BlockMath") {
        const marks = node.node.getChildren("BlockMathMark");
        // a block is only ever parsed when it is closed, so both marks exist
        const raw = doc.sliceString(marks[0].to, marks[marks.length - 1].from);
        // list indentation and blockquote markers are not part of the formula
        const src = raw.split("\n").map((l) => l.replace(/^[\s>]+/, "")).join("\n").trim();
        if (src) push(node, new DisplayMathWidget(src));
      } else if (node.name === "FencedCode") {
        const info = node.node.getChild("CodeInfo");
        if (!info || doc.sliceString(info.from, info.to).trim() !== "mermaid") return;
        const text = node.node.getChild("CodeText");
        const src = text ? doc.sliceString(text.from, text.to).trim() : "";
        if (src) push(node, new MermaidWidget(src, theme));
      }
    },
  });
  return out;
}

// Does the selection reveal this block's source? A caret on the block (edges count) or a selection
// inside it does. A selection that only passes over the block, or contains it, leaves it drawn:
// dragging across a diagram must not swap it for its source under the pointer (that moved the
// layout while selecting and made the selection flicker).
function reveals(state, from, to) {
  for (const r of state.selection.ranges) {
    if (r.empty ? r.from <= to && r.from >= from : r.from >= from && r.to <= to) return true;
  }
  return false;
}

// While the mouse button is held (a drag-selection) the set of drawn blocks stays as it was;
// the final selection is applied once on release.
const dragging = StateEffect.define();
const dragField = StateField.define({
  create: () => false,
  update: (v, tr) => tr.effects.reduce((acc, e) => (e.is(dragging) ? e.value : acc), v),
});
const dragTracking = EditorView.domEventHandlers({
  mousedown: (e, view) => {
    if (e.button !== 0) return false;
    view.dispatch({ effects: dragging.of(true) });
    const end = () => {
      window.removeEventListener("mouseup", end, true);
      window.removeEventListener("blur", end, true);
      view.dispatch({ effects: dragging.of(false) });
    };
    window.addEventListener("mouseup", end, true);
    window.addEventListener("blur", end, true);
    return false;
  },
});

// The widgets to show now: every candidate the selection does not reveal. A table being edited
// shows its source with a live rendered preview above it.
function visible(items, state) {
  const out = [];
  for (const { from, to, widget, editing } of items) {
    if (!reveals(state, from, to)) out.push(Decoration.replace({ widget, block: true }).range(from, to));
    else if (editing) out.push(Decoration.widget({ widget: editing, block: true, side: -1 }).range(from));
  }
  return Decoration.set(out, true);
}

const derive = (items, state) => ({ items, set: visible(items, state) });

const blockField = StateField.define({
  create: (state) => derive(candidates(state), state),
  update(value, tr) {
    if (tr.docChanged || tr.reconfigured || syntaxTree(tr.startState) !== syntaxTree(tr.state)) {
      return derive(candidates(tr.state), tr.state);
    }
    const held = tr.state.field(dragField, false);
    const released = tr.startState.field(dragField, false) && !held;
    if (held) return value;
    if (released || !tr.state.selection.eq(tr.startState.selection)) {
      return { items: value.items, set: visible(value.items, tr.state) };
    }
    return value;
  },
  provide: (f) => EditorView.decorations.from(f, (v) => v.set),
});

export const blocks = [dragField, dragTracking, blockField];
