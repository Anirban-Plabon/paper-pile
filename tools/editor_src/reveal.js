import { StateEffect } from "@codemirror/state";

// Dispatch this to make Live Preview rebuild its decorations without any text change (e.g. the
// note was renamed, so relative image URLs must be recomputed).
export const refreshEffect = StateEffect.define();

// What a selection range reveals: itself within one line; across lines only its caret (the
// head), so selecting several blocks keeps them drawn (bullets, quotes, callouts, fences) instead
// of turning every line raw — the selection looks like what it covers.
function revealed(state, r) {
  if (r.empty || state.doc.lineAt(r.from).number === state.doc.lineAt(r.to).number) return [r.from, r.to];
  return [r.head, r.head];
}

// "Does the selection touch this range?" decides when rendered markdown shows its raw syntax.
// Inclusive on both ends, so arrowing onto an element's edge reveals it.
export function touches(state, from, to) {
  for (const r of state.selection.ranges) {
    const [a, b] = revealed(state, r);
    if (a <= to && b >= from) return true;
  }
  return false;
}

// Line numbers that hold the caret or a one-line selection (for line prefixes like `#` or `>`).
export function activeLines(state) {
  const lines = new Set();
  for (const r of state.selection.ranges) {
    const [from, to] = revealed(state, r);
    const a = state.doc.lineAt(from).number;
    const b = state.doc.lineAt(to).number;
    for (let n = a; n <= b; n++) lines.add(n);
  }
  return lines;
}
