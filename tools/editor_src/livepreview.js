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
import { editorContext, normNote } from "./context.js";
import { parseWikilink } from "./wikilink.js";
import { activeLines, refreshEffect, touches } from "./reveal.js";
import { BulletWidget, CheckboxWidget, HrWidget, ImageWidget, MathWidget } from "./widgets.js";

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
const linkDeco = (href) =>
  Decoration.mark({ class: "pp-link", attributes: href ? { "data-href": href, title: href } : {} });
const normLabel = (s) => s.trim().replace(/\s+/g, " ").toLowerCase();

// `[label]: url` definitions, for `[text][label]` / `[label]` links. Built once per pass.
function references(cx) {
  if (cx.refs) return cx.refs;
  cx.refs = new Map();
  for (let n = syntaxTree(cx.state).topNode.firstChild; n; n = n.nextSibling) {
    if (n.name !== "LinkReference") continue;
    const label = n.getChild("LinkLabel");
    const url = n.getChild("URL");
    if (label && url) {
      cx.refs.set(normLabel(cx.doc.sliceString(label.from + 1, label.to - 1)), cx.doc.sliceString(url.from, url.to));
    }
  }
  return cx.refs;
}

const HEADING_LINE = Array.from({ length: 6 }, (_, i) => lineDeco(`pp-h pp-h${i + 1}`));
const SETEXT_UNDERLINE = lineDeco("pp-setext-underline");
const FM_LINE = lineDeco("pp-fm-line");
const CODE_LINE = lineDeco("pp-codeblock");
const CODE_FIRST = lineDeco("pp-codeblock pp-code-first");
const CODE_LAST = lineDeco("pp-codeblock pp-code-last");
const CODE_ONLY = lineDeco("pp-codeblock pp-code-first pp-code-last");
const FENCE_LINE = lineDeco("pp-fence-line");
const CODE_LANG = mark("pp-code-lang");
const QUOTE_LINE = [1, 2, 3].map((n) => lineDeco(`pp-quote pp-quote-${n}`));
const LIST_GLYPHS = ["\u2022", "\u25E6", "\u25AA"]; // bullet, white bullet, small square, repeating with depth
const LIST_NUM = mark("pp-list-num");
const TASK_DONE = mark("pp-task-done");
const numberPadded = (pad) => Decoration.mark({ class: "pp-list-num", attributes: { style: `margin-left:${pad}ch` } });
// A list line is pushed right by `--pp-hang` and its first line pulled back by the same amount, so
// wrapped lines sit under the item's text. The padding itself is in CSS (app.css), where it adds
// up with the quote bar's offset `--pp-qpad`, so a list inside a quote stays inside the bar.
const hangingIndent = (cols) =>
  Decoration.line({ class: "pp-li", attributes: { style: `--pp-hang:${cols}ch` } });
// How many characters of a line the quote marks (`> `) hide when the line is not being edited.
const quotePrefix = (text) => /^(?:>[ ]?)+/.exec(text)?.[0].length ?? 0;

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
      if (ordered) {
        // numbers of one list line up on their right edge (`9.` under `10.`) and so do the texts
        let widest = mark.to - mark.from;
        for (const sib of item.parent.getChildren("ListItem")) {
          const m = sib.getChild("ListMark");
          if (m) widest = Math.max(widest, m.to - m.from);
        }
        const pad = raw ? 0 : widest - (mark.to - mark.from);
        col += pad;
        cx.out.push((pad ? numberPadded(pad) : LIST_NUM).range(mark.from, mark.to));
      }
      else if (!box && !raw) {
        cx.out.push(Decoration.replace({ widget: new BulletWidget(LIST_GLYPHS[depth % LIST_GLYPHS.length]) }).range(mark.from, mark.to));
      }
    }
    const own = task ? [task] : item.getChildren("Paragraph");
    for (const r of own) {
      for (let n = cx.doc.lineAt(r.from).number; n <= cx.doc.lineAt(r.to).number; n++) {
        const line = cx.doc.line(n);
        // quote marks in front of the item are hidden (zero width) unless that line is being edited
        const hidden = cx.active.has(n) ? 0 : quotePrefix(line.text);
        cx.out.push(hangingIndent(Math.max(0, col - hidden)).range(line.from));
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

  // `[text](url)`, `[text][ref]`, `[ref]`: the text is styled as a link and carries its target (for
  // Ctrl/Cmd+click); `[` and `](url)` hide unless the link is being edited.
  Link: (cx, node) => {
    const n = node.node;
    const marks = n.getChildren("LinkMark");
    if (marks.length < 2) return;
    const [open, close] = marks;
    const url = n.getChild("URL");
    let href = url ? cx.doc.sliceString(url.from, url.to) : null;
    if (!url) {
      const label = n.getChild("LinkLabel");
      const inner = label ? cx.doc.sliceString(label.from + 1, label.to - 1) : "";
      href = references(cx).get(normLabel(inner || cx.doc.sliceString(open.to, close.from))) ?? null;
    }
    if (close.from > open.to) cx.out.push(linkDeco(href).range(open.to, close.from));
    if (touches(cx.state, node.from, node.to)) return;
    cx.out.push(hide.range(open.from, open.to));
    cx.out.push(hide.range(close.from, node.to));
  },

  // `[[note]]`, `[[note#head|alias]]`: shown as its display text; the brackets (and the target
  // part when there is an alias) hide unless the link is being edited. Ctrl/Cmd+click resolves it.
  WikiLink: (cx, node) => {
    const inner = cx.doc.sliceString(node.from + 2, node.to - 2);
    const target = parseWikilink(inner);
    if (!target) return;
    const bar = inner.indexOf("|");
    const shownFrom = bar < 0 ? node.from + 2 : node.from + 2 + bar + 1;
    const attributes = { "data-wiki-note": target.note, "data-wiki-heading": target.heading };
    const known = editorContext.known;
    const missing = known && target.note && !known.has(normNote(target.note));
    const cls = missing ? "pp-wikilink pp-wikilink-missing" : "pp-wikilink";
    cx.out.push(Decoration.mark({ class: cls, attributes }).range(shownFrom, node.to - 2));
    if (touches(cx.state, node.from, node.to)) return;
    cx.out.push(hide.range(node.from, shownFrom));
    cx.out.push(hide.range(node.to - 2, node.to));
  },

  // `<https://example.org>`
  Autolink: (cx, node) => {
    const url = node.node.getChild("URL");
    const marks = node.node.getChildren("LinkMark");
    if (!url || marks.length < 2) return;
    cx.out.push(linkDeco(cx.doc.sliceString(url.from, url.to)).range(url.from, url.to));
    if (touches(cx.state, node.from, node.to)) return;
    cx.out.push(hide.range(marks[0].from, marks[0].to));
    cx.out.push(hide.range(marks[marks.length - 1].from, marks[marks.length - 1].to));
  },

  // A bare `https://...` / `www....` in the text (the URL of a Link/Image is styled by its parent).
  URL: (cx, node) => {
    const parent = node.node.parent?.name;
    if (parent === "Link" || parent === "Image" || parent === "Autolink" || parent === "LinkReference") return;
    cx.out.push(linkDeco(cx.doc.sliceString(node.from, node.to)).range(node.from, node.to));
  },

  // `![alt|300](path)`: the picture, with the width taken from the `|300` in the alt text.
  Image: (cx, node) => {
    const n = node.node;
    const marks = n.getChildren("LinkMark");
    const url = n.getChild("URL");
    if (marks.length < 3 || !url || touches(cx.state, node.from, node.to)) return;
    const altRaw = cx.doc.sliceString(marks[0].to, marks[1].from);
    const sized = /^(.*?)\|\s*(\d+)\s*$/.exec(altRaw);
    const widget = new ImageWidget(cx.doc.sliceString(url.from, url.to), sized ? sized[1] : altRaw, sized ? Number(sized[2]) : null);
    cx.out.push(Decoration.replace({ widget }).range(node.from, node.to));
  },

  // ``` fenced code: every line is a code line; off-block the fence marks disappear and the
  // language shows as a small label. (A mermaid block that is drawn as a diagram is a widget.)
  FencedCode: (cx, node) => {
    const info = node.node.getChild("CodeInfo");
    const lang = info ? cx.doc.sliceString(info.from, info.to).trim() : "";
    const raw = touches(cx.state, node.from, node.to);
    if (lang === "mermaid" && !raw && node.node.getChild("CodeText")) return;
    const first = cx.doc.lineAt(node.from).number;
    const last = cx.doc.lineAt(node.to).number;
    for (let n = first; n <= last; n++) {
      const deco = first === last ? CODE_ONLY : n === first ? CODE_FIRST : n === last ? CODE_LAST : CODE_LINE;
      cx.out.push(deco.range(cx.doc.line(n).from));
    }
    if (raw) return;
    const marks = node.node.getChildren("CodeMark");
    if (marks.length) cx.out.push(hide.range(marks[0].from, marks[0].to));
    if (info) cx.out.push(CODE_LANG.range(info.from, info.to));
    else cx.out.push(FENCE_LINE.range(cx.doc.line(first).from));
    if (marks.length > 1 && cx.doc.lineAt(marks[marks.length - 1].from).number === last && last > first) {
      const m = marks[marks.length - 1];
      cx.out.push(hide.range(m.from, m.to));
      cx.out.push(FENCE_LINE.range(cx.doc.line(last).from));
    }
  },

  // Indented code: no syntax to hide, just the code look.
  CodeBlock: (cx, node) => {
    const first = cx.doc.lineAt(node.from).number;
    const last = cx.doc.lineAt(node.to).number;
    for (let n = first; n <= last; n++) {
      const deco = first === last ? CODE_ONLY : n === first ? CODE_FIRST : n === last ? CODE_LAST : CODE_LINE;
      cx.out.push(deco.range(cx.doc.line(n).from));
    }
  },

  // Front matter lines, as raw text (only visible while the caret is in the block; otherwise the
  // block widget covers them): dimmed so the metadata reads as metadata.
  FrontMatter: (cx, node) => {
    for (let n = cx.doc.lineAt(node.from).number; n <= cx.doc.lineAt(node.to).number; n++) {
      cx.out.push(FM_LINE.range(cx.doc.line(n).from));
    }
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
      const refresh = u.transactions.some((tr) => tr.effects.some((e) => e.is(refreshEffect)));
      if (refresh || u.docChanged || u.selectionSet || u.viewportChanged || syntaxTree(u.startState) !== syntaxTree(u.state)) {
        this.decorations = build(u.view);
      }
    }
  },
  { decorations: (v) => v.decorations },
);
