// "Does the selection touch this range?" decides when rendered markdown shows its raw syntax.
// Inclusive on both ends, so arrowing onto an element's edge reveals it.
export function touches(state, from, to) {
  for (const r of state.selection.ranges) {
    if (r.from <= to && r.to >= from) return true;
  }
  return false;
}

// Line numbers that hold the caret or part of a selection (for line prefixes like `#` or `>`).
export function activeLines(state) {
  const lines = new Set();
  for (const r of state.selection.ranges) {
    const a = state.doc.lineAt(r.from).number;
    const b = state.doc.lineAt(r.to).number;
    for (let n = a; n <= b; n++) lines.add(n);
  }
  return lines;
}
