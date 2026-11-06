// The lines a chat citation points at (PLAN_vault_agent §7.1, P30.46): after the jump's flash, a
// soft see-through band stays on the cited lines until the next click or key. A layer over the
// text like the AI bands (aiband.js) — never marks in the text; it maps through edits.
import { StateEffect, StateField } from "@codemirror/state";
import { EditorView } from "@codemirror/view";
import { bandLayer } from "./aiband.js";

export const setCiteBand = StateEffect.define();

export const citeBandField = StateField.define({
  create: () => null,
  update(band, tr) {
    for (const e of tr.effects) if (e.is(setCiteBand)) return e.value;
    if (!band) return band;
    // the user moves on (a click or a key moves the caret, or types): the band goes. Read from
    // the transaction, not DOM events: another extension may handle a mousedown first.
    if (tr.isUserEvent("select") || tr.isUserEvent("input") || tr.isUserEvent("delete")) return null;
    if (!tr.docChanged) return band;
    const from = tr.changes.mapPos(band.from, 1);
    const to = tr.changes.mapPos(band.to, -1);
    return to > from ? { from, to } : null;
  },
});

const citeBandLayer = bandLayer(
  "pp-cite-band",
  (state) => {
    const band = state.field(citeBandField, false);
    return band ? [band] : [];
  },
  (u) => u.startState.field(citeBandField, false) !== u.state.field(citeBandField, false),
);

function clear(view) {
  if (view.state.field(citeBandField, false)) view.dispatch({ effects: setCiteBand.of(null) });
  return false;
}

// Lines `first`..`last` (1-based, clamped) get the band; null clears it.
export function showCiteBand(view, first, last) {
  const doc = view.state.doc;
  const a = doc.line(Math.max(1, Math.min(first, doc.lines)));
  const b = doc.line(Math.max(a.number, Math.min(last, doc.lines)));
  view.dispatch({ effects: setCiteBand.of({ from: a.from, to: b.to }) });
}

export const citeBand = [
  citeBandField,
  citeBandLayer,
  EditorView.domEventHandlers({ mousedown: clear, keydown: clear }),
];
