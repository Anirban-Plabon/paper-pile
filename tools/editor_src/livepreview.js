// Obsidian-style Live Preview: render markdown inline, but keep the raw syntax on
// every line that holds the cursor or a selection. Render-only: no logic lives here.
import { syntaxTree } from "@codemirror/language";
import { Decoration, ViewPlugin, WidgetType } from "@codemirror/view";
import katex from "katex";

class MathWidget extends WidgetType {
  constructor(src) {
    super();
    this.src = src;
  }
  eq(other) {
    return other.src === this.src;
  }
  toDOM() {
    const el = document.createElement("span");
    el.className = "pp-math";
    el.innerHTML = katex.renderToString(this.src, { throwOnError: false });
    return el;
  }
  ignoreEvent() {
    return false;
  }
}

const hide = Decoration.replace({});
const mark = (cls) => Decoration.mark({ class: cls });
const marks = {
  StrongEmphasis: mark("pp-strong"),
  Emphasis: mark("pp-em"),
  Strikethrough: mark("pp-strike"),
  InlineCode: mark("pp-code"),
};
const lineDeco = Array.from({ length: 6 }, (_, i) => Decoration.line({ class: `pp-h pp-h${i + 1}` }));
const HIDE_MARKS = new Set(["EmphasisMark", "StrikethroughMark", "CodeMark"]);

function activeLines(state) {
  const lines = new Set();
  for (const r of state.selection.ranges) {
    const a = state.doc.lineAt(r.from).number;
    const b = state.doc.lineAt(r.to).number;
    for (let n = a; n <= b; n++) lines.add(n);
  }
  return lines;
}

function build(view) {
  const { state } = view;
  const active = activeLines(state);
  const isActive = (from, to) => {
    const a = state.doc.lineAt(from).number;
    const b = state.doc.lineAt(to).number;
    for (let n = a; n <= b; n++) if (active.has(n)) return true;
    return false;
  };
  const out = [];
  for (const { from, to } of view.visibleRanges) {
    syntaxTree(state).iterate({
      from,
      to,
      enter(node) {
        const name = node.name;
        const h = /^ATXHeading([1-6])$/.exec(name);
        if (h) out.push(lineDeco[+h[1] - 1].range(state.doc.lineAt(node.from).from));
        else if (marks[name]) out.push(marks[name].range(node.from, node.to));
        else if (name === "HeaderMark") {
          const line = state.doc.lineAt(node.from);
          if (!active.has(line.number)) {
            const end = state.sliceDoc(node.to, node.to + 1) === " " ? node.to + 1 : node.to;
            out.push(hide.range(node.from, end));
          }
        } else if (HIDE_MARKS.has(name)) {
          if (!isActive(node.from, node.to)) out.push(hide.range(node.from, node.to));
        } else if (name === "InlineMath") {
          // `$x$` or `$$x$$` (both are inline math inside a paragraph)
          const d = state.sliceDoc(node.from, node.from + 2) === "$$" ? 2 : 1;
          const src = state.sliceDoc(node.from + d, node.to - d);
          if (!isActive(node.from, node.to) && !src.includes("\n")) {
            out.push(Decoration.replace({ widget: new MathWidget(src) }).range(node.from, node.to));
          }
        }
      },
    });
  }
  return Decoration.set(out, true);
}

export const livePreview = ViewPlugin.fromClass(
  class {
    constructor(view) {
      this.decorations = build(view);
    }
    update(u) {
      if (u.docChanged || u.selectionSet || u.viewportChanged || syntaxTree(u.startState) !== syntaxTree(u.state)) {
        this.decorations = build(u.view);
      }
    }
  },
  { decorations: (v) => v.decorations },
);
