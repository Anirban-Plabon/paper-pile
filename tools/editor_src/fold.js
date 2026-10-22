// Fold a heading's section (everything under it up to the next heading of the same or a higher
// level). A small chevron in the margin of every heading line toggles it. Render/capture only.
import { codeFolding, foldEffect, foldedRanges, syntaxTree, unfoldEffect } from "@codemirror/language";
import { foldService } from "@codemirror/language";
import { WidgetType } from "@codemirror/view";

const level = (state, line) => {
  const m = /^(#{1,6})[ \t]+\S/.exec(line.text);
  if (!m) return 0;
  const node = syntaxTree(state).resolveInner(line.from + 1, 1);
  const name = node.name === "HeaderMark" ? node.parent?.name : node.name;
  return name && name.startsWith("ATXHeading") ? m[1].length : 0; // not inside a code block
};

// The section under the heading on `line`: from the end of the heading line to the end of the
// last non-blank line before the next heading of the same or a higher level.
export function sectionRange(state, line) {
  const lvl = level(state, line);
  if (!lvl) return null;
  const { doc } = state;
  let last = line;
  for (let n = line.number + 1; n <= doc.lines; n++) {
    const l = doc.line(n);
    const other = level(state, l);
    if (other && other <= lvl) break;
    if (l.text.trim()) last = l;
  }
  return last.number > line.number ? { from: line.to, to: last.to } : null;
}

export const headingFolding = [
  codeFolding({
    placeholderDOM: (view, onclick) => {
      const el = document.createElement("span");
      el.className = "pp-fold-placeholder";
      el.textContent = "…";
      el.dataset.tip = "Unfold";
      el.addEventListener("click", onclick);
      return el;
    },
  }),
  foldService.of((state, from) => sectionRange(state, state.doc.lineAt(from))),
];

const isFolded = (state, range) => {
  let found = false;
  foldedRanges(state).between(range.from, range.from, (a, b) => {
    if (a === range.from && b === range.to) found = true;
  });
  return found;
};

export class FoldToggle extends WidgetType {
  constructor(lineFrom, folded) {
    super();
    this.lineFrom = lineFrom;
    this.folded = folded;
  }
  eq(other) {
    return other.lineFrom === this.lineFrom && other.folded === this.folded;
  }
  toDOM(view) {
    const el = document.createElement("span");
    el.className = "pp-fold" + (this.folded ? " pp-fold-folded" : "");
    el.setAttribute("aria-hidden", "true"); // drawn by CSS, so it is not part of the line text
    el.dataset.tip = this.folded ? "Unfold" : "Fold";
    el.addEventListener("mousedown", (e) => {
      e.preventDefault();
      e.stopPropagation();
      const line = view.state.doc.lineAt(this.lineFrom);
      const range = sectionRange(view.state, line);
      if (!range) return;
      view.dispatch({ effects: (isFolded(view.state, range) ? unfoldEffect : foldEffect).of(range) });
    });
    return el;
  }
  ignoreEvent() {
    return true;
  }
}

// Does the heading on `line` have a section, and is it folded now?
export function foldState(state, line) {
  const range = sectionRange(state, line);
  return range ? { range, folded: isFolded(state, range) } : null;
}

export const foldEffects = { foldEffect, unfoldEffect };
