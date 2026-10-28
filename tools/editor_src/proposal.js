// An AI edit shown as a diff for the user to approve (PLAN §4.26): the lines it would remove get
// a light red background and a "−", the lines it would add are drawn below them in light green
// with a "+", each change with Accept / Reject, and a bar on top with Accept all / Reject all.
// Nothing here changes the note: a click is reported to Python, which applies the change (one
// undo step) and sends what is left of the proposal, or clears it. Positions follow typing.
import { StateEffect, StateField } from "@codemirror/state";
import { Decoration, EditorView, WidgetType, showPanel } from "@codemirror/view";
import { rtOf } from "./context.js";

const setProposal = StateEffect.define(); // {id, docId, hunks: [{id, from, to, insert}]} | null

export const proposalField = StateField.define({
  create: () => null,
  update(value, tr) {
    for (const e of tr.effects) if (e.is(setProposal)) value = e.value;
    if (value && tr.docChanged) {
      const hunks = value.hunks.map((h) => ({
        ...h,
        from: tr.changes.mapPos(h.from, -1),
        to: tr.changes.mapPos(h.to, 1),
      }));
      value = { ...value, hunks };
    }
    return value;
  },
  provide: (f) => showPanel.from(f, (p) => (p ? barPanel : null)),
});

const report = (view, action, hunk = null) => {
  const p = view.state.field(proposalField);
  if (p) rtOf(view.state).emit("proposal", { docId: p.docId, proposal: p.id, hunk, action });
};

const button = (label, cls, onClick) => {
  const b = document.createElement("button");
  b.type = "button";
  b.className = `pp-aidiff-btn ${cls}`;
  b.textContent = label;
  b.addEventListener("mousedown", (e) => e.preventDefault()); // keep the caret where it is
  b.addEventListener("click", onClick);
  return b;
};

class AddedLines extends WidgetType {
  constructor(hunk) {
    super();
    this.hunk = hunk;
  }
  eq(other) {
    return other.hunk.id === this.hunk.id && other.hunk.insert === this.hunk.insert;
  }
  toDOM(view) {
    const box = document.createElement("div");
    box.className = "pp-aidiff-block";
    const text = this.hunk.insert.replace(/\n$/, "");
    if (this.hunk.insert) {
      for (const line of text.split("\n")) {
        const row = document.createElement("div");
        row.className = "pp-aidiff-add";
        row.textContent = line || " ";
        box.appendChild(row);
      }
    }
    const actions = document.createElement("div");
    actions.className = "pp-aidiff-actions";
    actions.append(
      button("Accept", "pp-aidiff-accept", () => report(view, "accept", this.hunk.id)),
      button("Reject", "pp-aidiff-reject", () => report(view, "reject", this.hunk.id)),
    );
    box.appendChild(actions);
    return box;
  }
  ignoreEvent() {
    return true; // clicks are the buttons', not the editor's
  }
}

// Removed lines get a line class; the added lines are a block widget under the last of them (or,
// for a pure insertion, above the line it goes before). Built from the state, as block widgets
// must be.
const lineDel = Decoration.line({ class: "pp-aidiff-del" });

export const proposalDecorations = EditorView.decorations.compute([proposalField, "doc"], (state) => {
  const p = state.field(proposalField);
  if (!p) return Decoration.none;
  const doc = state.doc;
  const out = [];
  for (const h of p.hunks) {
    const from = Math.min(h.from, doc.length);
    const to = Math.min(h.to, doc.length);
    if (to > from) {
      const first = doc.lineAt(from).number;
      const last = doc.lineAt(Math.max(from, to - 1)).number;
      for (let n = first; n <= last; n++) out.push(lineDel.range(doc.line(n).from));
      const after = to >= doc.length ? doc.length : doc.lineAt(to - 1).to;
      out.push(Decoration.widget({ widget: new AddedLines(h), block: true, side: 1 }).range(after));
    } else {
      const at = doc.lineAt(from).from;
      out.push(Decoration.widget({ widget: new AddedLines(h), block: true, side: -1 }).range(at));
    }
  }
  return Decoration.set(out, true);
});

function barPanel(view) {
  const dom = document.createElement("div");
  dom.className = "pp-aidiff-bar";
  const label = document.createElement("span");
  label.className = "pp-aidiff-bar-text";
  const fill = (p) => {
    const n = p ? p.hunks.length : 0;
    label.textContent = `AI suggests ${n} change${n === 1 ? "" : "s"}`;
  };
  fill(view.state.field(proposalField));
  dom.append(
    label,
    button("Accept all", "pp-aidiff-accept", () => report(view, "accept")),
    button("Reject all", "pp-aidiff-reject", () => report(view, "reject")),
  );
  return {
    dom,
    top: true,
    update(u) {
      fill(u.state.field(proposalField));
    },
  };
}

// Python shows (or replaces) the proposal for doc `docId`, or clears it (null).
export function showProposal(view, proposal) {
  view.dispatch({ effects: setProposal.of(proposal) });
}

export const proposalExtension = [proposalField, proposalDecorations];
