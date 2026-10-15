// Keyboard behaviour for lists and quotes while writing (Enter, Tab, Shift+Tab, typing a marker).
//
//  * Enter continues a list/quote as a TIGHT list (never inserts blank lines between items); on an
//    empty item it steps out: a nested item moves out one level, a top-level item loses its marker,
//    an empty quote line leaves one quote level. So a list, a callout or a quote can always be
//    escaped by pressing Enter on the empty line.
//  * Tab / Shift+Tab nest and un-nest an item (and the items under it) to exactly the column that
//    makes it a child of the item above, also inside quotes (the indentation goes AFTER the `> `).
//  * A list marker typed right after a list marker (`- -`) is written as an escaped character
//    (`- \-`): a second marker never makes a nested list by accident.
import { insertNewlineContinueMarkupCommand, deleteMarkupBackward } from "@codemirror/lang-markdown";
import { Prec } from "@codemirror/state";
import { EditorView, keymap } from "@codemirror/view";

const LINE = /^((?:[ \t]*>[ \t]?)*)([ \t]*)(?:([-*+]|\d{1,9}[.)])([ \t]+)(\[[ xX]\][ \t]+)?)?([\s\S]*)$/;
const EMPTY_ITEM = /^(?:[ \t]*>[ \t]?)*[ \t]*(?:[-*+]|\d{1,9}[.)])[ \t]+(?:\[[ xX]\][ \t]+)?$/;

function parse(text) {
  const m = LINE.exec(text);
  return { quote: m[1], indent: m[2].length, marker: m[3] || "", gap: m[4] || "", task: m[5] || "", rest: m[6] };
}

const single = (state) => state.selection.ranges.length === 1 && state.selection.main.empty;

// the nearest list line above `line` in the same quote that sits (`strict`: strictly) left of `indent`
function referenceItem(doc, line, info, strict) {
  for (let n = line.number - 1; n >= 1; n--) {
    const p = parse(doc.line(n).text);
    if (p.quote !== info.quote) return null;
    if (p.marker && (strict ? p.indent < info.indent : p.indent <= info.indent)) return p;
  }
  return null;
}

function replaceLine(view, line, text) {
  view.dispatch({
    changes: { from: line.from, to: line.to, insert: text },
    selection: { anchor: line.from + text.length },
    userEvent: "input",
    scrollIntoView: true,
  });
  return true;
}

// CodeMirror's own command adds blank lines between items once any blank line exists in the list;
// we continue lists ourselves so a list stays tight, and leave odd cases to the library command.
const continueMarkup = insertNewlineContinueMarkupCommand({ nonTightLists: false });

function nextMarker(marker) {
  const m = /^(\d+)([.)])$/.exec(marker);
  return m ? `${Number(m[1]) + 1}${m[2]}` : marker;
}

function continueItem(view) {
  const { state } = view;
  if (!single(state)) return false;
  const head = state.selection.main.head;
  const line = state.doc.lineAt(head);
  const info = parse(line.text);
  if (!info.marker && !info.quote) return false;
  const markup = info.quote.length + info.indent + info.marker.length + info.gap.length + info.task.length;
  if (head - line.from < markup) return false; // the caret is inside the markup: library behaviour
  let prefix = info.quote.replace(/>[ \t]*$/, "> ") + " ".repeat(info.indent);
  if (info.marker) prefix += nextMarker(info.marker) + (info.gap || " ") + (info.task ? "[ ] " : "");
  let from = head;
  while (from > line.from && /[ \t]/.test(state.sliceDoc(from - 1, from))) from--;
  const insert = `\n${prefix}`;
  view.dispatch({
    changes: { from, to: head, insert },
    selection: { anchor: from + insert.length },
    userEvent: "input",
    scrollIntoView: true,
  });
  return true;
}

function enter(view) {
  const { state } = view;
  if (!single(state)) return false;
  const line = state.doc.lineAt(state.selection.main.head);
  if (state.selection.main.head !== line.to) return false;
  const info = parse(line.text);
  if (info.rest.trim() !== "") return false;
  if (info.marker) {
    if (info.indent > 0) {
      const parent = referenceItem(state.doc, line, info, true);
      const indent = parent ? parent.indent : 0;
      return replaceLine(view, line, info.quote + " ".repeat(indent) + info.marker + info.gap + info.task);
    }
    return replaceLine(view, line, info.quote); // top-level item: the marker goes, the quote stays
  }
  if (info.quote) return replaceLine(view, line, info.quote.replace(/[ \t]*>[ \t]?$/, "")); // leave a quote level
  return false;
}

// move the item on the caret's line, and everything nested under it, to a new indentation
function reindent(view, direction) {
  const { state } = view;
  if (!single(state)) return false;
  const doc = state.doc;
  const line = doc.lineAt(state.selection.main.head);
  const info = parse(line.text);
  if (!info.marker) {
    if (direction > 0 && info.quote) {
      view.dispatch(state.replaceSelection("  ")); // indent quoted text after the `> `, not before it
      return true;
    }
    return false;
  }
  const ref = referenceItem(doc, line, info, direction < 0);
  let target;
  if (direction > 0) {
    if (!ref) return true; // the first item of a list cannot be nested
    target = ref.indent + ref.marker.length + ref.gap.length;
    if (target <= info.indent) target = info.indent + 2;
  } else {
    if (info.indent === 0) return true;
    target = ref ? ref.indent : 0;
  }
  const delta = target - info.indent;
  const changes = [];
  for (let n = line.number; n <= doc.lines; n++) {
    const l = doc.line(n);
    const p = parse(l.text);
    if (n > line.number) {
      if (p.quote !== info.quote || (p.marker && p.indent <= info.indent)) break;
      if (!p.marker && p.rest.trim() !== "" && p.indent <= info.indent) break; // not part of the item
    }
    if (l.text.trim() === "" || p.quote !== info.quote) continue;
    const at = l.from + p.quote.length;
    if (delta > 0) changes.push({ from: at, insert: " ".repeat(delta) });
    else changes.push({ from: at, to: at + Math.min(-delta, p.indent) });
  }
  if (changes.length) view.dispatch({ changes, userEvent: "input", scrollIntoView: true });
  return true;
}

// `- ` then `-`: the second marker is just a character
const secondMarker = EditorView.inputHandler.of((view, from, to, text) => {
  if (from !== to || !/^[-*+]$/.test(text)) return false;
  const line = view.state.doc.lineAt(from);
  if (!EMPTY_ITEM.test(view.state.sliceDoc(line.from, from))) return false;
  view.dispatch({ changes: { from, insert: `\\${text}` }, selection: { anchor: from + 2 }, userEvent: "input.type" });
  return true;
});

export const listEditing = [
  secondMarker,
  Prec.high(
    keymap.of([
      { key: "Enter", run: (view) => enter(view) || continueItem(view) || continueMarkup(view) },
      { key: "Tab", run: (view) => reindent(view, 1) },
      { key: "Shift-Tab", run: (view) => reindent(view, -1) },
      { key: "Backspace", run: deleteMarkupBackward },
    ]),
  ),
];
