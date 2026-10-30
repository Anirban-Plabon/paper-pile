import { StateEffect } from "@codemirror/state";

// Dispatch this to make Live Preview rebuild its decorations without any text change (e.g. the
// note was renamed, so relative image URLs must be recomputed).
export const refreshEffect = StateEffect.define();

// What a selection range reveals: the caret, or a selection within one line; a selection over
// several lines reveals nothing, so everything it covers stays drawn (bullets, quotes, callouts,
// fences, images) — and nothing switches between drawn and raw while the mouse drags (an image
// turning into its source moved the whole note under the pointer).
function revealed(state, r) {
  if (r.empty || state.doc.lineAt(r.from).number === state.doc.lineAt(r.to).number) return [r.from, r.to];
  return null;
}

// "Does the selection touch this range?" decides when rendered markdown shows its raw syntax.
// Inclusive on both ends, so arrowing onto an element's edge reveals it.
export function touches(state, from, to) {
  for (const r of state.selection.ranges) {
    const shown = revealed(state, r);
    if (shown && shown[0] <= to && shown[1] >= from) return true;
  }
  return false;
}

// Line numbers that hold the caret or a one-line selection (for line prefixes like `#` or `>`).
export function activeLines(state) {
  const lines = new Set();
  for (const r of state.selection.ranges) {
    const shown = revealed(state, r);
    if (!shown) continue;
    const [from, to] = shown;
    const a = state.doc.lineAt(from).number;
    const b = state.doc.lineAt(to).number;
    for (let n = a; n <= b; n++) lines.add(n);
  }
  return lines;
}
