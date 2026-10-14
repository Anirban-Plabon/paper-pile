// Block widgets for Live Preview: display math ($$...$$) and ```mermaid fences.
// CM6 only allows block / line-spanning replace decorations from a StateField, so these
// live apart from the inline ViewPlugin in livepreview.js. Render-only: no logic here.
import { ensureSyntaxTree, syntaxTree } from "@codemirror/language";
import { Facet, StateField } from "@codemirror/state";
import { Decoration, EditorView, WidgetType } from "@codemirror/view";
import katex from "katex";

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

function build(state) {
  const { doc } = state;
  const theme = state.facet(themeFacet);
  const touched = (from, to) => state.selection.ranges.some((r) => r.from <= to && r.to >= from);
  const out = [];
  const add = (node, widget) => {
    const from = doc.lineAt(node.from).from;
    const to = doc.lineAt(node.to).to;
    if (!touched(from, to)) out.push(Decoration.replace({ widget, block: true }).range(from, to));
  };
  const tree = ensureSyntaxTree(state, doc.length, 50) ?? syntaxTree(state);
  tree.iterate({
    enter(node) {
      if (node.name === "BlockMath") {
        const marks = node.node.getChildren("BlockMathMark");
        const open = marks[0];
        const close = marks.length > 1 ? marks[marks.length - 1] : null;
        const src = doc.sliceString(open.to, close ? close.from : node.to).trim();
        if (src) add(node, new DisplayMathWidget(src));
      } else if (node.name === "FencedCode") {
        const info = node.node.getChild("CodeInfo");
        if (!info || doc.sliceString(info.from, info.to).trim() !== "mermaid") return;
        const text = node.node.getChild("CodeText");
        const src = text ? doc.sliceString(text.from, text.to).trim() : "";
        if (src) add(node, new MermaidWidget(src, theme));
      }
    },
  });
  return Decoration.set(out, true);
}

const blockField = StateField.define({
  create: (state) => build(state),
  update(value, tr) {
    const changed =
      tr.docChanged ||
      tr.reconfigured ||
      !tr.state.selection.eq(tr.startState.selection) ||
      syntaxTree(tr.startState) !== syntaxTree(tr.state);
    return changed ? build(tr.state) : value;
  },
  provide: (f) => EditorView.decorations.from(f),
});

export const blocks = [blockField];
