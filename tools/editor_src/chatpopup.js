// A small "Add to chat" button under the selected text (JS only captures; Python decides what to do).
// It stays hidden while the mouse button is held, so dragging a selection does not flicker.
import { StateEffect, StateField } from "@codemirror/state";
import { EditorView, showTooltip } from "@codemirror/view";

const dragging = StateEffect.define();
const dragState = StateField.define({
  create: () => false,
  update: (v, tr) => tr.effects.reduce((acc, e) => (e.is(dragging) ? e.value : acc), v),
});

export function chatPopup({ emit, getDocId }) {
  const tip = StateField.define({
    create: () => null,
    update(value, tr) {
      if (!tr.docChanged && !tr.selection && !tr.effects.length) return value;
      const sel = tr.state.selection.main;
      if (sel.empty || tr.state.selection.ranges.length !== 1 || tr.state.field(dragState)) return null;
      return {
        pos: sel.to,
        above: false,
        strictSide: false,
        class: "pp-chatpop-tooltip",
        create(view) {
          const dom = document.createElement("div");
          dom.className = "pp-chatpop";
          const btn = document.createElement("button");
          btn.type = "button";
          btn.textContent = "Add to chat";
          btn.addEventListener("mousedown", (e) => e.preventDefault()); // keep the selection
          btn.addEventListener("click", () => {
            const r = view.state.selection.main;
            if (r.empty) return;
            emit("add_to_chat", { docId: getDocId(), text: view.state.sliceDoc(r.from, r.to) });
            view.dispatch({ selection: { anchor: r.to } });
            view.focus();
          });
          dom.append(btn);
          return { dom };
        },
      };
    },
    provide: (f) => showTooltip.from(f),
  });
  return [
    dragState,
    tip,
    EditorView.domEventHandlers({
      mousedown: (e, view) => {
        if (e.button === 0) view.dispatch({ effects: dragging.of(true) });
        const up = () => {
          window.removeEventListener("mouseup", up, true);
          view.dispatch({ effects: dragging.of(false) });
        };
        window.addEventListener("mouseup", up, true);
        return false;
      },
    }),
  ];
}
