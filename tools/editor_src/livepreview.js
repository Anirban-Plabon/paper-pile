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
import { editorContext, normNote, rtOf } from "./context.js";
import { pageViewFacet } from "./pageview.js";
import { parseWikilink } from "./wikilink.js";
import { activeLines, refreshEffect, touches } from "./reveal.js";
import { CodeCopyWidget } from "./blockactions.js";
import { FoldToggle, foldEffects, foldState } from "./fold.js";
import { BulletWidget, CalloutLabelWidget, CheckboxWidget, HrWidget, ImageWidget, MathWidget, PageBreakWidget } from "./widgets.js";

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
const PAGE_BREAK_RAW = lineDeco("pp-page-break-raw");
const CODE_LINE = lineDeco("pp-codeblock");
const CODE_FIRST = lineDeco("pp-codeblock pp-code-first");
const CODE_LAST = lineDeco("pp-codeblock pp-code-last");
const CODE_ONLY = lineDeco("pp-codeblock pp-code-first pp-code-last");
const FENCE_LINE = lineDeco("pp-fence-line");
const CODE_LANG = mark("pp-code-lang");
const CALLOUT_TYPES = {
  tip: "ok", success: "ok", done: "ok", hint: "ok",
  warning: "warn", caution: "warn", attention: "warn", important: "warn",
  danger: "bad", error: "bad", bug: "bad", failure: "bad",
};
const CALLOUT_KIND = { "": "pp-callout", ok: "pp-callout pp-callout-ok", warn: "pp-callout pp-callout-warn", bad: "pp-callout pp-callout-bad" };
const CALLOUT_EDGE = ["", " pp-callout-first", " pp-callout-last", " pp-callout-first pp-callout-last"];
const calloutLines = new Map();
const calloutLine = (kind, edge) => {
  const key = `${kind}:${edge}`;
  if (!calloutLines.has(key)) calloutLines.set(key, lineDeco(CALLOUT_KIND[kind] + CALLOUT_EDGE[edge]));
  return calloutLines.get(key);
};
const CALLOUT_HEADER = /^(\s*>\s*)(\[!([A-Za-z][\w-]*)\][-+]?)[ \t]*(.*)$/;

// `> [!note]` / `> [!tip]- Title` on a quote's first line: returns [, type] like the bold-label
// match, and draws the header (unless the caret is on it).
function calloutHeader(cx, line) {
  const m = CALLOUT_HEADER.exec(line.text);
  if (!m) return null;
  const from = line.from + m[1].length;
  (cx.calloutHeads ??= new Set()).add(from);
  if (!cx.active.has(line.number)) {
    const type = m[3];
    const title = m[4].trim();
    const to = line.to - m[4].length;
    if (title) {
      cx.out.push(hide.range(from, to));
      cx.out.push(INLINE_DECO.StrongEmphasis.range(to, line.to));
    } else {
      const label = type[0].toUpperCase() + type.slice(1).toLowerCase();
      cx.out.push(Decoration.replace({ widget: new CalloutLabelWidget(label) }).range(from, line.to));
    }
  }
  return [null, m[3]];
}

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
const continuationIndent = (cols, lead) =>
  Decoration.line({ class: "pp-li", attributes: { style: `--pp-hang:${cols}ch;--pp-pull:${Math.min(cols, lead)}ch` } });
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
        const fold = foldState(cx.state, line);
        if (fold) {
          cx.out.push(Decoration.widget({ widget: new FoldToggle(line.from, fold.folded), side: -1 }).range(line.from));
        }
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
        const hang = Math.max(0, col - hidden);
        // a continuation line (also a "lazy" one written without indentation) sits under the
        // item's text: only its own leading spaces are pulled back, not the whole hang
        const prefix = quotePrefix(line.text);
        const lead = prefix - hidden + /^[ \t]*/.exec(line.text.slice(prefix))[0].length;
        cx.out.push((n === first.number ? hangingIndent(hang) : continuationIndent(hang, lead)).range(line.from));
      }
    }
  },

  // A quote that opens with a bold label (`> **Note:** ...`, what /callout inserts) is a callout:
  // the box is tinted in the theme colour; the text is untouched. An Obsidian/GitHub header
  // (`> [!note]`, `> [!tip]- Title`) makes the same callout: off the caret's line its `[!note]`
  // shows as the bold `Note:` label (or hides before a title, which turns bold).
  // Every line of a quote gets its bars, also a "lazy" line written without `>`: markdown keeps a
  // line that follows quoted text in the quote, so it must not look like it is outside.
  Blockquote: (cx, node) => {
    let level = 1;
    for (let a = node.node.parent; a; a = a.parent) if (a.name === "Blockquote") level++;
    const end = cx.doc.lineAt(node.to).number;
    for (let n = cx.doc.lineAt(node.from).number; n <= end; n++) {
      cx.quoteDepth.set(n, Math.max(cx.quoteDepth.get(n) ?? 0, level));
    }
    if (level > 1) return;
    const first = cx.doc.lineAt(node.from);
    const label = /^\s*>\s*\*\*([^*\n]+?):?\*\*/.exec(first.text) ?? calloutHeader(cx, first);
    if (!label) return;
    const kind = CALLOUT_TYPES[label[1].trim().toLowerCase()] ?? "";
    const last = cx.doc.lineAt(node.to).number;
    for (let n = first.number; n <= last; n++) {
      const edge = (n === first.number ? 1 : 0) + (n === last ? 2 : 0); // a card: rounded ends
      cx.out.push(calloutLine(kind, edge).range(cx.doc.line(n).from));
    }
  },

  // `>` quote markers: hidden off-line (the bars come from the Blockquote handler).
  QuoteMark: (cx, node) => {
    const line = cx.doc.lineAt(node.from);
    if (cx.active.has(line.number)) return;
    const space = cx.doc.sliceString(node.to, node.to + 1) === " " ? 1 : 0;
    cx.out.push(hide.range(node.from, node.to + space));
  },

  // `---` / `***` / `___`: a drawn rule off-line.
  HorizontalRule: (cx, node) => {
    if (cx.active.has(cx.doc.lineAt(node.from).number)) return;
    cx.out.push(Decoration.replace({ widget: new HrWidget() }).range(node.from, node.to));
  },

  // A manual page break: the drawn line off-line, the raw (dimmed) `<div …>` on the caret's line.
  PageBreak: (cx, node) => {
    if (cx.state.facet(pageViewFacet)) return; // page view hides the whole line (pageview.js)
    const line = cx.doc.lineAt(node.from);
    if (cx.active.has(line.number)) cx.out.push(PAGE_BREAK_RAW.range(line.from));
    else cx.out.push(Decoration.replace({ widget: new PageBreakWidget() }).range(node.from, node.to));
  },

  // `[text](url)`, `[text][ref]`, `[ref]`: the text is styled as a link and carries its target (for
  // Ctrl/Cmd+click); `[` and `](url)` hide unless the link is being edited.
  Link: (cx, node) => {
    const n = node.node;
    const marks = n.getChildren("LinkMark");
    if (marks.length < 2 || cx.calloutHeads?.has(node.from)) return; // `[!note]` is not a link
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
    const editing = touches(cx.state, node.from, node.to);
    // a link that is not being edited opens its note on a plain click (like a link on a web page)
    if (!editing) attributes["data-wiki-open"] = "1";
    cx.out.push(Decoration.mark({ class: cls, attributes }).range(shownFrom, node.to - 2));
    if (editing) return;
    cx.out.push(hide.range(node.from, shownFrom));
    cx.out.push(hide.range(node.to - 2, node.to));
  },

  // `#tag`: a chip; a plain click opens the tag's list (Python), unless the tag is being edited
  HashTag: (cx, node) => {
    const tag = cx.doc.sliceString(node.from + 1, node.to);
    const editing = touches(cx.state, node.from, node.to);
    const attributes = { "data-tag": tag };
    if (!editing) attributes["data-tag-open"] = "1";
    cx.out.push(Decoration.mark({ class: editing ? "pp-tag pp-tag-edit" : "pp-tag", attributes }).range(node.from, node.to));
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
    const widget = new ImageWidget(cx.doc.sliceString(url.from, url.to), sized ? sized[1] : altRaw, sized ? Number(sized[2]) : null, rtOf(cx.state).notePath);
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
    const code = node.node.getChild("CodeText");
    if (code) {
      const text = cx.doc.sliceString(code.from, code.to);
      const widget = new CodeCopyWidget(lang === "mermaid" ? "diagram" : "code", lang, text);
      cx.out.push(Decoration.widget({ widget, side: -1 }).range(cx.doc.line(first).from));
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
      const refresh = u.transactions.some((tr) =>
        tr.effects.some((e) => e.is(refreshEffect) || e.is(foldEffects.foldEffect) || e.is(foldEffects.unfoldEffect)),
      );
      if (refresh || u.docChanged || u.startState.facet(pageViewFacet) !== u.state.facet(pageViewFacet) || u.selectionSet || u.viewportChanged || syntaxTree(u.startState) !== syntaxTree(u.state)) {
        this.decorations = build(u.view);
      }
    }
  },
  { decorations: (v) => v.decorations },
);
