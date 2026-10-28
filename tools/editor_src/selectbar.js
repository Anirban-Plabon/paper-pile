// A small bar above a selection (PLAN §4.26): "Ask" attaches it to the chat, "Edit" opens a one-line
// prompt here and the AI's version comes back as a diff (proposal.js). Shown once the selection has
// settled (selectionsync.js calls `settleBar`), only while AI is on (`aiBar` option, index.js).
// JS only reports: Python decides what Ask and Edit do.
import { StateEffect, StateField } from "@codemirror/state";
import { showTooltip } from "@codemirror/view";
import { rtOf } from "./context.js";

const setBar = StateEffect.define(); // {from, to} | null

const barField = StateField.define({
  create: () => null,
  update(value, tr) {
    for (const e of tr.effects) if (e.is(setBar)) return e.value;
    if (!value) return value;
    const r = tr.state.selection.main;
    if (tr.selection && (r.empty || r.from !== tr.changes.mapPos(value.from) || r.to !== tr.changes.mapPos(value.to))) {
      return null; // the selection moved on: hidden until it settles again
    }
    return tr.docChanged ? { from: tr.changes.mapPos(value.from), to: tr.changes.mapPos(value.to) } : value;
  },
  provide: (f) =>
    showTooltip.compute([f], (state) => {
      const bar = state.field(f);
      return bar ? { pos: bar.from, above: true, strictSide: false, arrow: false, create: (view) => barDom(view, bar) } : null;
    }),
});

const report = (view, bar, action, instruction = "") => {
  const rt = rtOf(view.state);
  rt.emit("selection_action", {
    docId: rt.getDocId(),
    action,
    from: bar.from,
    to: bar.to,
    text: view.state.sliceDoc(bar.from, bar.to),
    instruction,
  });
};

function barDom(view, bar) {
  const dom = document.createElement("div");
  dom.className = "pp-selbar";
  const button = (label, onClick) => {
    const b = document.createElement("button");
    b.type = "button";
    b.className = "pp-selbar-btn";
    b.textContent = label;
    b.addEventListener("mousedown", (e) => e.preventDefault()); // keep the selection
    b.addEventListener("click", onClick);
    return b;
  };
  const close = () => view.dispatch({ effects: setBar.of(null) });
  const ask = button("Ask", () => {
    report(view, bar, "ask");
    close();
  });
  const edit = button("Edit", () => {
    dom.replaceChildren(input);
    input.focus();
  });
  const input = document.createElement("input");
  input.className = "pp-selbar-input";
  input.placeholder = "Change it how? e.g. shorter, more formal";
  input.addEventListener("keydown", (e) => {
    e.stopPropagation();
    if (e.key === "Enter" && input.value.trim()) {
      report(view, bar, "edit", input.value.trim());
      close();
      view.focus();
    } else if (e.key === "Escape") {
      close();
      view.focus();
    }
  });
  dom.append(ask, edit);
  return { dom };
}

// The selection settled (or was cleared): show the bar over it, or hide it.
export function settleBar(view) {
  const now = view.state.field(barField, false);
  if (now === undefined) return; // AI is off: no bar in this editor
  const r = view.state.selection.main;
  const one = view.state.selection.ranges.length === 1 && !r.empty;
  const bar = one && view.state.sliceDoc(r.from, r.to).trim() ? { from: r.from, to: r.to } : null;
  if (bar === null && now === null) return;
  if (bar && now && bar.from === now.from && bar.to === now.to) return;
  view.dispatch({ effects: setBar.of(bar) });
}

export const selectBar = [barField];
