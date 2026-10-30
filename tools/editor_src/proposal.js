// An AI edit shown as a diff for the user to approve (PLAN §4.26): the lines it would remove get
// a light red background and a "−", the lines it would add are drawn below them in light green
// with a "+", each change with Accept / Reject, and a bar on top with Accept all / Reject all.
// Nothing here changes the note: a click is reported to Python, which applies the change (one
// undo step) and sends what is left of the proposal, or clears it. Positions follow typing.
// An edit of several places (PLAN §4.29) shows each change's reason, an "outside selection" chip
// and the checks' warnings, marks the words that changed, and the bar jumps between changes
// (‹ ›) and lists notes ("Similar text in …", "Maybe also update …" with Update).
import { StateEffect, StateField } from "@codemirror/state";
import { Decoration, EditorView, WidgetType, showPanel } from "@codemirror/view";
import { rtOf } from "./context.js";

// {id, docId, readonly, notes: [{i, message, update}],
//  hunks: [{id, from, to, insert, reason, outside, issues: [{severity, message}], marksOld, marksNew}]}
const setProposal = StateEffect.define();

export const proposalField = StateField.define({
  create: () => null,
  update(value, tr) {
    for (const e of tr.effects) if (e.is(setProposal)) value = e.value;
    if (value && tr.docChanged) {
      const hunks = value.hunks.map((h) => ({
        ...h,
        from: tr.changes.mapPos(h.from, -1),
        to: tr.changes.mapPos(h.to, 1),
        marksOld: (h.marksOld || []).map(([a, b]) => [tr.changes.mapPos(a, 1), tr.changes.mapPos(b, -1)]),
      }));
      value = { ...value, hunks };
    }
    return value;
  },
  provide: (f) => showPanel.from(f, (p) => (p ? barPanel : null)),
});

const report = (view, action, hunk = null, note = null) => {
  const p = view.state.field(proposalField);
  if (p) rtOf(view.state).emit("proposal", { docId: p.docId, proposal: p.id, hunk, action, note });
};

const chip = (text, cls) => {
  const c = document.createElement("span");
  c.className = `pp-aidiff-chip ${cls}`;
  c.textContent = text;
  return c;
};

// one added line, with the words that changed marked (`marks`: [from, to] in the whole insert)
function addedLine(line, offset, marks) {
  const row = document.createElement("div");
  row.className = "pp-aidiff-add";
  let at = 0;
  for (const [a, b] of marks) {
    const from = Math.max(a - offset, 0);
    const to = Math.min(b - offset, line.length);
    if (to <= from) continue;
    if (from > at) row.append(line.slice(at, from));
    const word = document.createElement("span");
    word.className = "pp-aidiff-addword";
    word.textContent = line.slice(from, to);
    row.append(word);
    at = to;
  }
  if (at < line.length) row.append(line.slice(at));
  if (!line) row.textContent = " "; // keeps an empty line's height
  return row;
}

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
  constructor(hunk, readonly) {
    super();
    this.hunk = hunk;
    this.readonly = readonly;
  }
  eq(other) {
    return other.hunk.id === this.hunk.id && other.hunk.insert === this.hunk.insert && other.readonly === this.readonly;
  }
  toDOM(view) {
    const h = this.hunk;
    const box = document.createElement("div");
    box.className = "pp-aidiff-block";
    if (h.reason) {
      const why = document.createElement("div");
      why.className = "pp-aidiff-why";
      why.textContent = h.reason;
      box.appendChild(why);
    }
    const text = h.insert.replace(/\n$/, "");
    if (h.insert) {
      let offset = 0;
      for (const line of text.split("\n")) {
        box.appendChild(addedLine(line, offset, h.marksNew || []));
        offset += line.length + 1;
      }
    }
    const actions = document.createElement("div");
    actions.className = "pp-aidiff-actions";
    if (this.readonly) {
      // read-only (Settings → AI): nothing is applied; the new text can be copied
      actions.append(
        button("Copy", "pp-aidiff-copy", () => navigator.clipboard?.writeText(this.hunk.insert)),
        button("Close", "pp-aidiff-reject", () => report(view, "reject", this.hunk.id)),
      );
    } else {
      actions.append(
        button("Accept", "pp-aidiff-accept", () => report(view, "accept", this.hunk.id)),
        button("Reject", "pp-aidiff-reject", () => report(view, "reject", this.hunk.id)),
      );
    }
    if (h.outside) actions.append(chip("outside the selection", "pp-aidiff-chip-outside"));
    for (const issue of h.issues || []) {
      actions.append(chip(issue.message, issue.severity === "warn" ? "pp-aidiff-chip-warn" : "pp-aidiff-chip-fixed"));
    }
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
const wordDel = Decoration.mark({ class: "pp-aidiff-delword" });

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
      for (const [a, b] of h.marksOld || []) {
        if (b > a && a >= from && b <= to) out.push(wordDel.range(a, b));
      }
      const after = to >= doc.length ? doc.length : doc.lineAt(to - 1).to;
      out.push(Decoration.widget({ widget: new AddedLines(h, !!p.readonly), block: true, side: 1 }).range(after));
    } else {
      const at = doc.lineAt(from).from;
      out.push(Decoration.widget({ widget: new AddedLines(h, !!p.readonly), block: true, side: -1 }).range(at));
    }
  }
  return Decoration.set(out, true);
});

function barPanel(view) {
  const dom = document.createElement("div");
  dom.className = "pp-aidiff-bar";
  const row = document.createElement("div");
  row.className = "pp-aidiff-bar-row";
  const label = document.createElement("span");
  label.className = "pp-aidiff-bar-text";
  const notes = document.createElement("div");
  notes.className = "pp-aidiff-notes";
  let at = -1; // the change ‹ › last jumped to
  const jump = (step) => {
    const p = view.state.field(proposalField);
    if (!p || !p.hunks.length) return;
    at = (at + step + p.hunks.length) % p.hunks.length;
    const pos = Math.min(p.hunks[at].from, view.state.doc.length);
    view.dispatch({ effects: EditorView.scrollIntoView(pos, { y: "center" }) });
  };
  const places = (p) =>
    new Set(p.hunks.map((h) => view.state.doc.lineAt(Math.min(h.from, view.state.doc.length)).number)).size;
  let shown = null;
  const fill = (p) => {
    const n = p ? p.hunks.length : 0;
    const where = p && n > 1 && places(p) > 1 ? ` in ${places(p)} places` : "";
    label.textContent = `AI suggests ${n} change${n === 1 ? "" : "s"}${where}${p && p.readonly ? " (read-only)" : ""}`;
    if (p === shown) return;
    shown = p;
    notes.replaceChildren();
    for (const note of (p && p.notes) || []) {
      const line = document.createElement("div");
      line.className = "pp-aidiff-note";
      line.append(note.update ? `Maybe also update: ${note.message}` : note.message);
      if (note.update && !p.readonly) line.append(button("Update", "pp-aidiff-update", () => report(view, "update", null, note.i)));
      notes.append(line);
    }
    notes.hidden = !notes.childElementCount;
  };
  const p = view.state.field(proposalField);
  row.append(label);
  if (p && p.hunks.length > 1) {
    row.append(button("‹", "pp-aidiff-nav", () => jump(-1)), button("›", "pp-aidiff-nav", () => jump(1)));
  }
  if (!p || !p.readonly) row.append(button("Accept all", "pp-aidiff-accept", () => report(view, "accept")));
  row.append(button(p && p.readonly ? "Close" : "Reject all", "pp-aidiff-reject", () => report(view, "reject")));
  dom.append(row, notes);
  fill(p);
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
