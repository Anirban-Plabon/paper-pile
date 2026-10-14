// Obsidian-style Live Preview, inline part: render markdown in place, but keep the raw syntax
// of whatever the cursor touches. Render-only: no logic lives here.
//
// Reveal rules (see reveal.js):
//   * inline elements (emphasis, strike, code, math, ...): syntax shows while a selection range
//     touches that element, so only the element being edited turns raw, not the whole line;
//   * line prefixes (`#`, `>`, list markers): syntax shows while the caret is on that line.
// Block widgets (display math, mermaid, tables, ...) live in blocks.js (a StateField).
import { syntaxTree } from "@codemirror/language";
import { Decoration, ViewPlugin } from "@codemirror/view";
import { activeLines, touches } from "./reveal.js";
import { BulletWidget, CheckboxWidget, HrWidget, MathWidget } from "./widgets.js";

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
const QUOTE_LINE = [1, 2, 3].map((n) => lineDeco(`pp-quote pp-quote-${n}`));
const LIST_GLYPHS = ["\u2022", "\u25E6", "\u25AA"]; // bullet, white bullet, small square by depth
const LIST_NUM = mark("pp-list-num");
const TASK_DONE = mark("pp-task-done");
const LINE_PAD_PX = 6; // CodeMirror's own left padding of a line; our padding must add to it
const hangingIndent = (cols) =>
  Decoration.line({
    class: "pp-li",
    attributes: { style: `padding-left:calc(${cols}ch + ${LINE_PAD_PX}px);text-indent:-${cols}ch` },
  });

// Everything the builder needs while walking the tree.
function context(view) {
  const { state } = view;
  return { state, doc: state.doc, active: activeLines(state), out: [], quoteDepth: new Map() };
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

  // List items: bullet glyph or number styling, task checkbox, and a hanging indent so wrapped
  // lines line up under the item's text (the editor font is monospace, so `ch` is exact).
  ListItem: (cx, node) => {
    const item = node.node;
    const mark = item.getChild("ListMark");
    if (!mark) return;
    const first = cx.doc.lineAt(item.from);
    const raw = cx.active.has(first.number); // caret on the item's first line: show real syntax
    const ordered = item.parent?.name === "OrderedList";
    const task = item.getChild("Task");
    const box = task?.getChild("TaskMarker");
    let depth = 0;
    for (let a = item.parent?.parent; a; a = a.parent) if (a.name === "ListItem") depth++;

    let col; // visual column where the item's text starts on its first line
    if (box && !raw) {
      const checked = /[xX]/.test(cx.doc.sliceString(box.from + 1, box.from + 2));
      cx.out.push(
        Decoration.replace({ widget: new CheckboxWidget(checked, box.from + 1 - mark.from) }).range(mark.from, box.to),
      );
      if (checked) cx.out.push(TASK_DONE.range(Math.min(box.to + 1, task.to), task.to)); // text, not the space
      col = mark.from - first.from + 3; // widget (2ch) + the space after it
    } else {
      let start = box ? box.to : mark.to;
      while (cx.doc.sliceString(start, start + 1) === " ") start++;
      col = start - first.from;
      if (ordered) cx.out.push(LIST_NUM.range(mark.from, mark.to));
      else if (!box && !raw) {
        cx.out.push(Decoration.replace({ widget: new BulletWidget(LIST_GLYPHS[Math.min(depth, 2)]) }).range(mark.from, mark.to));
      }
    }
    const own = task ? [task] : item.getChildren("Paragraph");
    for (const r of own) {
      for (let n = cx.doc.lineAt(r.from).number; n <= cx.doc.lineAt(r.to).number; n++) {
        cx.out.push(hangingIndent(col).range(cx.doc.line(n).from));
      }
    }
  },

  // `>` quote markers: hidden off-line; every quoted line gets a bar per nesting level.
  QuoteMark: (cx, node) => {
    const line = cx.doc.lineAt(node.from);
    cx.quoteDepth.set(line.number, (cx.quoteDepth.get(line.number) ?? 0) + 1);
    if (cx.active.has(line.number)) return;
    const space = cx.doc.sliceString(node.to, node.to + 1) === " " ? 1 : 0;
    cx.out.push(hide.range(node.from, node.to + space));
  },

  // `---` / `***` / `___`: a drawn rule off-line.
  HorizontalRule: (cx, node) => {
    if (cx.active.has(cx.doc.lineAt(node.from).number)) return;
    cx.out.push(Decoration.replace({ widget: new HrWidget() }).range(node.from, node.to));
  },

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
  for (const [lineNo, depth] of cx.quoteDepth) {
    cx.out.push(QUOTE_LINE[Math.min(depth, 3) - 1].range(cx.doc.line(lineNo).from));
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
