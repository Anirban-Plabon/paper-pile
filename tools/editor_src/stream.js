// Text that arrives piece by piece (AI answers) is typed at a position that follows the document:
// if the user edits above it, the position moves with them. A stream belongs to one open note;
// switching notes stops it (append returns false).
import { isolateHistory } from "@codemirror/commands";
import { StateEffect, StateField } from "@codemirror/state";

const begin = StateEffect.define(); // {id, pos, docId}
const end = StateEffect.define(); // id

export const streamField = StateField.define({
  create: () => new Map(),
  update(map, tr) {
    let out = map;
    for (const e of tr.effects) {
      if (e.is(begin)) out = new Map(out).set(e.value.id, { pos: e.value.pos, docId: e.value.docId, started: false });
      else if (e.is(end)) {
        out = new Map(out);
        out.delete(e.value);
      }
    }
    if (tr.docChanged && out.size) {
      out = new Map([...out].map(([id, s]) => [id, { ...s, pos: tr.changes.mapPos(s.pos, 1) }]));
    }
    return out;
  },
});

export function streamBegin(view, id, pos, docId) {
  view.dispatch({ effects: begin.of({ id, pos: Math.min(pos, view.state.doc.length), docId }) });
}

// false: the stream is gone (another note is on screen, or it ended)
export function streamAppend(view, id, text, docId) {
  const s = view.state.field(streamField).get(id);
  if (!s || s.docId !== docId) return false;
  // the first piece starts a new undo step; the rest join it (history config in index.js)
  const first = !s.started;
  s.started = true;
  view.dispatch({
    changes: { from: s.pos, insert: text },
    userEvent: "input.type.ai",
    scrollIntoView: true,
    annotations: first ? isolateHistory.of("before") : [],
  });
  return true;
}

export function streamEnd(view, id) {
  // what the user types next must not join the answer's undo step
  view.dispatch({ effects: end.of(id), annotations: isolateHistory.of("after") });
}
