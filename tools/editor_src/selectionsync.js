// Tells the Ask box (selectpopup.js, through `onSettle`) that the selection has settled: at once when
// the mouse button is let go, else (keyboard, typing) once nothing changed for SETTLE_MS. Never while
// the mouse button is held. JS only reports; what to do with it is decided in Python.
import { EditorView } from "@codemirror/view";

const SETTLE_MS = 350;

export function selectionSync({ onSettle = () => {} } = {}) {
  let timer = null;
  let down = false;
  const report = (view, wait = SETTLE_MS) => {
    clearTimeout(timer);
    timer = setTimeout(() => {
      if (!down) onSettle(view);
    }, wait);
  };
  return [
    EditorView.updateListener.of((u) => {
      // a match the search panel selected is not the user choosing text
      if (u.transactions.some((tr) => tr.isUserEvent("select.search"))) return;
      if (u.selectionSet || u.docChanged) report(u.view);
    }),
    EditorView.domEventHandlers({
      mousedown: (e, view) => {
        down = true;
        const up = () => {
          window.removeEventListener("mouseup", up, true);
          down = false;
          report(view, 0); // the release ends the selection: no need to wait
        };
        window.addEventListener("mouseup", up, true);
        return false;
      },
    }),
  ];
}
