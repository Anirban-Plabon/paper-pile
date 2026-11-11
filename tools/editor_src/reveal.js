import { StateEffect, StateField } from "@codemirror/state";
import { EditorView } from "@codemirror/view";

// Dispatch this to make Live Preview rebuild its decorations without any text change (e.g. the
// note was renamed, so relative image URLs must be recomputed).
export const refreshEffect = StateEffect.define();

// While the mouse clicks (a click, a double or triple click) the raw syntax stays as it was before
// the first click: revealing it at once moved the text under the pointer, so a double-click on a
// **bold** word landed on the `**` that had just appeared and selected that instead of the word.
// The reveal catches up ~0.4 s after the last click, or at once on a key or any edit.
const CLICK_GAP_MS = 400; // longer than the double-click interval the browser uses between clicks
const holdReveal = StateEffect.define(); // the selection to reveal from, or null: the real one
const holdField = StateField.define({
  create: () => null,
  update(value, tr) {
    for (const e of tr.effects) if (e.is(holdReveal)) return e.value;
    if (value && (tr.docChanged || (tr.selection && !tr.isUserEvent("select.pointer")))) return null;
    return value;
  },
});
export const isHoldChange = (tr) => tr.effects.some((e) => e.is(holdReveal));
const timers = new WeakMap();
const clickHold = EditorView.domEventHandlers({
  mousedown(e, view) {
    if (e.button !== 0 || e.shiftKey) return false;
    clearTimeout(timers.get(view));
    if (!view.state.field(holdField)) view.dispatch({ effects: holdReveal.of(view.state.selection) });
    const up = () => {
      window.removeEventListener("mouseup", up, true);
      timers.set(view, setTimeout(() => {
        if (view.state.field(holdField, false)) view.dispatch({ effects: holdReveal.of(null) });
      }, CLICK_GAP_MS));
    };
    window.addEventListener("mouseup", up, true);
    return false;
  },
});
export const revealHold = [holdField, clickHold];

const rangesOf = (state) => (state.field(holdField, false) ?? state.selection).ranges;

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
  for (const r of rangesOf(state)) {
    const shown = revealed(state, r);
    if (shown && shown[0] <= to && shown[1] >= from) return true;
  }
  return false;
}

// Line numbers that hold the caret or a one-line selection (for line prefixes like `#` or `>`).
export function activeLines(state) {
  const lines = new Set();
  for (const r of rangesOf(state)) {
    const shown = revealed(state, r);
    if (!shown) continue;
    const [from, to] = shown;
    const a = state.doc.lineAt(from).number;
    const b = state.doc.lineAt(to).number;
    for (let n = a; n <= b; n++) lines.add(n);
  }
  return lines;
}
