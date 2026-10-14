// Block widgets for Live Preview: display math ($$...$$) and ```mermaid fences.
// CM6 only allows block / line-spanning replace decorations from a StateField, so these
// live apart from the inline ViewPlugin in livepreview.js. Render-only: no logic here.
import { ensureSyntaxTree, syntaxTree } from "@codemirror/language";
import { Facet, StateField } from "@codemirror/state";
import { Decoration, EditorView, WidgetType } from "@codemirror/view";
import katex from "katex";
import { touches } from "./reveal.js";

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
    el.textContent = "Rendering diagram…";
    renderMermaid(this.src, this.theme).then(
      (svg) => {
        el.textContent = "";
        el.innerHTML = svg;
        view.requestMeasure();
      },
      (err) => {
        showError(el, `Mermaid: ${String(err?.message ?? err).split("\n")[0]}`);
        view.requestMeasure();
      },
    );
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
  const push = (node, widget) => {
    out.push({ from: doc.lineAt(node.from).from, to: doc.lineAt(node.to).to, widget });
  };
  const tree = ensureSyntaxTree(state, doc.length, 50) ?? syntaxTree(state);
  tree.iterate({
    enter(node) {
      if (isInlineOnly(node.name)) return false;
      if (node.name === "BlockMath") {
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

// The widgets to show now: every candidate the selection does not touch.
function visible(items, state) {
  const out = [];
  for (const { from, to, widget } of items) {
    if (!touches(state, from, to)) out.push(Decoration.replace({ widget, block: true }).range(from, to));
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
    if (!tr.state.selection.eq(tr.startState.selection)) {
      return { items: value.items, set: visible(value.items, tr.state) };
    }
    return value;
  },
  provide: (f) => EditorView.decorations.from(f, (v) => v.set),
});

export const blocks = [blockField];
