// Keyboard shortcuts for the formatting menu's items (user 2026-11-22, PLAN §4.38): with words
// selected, Ctrl+B bold, Ctrl+I italic, Ctrl+U underline, Ctrl+Shift+X strikethrough, Ctrl+Shift+H
// highlight, Ctrl+` inline code, Ctrl+K link, Ctrl+Shift+M comment. Python does the edit (the same
// `core/formatting.apply` as the menu); link and comment open the menu's Link / Comment box at the
// selection. Without a selection the keys keep their usual meaning: CodeMirror's own (Ctrl+I, Ctrl+U)
// or the app's (Ctrl+B folds the left pane; shortcuts.py asks `window.ppEditorHasSelection`).

import { Facet, Prec } from "@codemirror/state";
import { EditorView, keymap } from "@codemirror/view";
import { rtOf } from "./context.js";

// markdown notes have it (not `.txt`): the app's Ctrl+B gives way only where the keys work
export const formatKeysOn = Facet.define({ combine: (values) => values.length > 0 });

const KEYS = {
  "Mod-b": "bold",
  "Mod-i": "italic",
  "Mod-u": "underline",
  "Mod-Shift-x": "strike",
  "Mod-Shift-h": "highlight",
  "Mod-`": "code",
  "Mod-k": "link",
  "Mod-Shift-m": "comment",
};

const run = (kind) => (view) => {
  const { state } = view;
  const sel = state.selection.main;
  if (sel.empty || state.selection.ranges.length !== 1 || state.readOnly) return false;
  const at = view.coordsAtPos(sel.to) ?? view.coordsAtPos(sel.from);
  const rt = rtOf(state);
  rt.emit("format_key", { docId: rt.getDocId(), kind, from: sel.from, to: sel.to, x: at ? at.left : 0, y: at ? at.bottom + 6 : 0 });
  return true;
};

export const formatKeys = [
  formatKeysOn.of(true),
  Prec.high(keymap.of(Object.entries(KEYS).map(([key, kind]) => ({ key, run: run(kind), preventDefault: true })))),
];

// The item a key event asks for, or null (askpop.js: the keys typed in the Ask box of a selection
// format the note's selection)
export function formatKind(e) {
  if (!(e.ctrlKey || e.metaKey) || e.altKey) return null;
  const k = e.code === "Backquote" ? "`" : (e.key || "").toLowerCase();
  const key = `Mod-${e.shiftKey ? "Shift-" : ""}${k}`;
  return KEYS[key] ?? null;
}

// Run item `kind` on the selection of the editor holding `dom` (askpop.js)
export function formatKeyFor(dom, kind) {
  const ed = dom && dom.closest ? dom.closest(".cm-editor") : null;
  const view = ed && EditorView.findFromDOM(ed);
  return !!view && view.state.facet(formatKeysOn) && run(kind)(view);
}

// Is `target` inside a markdown editor holding a selection, or in the Ask box of a selection?
// (shortcuts.py: Ctrl+B then bolds)
export function editorHasSelection(target) {
  const ask = target && target.closest ? target.closest(".pp-askpop") : null;
  if (ask) return ask.classList.contains("pp-askpop-box");
  const dom = target && target.closest ? target.closest(".cm-editor") : null;
  const view = dom && EditorView.findFromDOM(dom);
  if (!view || !view.state.facet(formatKeysOn)) return false;
  const sel = view.state.selection.main;
  return !sel.empty && !view.state.readOnly;
}
