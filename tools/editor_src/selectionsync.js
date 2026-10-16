// Tells Python what is selected once the selection has settled (not while the mouse button is held),
// so the chat can attach it. JS only reports; what to do with it is decided in Python.
import { EditorView } from "@codemirror/view";

const SETTLE_MS = 350;
const MAX_CHARS = 50000;

export function selectionSync({ emit, getDocId }) {
  let timer = null;
  let down = false;
  let last = null;
  const report = (view) => {
    clearTimeout(timer);
    timer = setTimeout(() => {
      if (down) return;
      const r = view.state.selection.main;
      const text = r.empty || view.state.selection.ranges.length !== 1 ? "" : view.state.sliceDoc(r.from, r.to);
      const key = text.length > MAX_CHARS ? text.slice(0, MAX_CHARS) : text;
      if (key === last) return;
      last = key;
      emit("selection", { docId: getDocId(), text: key });
    }, SETTLE_MS);
  };
  return [
    EditorView.updateListener.of((u) => {
      if (u.selectionSet || u.docChanged) report(u.view);
    }),
    EditorView.domEventHandlers({
      mousedown: (e, view) => {
        down = true;
        const up = () => {
          window.removeEventListener("mouseup", up, true);
          down = false;
          report(view);
        };
        window.addEventListener("mouseup", up, true);
        return false;
      },
    }),
  ];
}
