// Typing an opening ``` (or $$) at the start of a line writes the closing one too, with the caret
// after the opening mark so the language can be typed; Enter there steps into the empty body.
// Nothing is added when the fence being typed closes an open block.
import { Prec } from "@codemirror/state";
import { EditorView, keymap } from "@codemirror/view";

const PAIRS = [
  { ch: "`", open: "``", mark: "```", line: /^\s*```/ },
  { ch: "$", open: "$", mark: "$$", line: /^\s*\$\$\s*$/ },
];

// is the position inside an open fenced block (an odd number of fence lines above)?
function insideOpen(doc, lineNo, re) {
  let count = 0;
  for (let n = 1; n < lineNo; n++) if (re.test(doc.line(n).text)) count++;
  return count % 2 === 1;
}

const typed = EditorView.inputHandler.of((view, from, to, text) => {
  if (from !== to) return false;
  const pair = PAIRS.find((p) => p.ch === text);
  if (!pair) return false;
  const { doc } = view.state;
  const line = doc.lineAt(from);
  const indent = /^\s*/.exec(line.text)[0];
  if (doc.sliceString(line.from, from) !== indent + pair.open || from !== line.to) return false;
  if (insideOpen(doc, line.number, pair.line)) return false;
  const insert = `${text}\n${indent}\n${indent}${pair.mark}`;
  view.dispatch({ changes: { from, insert }, selection: { anchor: from + 1 }, userEvent: "input.type", scrollIntoView: true });
  return true;
});

// Enter on `<fence>lang` whose body is empty and closed right below: just go into the body.
function stepIn(view) {
  const { state } = view;
  const sel = state.selection.main;
  if (!sel.empty) return false;
  const line = state.doc.lineAt(sel.from);
  if (sel.from !== line.to || line.number + 2 > state.doc.lines) return false;
  const open = /^(\s*)(```|\$\$)\S*$/.exec(line.text);
  if (!open) return false;
  const body = state.doc.line(line.number + 1);
  const close = state.doc.line(line.number + 2);
  if (body.text.trim() !== "" || close.text.trim() !== open[2]) return false;
  view.dispatch({ selection: { anchor: body.to }, scrollIntoView: true });
  return true;
}

export const autoClose = [typed, Prec.highest(keymap.of([{ key: "Enter", run: stepIn }]))];

// ---- brackets: ( [ { are written in pairs ---------------------------------------------------
const CLOSER = { "(": ")", "[": "]", "{": "}" };
const CLOSERS = new Set(Object.values(CLOSER));

const unmatched = (before, open, close) => {
  let depth = 0;
  for (const ch of before) {
    if (ch === open) depth++;
    else if (ch === close && depth > 0) depth--;
  }
  return depth;
};

const brackets = EditorView.inputHandler.of((view, from, to, text) => {
  if (from !== to || text.length !== 1) return false;
  const { doc } = view.state;
  const line = doc.lineAt(from);
  const next = doc.sliceString(from, Math.min(from + 1, line.to));
  if (CLOSER[text] && (next === "" || /\s/.test(next) || CLOSERS.has(next))) {
    view.dispatch({ changes: { from, insert: text + CLOSER[text] }, selection: { anchor: from + 1 }, userEvent: "input.type" });
    return true;
  }
  if (CLOSERS.has(text) && next === text) {
    const open = Object.keys(CLOSER).find((k) => CLOSER[k] === text);
    if (unmatched(doc.sliceString(line.from, from), open, text) > 0) {
      view.dispatch({ selection: { anchor: from + 1 }, userEvent: "input.type" });
      return true;
    }
  }
  return false;
});

// Backspace between an empty pair removes both marks.
function deletePair(view) {
  const { state } = view;
  const sel = state.selection.main;
  if (!sel.empty || sel.from === 0) return false;
  const before = state.sliceDoc(sel.from - 1, sel.from);
  if (CLOSER[before] && state.sliceDoc(sel.from, sel.from + 1) === CLOSER[before]) {
    view.dispatch({ changes: { from: sel.from - 1, to: sel.from + 1 }, userEvent: "delete.backward" });
    return true;
  }
  return false;
}

export const autoBrackets = [brackets, Prec.highest(keymap.of([{ key: "Backspace", run: deletePair }]))];
