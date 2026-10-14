// Obsidian-style Live Preview, inline part: render markdown in place, but keep the raw syntax
// of whatever the cursor touches. Render-only: no logic lives here.
//
// Reveal rules (see reveal.js):
//   * inline elements (emphasis, strike, code, math, ...): syntax shows while a selection range
//     touches that element, so only the element being edited turns raw, not the whole line;
//   * line prefixes (`#`, `>`, list markers): syntax shows while the caret is on that line.
// Block widgets (display math, mermaid, tables, ...) live in blocks.js (a StateField).
import { syntaxTree } from "@codemirror/language";
import { Decoration, ViewPlugin, WidgetType } from "@codemirror/view";
import katex from "katex";
import { activeLines, touches } from "./reveal.js";

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
const lineDeco = (cls) => Decoration.line({ class: cls });

// Inline elements: a class over the whole element, and the child marks that are hidden when the
// element is not being edited.
const INLINE = {
  StrongEmphasis: { cls: "pp-strong", marks: "EmphasisMark" },
  Emphasis: { cls: "pp-em", marks: "EmphasisMark" },
  Strikethrough: { cls: "pp-strike", marks: "StrikethroughMark" },
  InlineCode: { cls: "pp-code", marks: "CodeMark" },
};
const INLINE_DECO = Object.fromEntries(Object.entries(INLINE).map(([k, v]) => [k, mark(v.cls)]));
const HEADING_LINE = Array.from({ length: 6 }, (_, i) => lineDeco(`pp-h pp-h${i + 1}`));
const SETEXT_UNDERLINE = lineDeco("pp-setext-underline");

// Everything the builder needs while walking the tree.
function context(view) {
  const { state } = view;
  return { state, doc: state.doc, active: activeLines(state), out: [] };
}

const handlers = {
  ...Object.fromEntries(
    Object.keys(INLINE).map((name) => [
      name,
      (cx, node) => {
        cx.out.push(INLINE_DECO[name].range(node.from, node.to));
        if (touches(cx.state, node.from, node.to)) return;
        for (const m of node.node.getChildren(INLINE[name].marks)) cx.out.push(hide.range(m.from, m.to));
      },
    ]),
  ),

  // `#`..`######` (ATX) headings: the size comes from the line, the marks hide off-line.
  ...Object.fromEntries(
    [1, 2, 3, 4, 5, 6].map((level) => [
      `ATXHeading${level}`,
      (cx, node) => {
        const line = cx.doc.lineAt(node.from);
        cx.out.push(HEADING_LINE[level - 1].range(line.from));
        if (cx.active.has(line.number)) return;
        for (const m of node.node.getChildren("HeaderMark")) {
          const space = cx.doc.sliceString(m.to, m.to + 1) === " " ? 1 : 0;
          cx.out.push(hide.range(m.from, m.to + space));
        }
      },
    ]),
  ),

  // Setext headings (`Title` over `=====`): the text lines are headings, the underline is dimmed.
  ...Object.fromEntries(
    [1, 2].map((level) => [
      `SetextHeading${level}`,
      (cx, node) => {
        const underline = node.node.getChild("HeaderMark");
        const last = cx.doc.lineAt(underline ? underline.from : node.to);
        for (let n = cx.doc.lineAt(node.from).number; n < last.number; n++) {
          cx.out.push(HEADING_LINE[level - 1].range(cx.doc.line(n).from));
        }
        if (underline && !cx.active.has(last.number)) cx.out.push(SETEXT_UNDERLINE.range(last.from));
      },
    ]),
  ),

  // `\*` : the backslash is only an escape; hide it unless the escape is being edited.
  Escape: (cx, node) => {
    if (!touches(cx.state, node.from, node.to)) cx.out.push(hide.range(node.from, node.from + 1));
  },

  // `$x$` / `$$x$$` inside a paragraph.
  InlineMath: (cx, node) => {
    const d = cx.doc.sliceString(node.from, node.from + 2) === "$$" ? 2 : 1;
    const src = cx.doc.sliceString(node.from + d, node.to - d);
    if (touches(cx.state, node.from, node.to) || src.includes("\n")) return;
    cx.out.push(Decoration.replace({ widget: new MathWidget(src) }).range(node.from, node.to));
  },
};

function build(view) {
  const cx = context(view);
  for (const { from, to } of view.visibleRanges) {
    syntaxTree(cx.state).iterate({
      from,
      to,
      enter(node) {
        const handle = handlers[node.name];
        if (handle) handle(cx, node);
      },
    });
  }
  return Decoration.set(cx.out, true);
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
