// Where the Ask box goes (PLAN §4.27): once a selection settles (selectionsync.js calls
// `settlePopup`), the editor tells Python what is selected and where it is on screen; Python draws
// the box (gui/components/ask_popup.py, placed by static/askpop.js). While the box is open its text
// keeps a band behind its lines (`markTarget`, aiband.js: the same box as the diff's rows),
// pulsing while the AI works; it goes when the diff it led to is shown. Only while AI and the box
// are on (`aiPopup` option, index.js). JS only reports and draws.
import { StateEffect, StateField } from "@codemirror/state";
import { rtOf } from "./context.js";
import { bandLayer, snapToBlocks } from "./aiband.js";
import { proposalField } from "./proposal.js";

const setTarget = StateEffect.define(); // {from, to, busy} | null

const targetField = StateField.define({
  create: () => null,
  update(value, tr) {
    for (const e of tr.effects) if (e.is(setTarget)) return e.value;
    if (!value || !tr.docChanged) return value;
    const from = tr.changes.mapPos(value.from, 1);
    const to = tr.changes.mapPos(value.to, -1);
    return to > from ? { ...value, from, to } : null;
  },
  // a parked note (another tab) keeps its field: its tint counts only while its `token` is the
  // editor's current one, so a box closed meanwhile never comes back with that note
  // no band while the editor has the selection itself (it shows), nor once a diff is shown
  provide: (f) =>
    bandLayer(
      "pp-ai-band",
      (state, view) => {
        if (!askBandShown(view)) return [];
        const t = state.field(f);
        return [{ ...snapToBlocks(state, t.from, t.to), cls: t.busy ? "pp-ai-band-busy" : "" }];
      },
      (u) => u.startState.field(f) !== u.state.field(f) || u.startState.field(proposalField, false) !== u.state.field(proposalField, false),
    ),
});

// Is the Ask box's band drawn now? (Not while the editor itself shows the selection, nor once a
// diff is shown.) The selection layer (selectionband.js) stays empty while it is.
export function askBandShown(view) {
  const state = view.state;
  const t = state.field(targetField, false);
  if (!t || t.token !== (rtOf(state).askToken || 0) || state.field(proposalField, false)) return false;
  return t.busy || !view.hasFocus;
}

const reported = new WeakMap(); // view -> "from:to" of the selection last reported (null: none)

// The selection's place on screen (client pixels): the box goes under `bottom` at `left`, or above
// `top` when there is no room below. Several lines: the left edge of the text, not of the start.
function placeOf(view, r) {
  const line = view.state.doc.lineAt(r.from);
  const start = view.coordsAtPos(r.from, 1);
  const end = view.coordsAtPos(r.to, -1);
  const box = view.scrollDOM.getBoundingClientRect();
  const oneLine = start && end && Math.abs(start.top - end.top) < 2;
  const edge = oneLine ? start : view.coordsAtPos(line.from, 1);
  // a whole block the band covers (code, math, table, quote): the box goes under / over all of it
  const band = snapToBlocks(view.state, r.from, r.to);
  const grown = band.from !== r.from || band.to !== r.to;
  let top = (grown ? view.documentTop + view.lineBlockAt(band.from).top : start?.top) ?? box.top;
  let bottom = (grown ? view.documentTop + view.lineBlockAt(Math.max(band.from, band.to - 1)).bottom : end?.bottom) ?? box.bottom;
  // taller than the window: next to where the selection ended (the caret), not at a far edge
  if (top < box.top || bottom > box.bottom) {
    const head = view.coordsAtPos(r.head, r.head === r.from ? 1 : -1);
    if (head) ({ top, bottom } = head);
  }
  return { left: edge ? edge.left : box.left, top, bottom };
}

// The selection settled (or was cleared): tell Python where the box goes, or that it may go.
export function settlePopup(view) {
  if (view.state.field(targetField, false) === undefined) return; // the box is off
  const r = view.state.selection.main;
  const text = view.state.selection.ranges.length === 1 && !r.empty ? view.state.sliceDoc(r.from, r.to) : "";
  const key = text.trim() ? `${r.from}:${r.to}` : null;
  if (key === (reported.get(view) ?? null)) return;
  reported.set(view, key);
  const rt = rtOf(view.state);
  if (key === null) {
    rt.emit("selection_popup", { docId: rt.getDocId(), clear: true });
    return;
  }
  // askpop.js moves an unused box with this scroller when the note scrolls
  for (const el of document.querySelectorAll("[data-pp-ask-anchor]")) el.removeAttribute("data-pp-ask-anchor");
  view.scrollDOM.setAttribute("data-pp-ask-anchor", "");
  rt.emit("selection_popup", { docId: rt.getDocId(), from: r.from, to: r.to, text, rect: placeOf(view, r) });
}

// An AI command picked in the editor's own slash menu for a selection (Ctrl+J, right-click):
// select `from`..`to` again and open the box there with `command` already picked (Python).
export function askAbout(view, from, to, command) {
  if (view.state.field(targetField, false) === undefined) return false;
  view.dispatch({ selection: { anchor: from, head: to } });
  view.requestMeasure({
    read: () => placeOf(view, view.state.selection.main),
    write: (rect) => {
      const r = view.state.selection.main;
      reported.set(view, `${r.from}:${r.to}`); // the settle that follows is the same selection
      for (const el of document.querySelectorAll("[data-pp-ask-anchor]")) el.removeAttribute("data-pp-ask-anchor");
      view.scrollDOM.setAttribute("data-pp-ask-anchor", "");
      const rt = rtOf(view.state);
      rt.emit("selection_popup", { docId: rt.getDocId(), from: r.from, to: r.to, text: view.state.sliceDoc(r.from, r.to), rect, command });
    },
  });
  return true;
}

// A band behind `from`..`to` (busy: pulsing) while the box is about it; `from` null clears it
// (also in the notes parked in this editor).
export function markTarget(view, from, to, busy) {
  if (view.state.field(targetField, false) === undefined) return;
  const rt = rtOf(view.state);
  if (from === null) rt.askToken = (rt.askToken || 0) + 1;
  const len = view.state.doc.length;
  const value = from === null || to <= from || to > len ? null : { from, to, busy: !!busy, token: rt.askToken || 0 };
  // working on it: only the band shows the text, the selection goes (one highlight at a time)
  const collapse = value && value.busy && !view.state.selection.main.empty ? { selection: { anchor: to } } : {};
  view.dispatch({ effects: setTarget.of(value), ...collapse });
}

export const selectPopup = [targetField];
