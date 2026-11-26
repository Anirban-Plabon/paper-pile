// Typing an opening ``` (or $$) at the start of a line writes the closing one too, with the caret
// after the opening mark so the language can be typed; Enter there steps into the empty body.
// Nothing is added when the fence being typed closes an open block.
import { Prec } from "@codemirror/state";
import { EditorView, keymap } from "@codemirror/view";
import { syntaxTree } from "@codemirror/language";

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

// ---- marks and brackets written in pairs (user 2026-11-26) ---------------------------------
// The rules are shared with the chat boxes and table cells: window.ppPairs (static/pairs.js).
// Here they get the note's syntax tree for "is this code" (marks are plain in code and maths).
const CODE = new Set(["InlineCode", "FencedCode", "CodeBlock", "CodeText", "InlineMath", "BlockMath", "HTMLBlock", "Comment"]);

function inCode(state, pos) {
  for (let node = syntaxTree(state).resolveInner(pos, -1); node; node = node.parent) if (CODE.has(node.name)) return true;
  return false;
}

// replace [from - back, to + fwd] with r.text, then select r.a..r.b in it
function apply(view, from, to, r, userEvent) {
  const start = from - r.back;
  view.dispatch({
    changes: { from: start, to: to + r.fwd, insert: r.text },
    selection: { anchor: start + r.a, head: start + r.b },
    userEvent,
    scrollIntoView: true,
  });
  return true;
}

const pairs = EditorView.inputHandler.of((view, from, to, text) => {
  const P = window.ppPairs;
  const { state } = view;
  if (!P || text.length !== 1 || state.selection.ranges.length > 1) return false;
  const a = state.doc.lineAt(from);
  const b = state.doc.lineAt(to);
  const r = P.typed(state.sliceDoc(a.from, from), state.sliceDoc(to, b.to), state.sliceDoc(from, to), text, text !== "`" && inCode(state, from));
  return r ? apply(view, from, to, r, "input.type") : false;
});

// Backspace between an empty pair removes both marks.
function deletePair(view) {
  const P = window.ppPairs;
  const { state } = view;
  const sel = state.selection.main;
  if (!P || !sel.empty || state.selection.ranges.length > 1) return false;
  const line = state.doc.lineAt(sel.from);
  const r = P.back(state.sliceDoc(line.from, sel.from), state.sliceDoc(sel.from, line.to));
  return r ? apply(view, sel.from, sel.from, r, "delete.backward") : false;
}

export const autoBrackets = [pairs, Prec.highest(keymap.of([{ key: "Backspace", run: deletePair }]))];
