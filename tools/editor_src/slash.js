// The "/" command menu (PLAN §4.8). JS only draws it and captures keys; Python filters the
// commands (`slash_query` -> `setSlashResults`), decides what a command does and sends the exact
// text edit back (`slash_run` -> `applyChanges`).
//
// State lives in a StateField: the position of the typed "/", the current query (the text between
// the "/" and the caret) and the results Python last sent. The menu is a CM6 tooltip, so
// positioning, flipping above the caret near the bottom and scroll tracking come for free.
import { syntaxTree } from "@codemirror/language";
import { Prec, StateEffect, StateField } from "@codemirror/state";
import { EditorView, ViewPlugin, keymap, showTooltip } from "@codemirror/view";
import { rtOf } from "./context.js";

const NO_SLASH_NODES = new Set(["FencedCode", "CodeBlock", "InlineCode", "URL", "CodeText"]);
const MAX_QUERY = 40;
const PAGE = 6;

function inNoSlashContext(state, pos) {
  for (let n = syntaxTree(state).resolveInner(pos, -1); n; n = n.parent) {
    if (NO_SLASH_NODES.has(n.name)) return true;
  }
  return false;
}

// A typed "/" opens the menu at the start of a line or after whitespace, but not in code or URLs.
function triggers(state, pos) {
  const line = state.doc.lineAt(pos);
  const before = state.sliceDoc(line.from, pos);
  return (before === "" || /\s$/.test(before)) && !inNoSlashContext(state, pos);
}

const closeEffect = StateEffect.define();
const forceOpenEffect = StateEffect.define(); // position of a "/" that opens the menu regardless of the trigger rule
const resultsEffect = StateEffect.define(); // {groups}
const moveEffect = StateEffect.define(); // {delta} or {to}

const flatten = (groups) => groups.flatMap((g) => g.items);

const slashField = StateField.define({
  create: () => null,
  update(value, tr) {
    let v = value;
    let from = v ? (tr.docChanged ? tr.changes.mapPos(v.from, -1) : v.from) : -1;
    for (const e of tr.effects) if (e.is(closeEffect)) v = null;
    for (const e of tr.effects) {
      if (e.is(forceOpenEffect)) {
        v = { from: e.value, query: "", groups: [], items: [], selected: 0, hasResults: false };
        from = e.value; // already in the new document's coordinates
      }
    }
    if (tr.docChanged && tr.isUserEvent("input.type") && !tr.isUserEvent("input.type.ai")) {
      let at = null;
      tr.changes.iterChanges((fa, ta, fb, _tb, inserted) => {
        if (fa === ta && inserted.length === 1 && inserted.sliceString(0) === "/") at = fb;
      });
      if (at !== null && triggers(tr.state, at)) {
        v = { from: at, query: "", groups: [], items: [], selected: 0, hasResults: false };
        from = at; // already in the new document's coordinates
      }
    }
    if (!v) return null;
    const sel = tr.state.selection.main;
    const doc = tr.state.doc;
    if (from >= doc.length || doc.sliceString(from, from + 1) !== "/") return null; // the "/" is gone
    if (!sel.empty || sel.head < from + 1 || sel.head > doc.lineAt(from).to) return null;
    const query = doc.sliceString(from + 1, sel.head);
    if (query.length > MAX_QUERY) return null;
    v = v.from === from && v.query === query ? v : { ...v, from, query };
    for (const e of tr.effects) {
      if (e.is(resultsEffect)) {
        const items = flatten(e.value.groups);
        v = { ...v, groups: e.value.groups, items, selected: 0, hasResults: true };
      } else if (e.is(moveEffect) && v.items.length) {
        const n = v.items.length;
        const to = e.value.to !== undefined ? e.value.to : v.selected + e.value.delta;
        v = { ...v, selected: e.value.wrap ? ((to % n) + n) % n : Math.max(0, Math.min(n - 1, to)) };
      }
    }
    // "no results" and the user typed a space: they are not looking for a command any more
    if (v.query.endsWith(" ") && v.hasResults && v.items.length === 0) return null;
    return v;
  },
  provide: (f) =>
    showTooltip.compute([f], (state) => {
      const v = state.field(f);
      return v ? { pos: v.from, above: false, strictSide: false, class: "pp-slash-tooltip", create: createMenu } : null;
    }),
});

// ---- drawing --------------------------------------------------------------------------------

function el(tag, cls, text) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text !== undefined) e.textContent = text;
  return e;
}

function createMenu(view) {
  const dom = el("div", "pp-slash");
  const header = el("div", "pp-slash-header");
  const body = el("div", "pp-slash-body");
  const footer = el("div", "pp-slash-footer");
  footer.append(el("span", "", "Close menu"), el("span", "pp-slash-dot", "·"), el("kbd", "", "esc"));
  body.setAttribute("role", "listbox");
  dom.append(header, body, footer);
  let drawn = null;

  const draw = (state) => {
    const v = state.field(slashField, false);
    if (!v || v === drawn) return;
    const rebuild = !drawn || drawn.groups !== v.groups;
    header.textContent = "";
    header.append(v.query ? el("span", "pp-slash-query", v.query) : el("span", "pp-slash-placeholder", "Type to search"));
    if (rebuild) {
      body.textContent = "";
      let index = 0;
      if (!v.items.length) body.append(el("div", "pp-slash-empty", "No results"));
      for (const g of v.groups) {
        body.append(el("div", "pp-slash-group", g.group));
        for (const item of g.items) {
          const i = index++;
          const row = el("div", "pp-slash-item");
          row.id = `pp-slash-${i}`;
          row.dataset.index = String(i);
          row.setAttribute("role", "option");
          const icon = el("span", "pp-slash-icon");
          if (item.icon && window.ppIconSvg) icon.innerHTML = window.ppIconSvg(item.icon);
          row.append(icon);
          const text = el("span", "pp-slash-text");
          text.append(el("span", "pp-slash-title", item.title));
          if (item.subtitle) text.append(el("span", "pp-slash-subtitle", item.subtitle));
          row.append(text);
          if (item.badge) row.append(el("span", "pp-slash-badge", item.badge));
          if (item.hint) row.append(el("span", "pp-slash-hint", item.hint));
          // mousedown, not click: the editor must keep focus and its caret
          row.addEventListener("mousedown", (e) => {
            e.preventDefault();
            runItem(view, i);
          });
          row.addEventListener("mousemove", () => {
            const cur = view.state.field(slashField, false);
            if (cur && cur.selected !== i) view.dispatch({ effects: moveEffect.of({ to: i }) });
          });
          body.append(row);
        }
      }
    }
    for (const row of body.querySelectorAll(".pp-slash-item")) {
      const on = Number(row.dataset.index) === v.selected;
      row.classList.toggle("pp-slash-selected", on);
      row.setAttribute("aria-selected", on ? "true" : "false");
      if (on) {
        body.setAttribute("aria-activedescendant", row.id);
        row.scrollIntoView({ block: "nearest" });
      }
    }
    drawn = v;
  };
  draw(view.state);
  return { dom, update: (u) => draw(u.state) };
}

// ---- running and keys -------------------------------------------------------------------------

const emitFrom = (state, name, payload) => {
  const rt = rtOf(state);
  rt.emit(name, { docId: rt.getDocId(), ...payload });
};

function runItem(view, index) {
  const v = view.state.field(slashField, false);
  const item = v && v.items[index];
  if (!item) return false;
  emitFrom(view.state, "slash_run", { id: item.id, from: v.from, to: view.state.selection.main.head });
  view.dispatch({ effects: closeEffect.of(null) });
  return true;
}

const open = (view) => view.state.field(slashField, false);
const move = (delta, wrap) => (view) => {
  const v = open(view);
  if (!v) return false;
  if (v.items.length) view.dispatch({ effects: moveEffect.of({ delta, wrap }) });
  return true;
};

// Ctrl+J / Alt+/: open the menu keeping the selection (typing "/" would replace it). Python is told
// which text was selected; the AI commands that work on a selection read it from there.
function openOnSelection(view) {
  const { state } = view;
  if (state.selection.ranges.length !== 1) return false;
  const sel = state.selection.main;
  emitFrom(state, "ai_selection", { from: sel.from, to: sel.to, text: state.sliceDoc(sel.from, sel.to) });
  view.dispatch({
    changes: { from: sel.to, insert: "/" },
    selection: { anchor: sel.to + 1 },
    effects: forceOpenEffect.of(sel.to),
    userEvent: "input.type",
  });
  return true;
}

const slashKeys = Prec.highest(
  keymap.of([
    { key: "Mod-j", run: openOnSelection },
    { key: "Alt-/", run: openOnSelection },
    { key: "ArrowDown", run: move(1, true) },
    { key: "ArrowUp", run: move(-1, true) },
    { key: "PageDown", run: move(PAGE, false) },
    { key: "PageUp", run: move(-PAGE, false) },
    { key: "Enter", run: (view) => { const v = open(view); return v && v.items.length ? runItem(view, v.selected) : false; } },
    { key: "Tab", run: (view) => { const v = open(view); return v && v.items.length ? runItem(view, v.selected) : false; } },
    { key: "Escape", run: (view) => { if (!open(view)) return false; view.dispatch({ effects: closeEffect.of(null) }); return true; } },
  ]),
);

// Tells Python the query whenever it changes; later results for an older query are ignored.
const queryPlugin = ViewPlugin.fromClass(
  class {
    constructor() {
      this.seq = 0;
      this.last = null;
    }
    update(u) {
      const v = u.state.field(slashField, false);
      if (!v) {
        this.last = null;
        return;
      }
      if (this.last && this.last.from === v.from && this.last.query === v.query) return;
      this.last = { from: v.from, query: v.query };
      this.seq += 1;
      emitFrom(u.state, "slash_query", { q: v.query, seq: this.seq, from: v.from });
    }
  },
);

export function slashExtension() {
  return [
    slashField,
    queryPlugin,
    slashKeys,
    EditorView.domEventHandlers({
      blur: (_e, view) => {
        if (open(view)) view.dispatch({ effects: closeEffect.of(null) });
        return false;
      },
    }),
  ];
}

export const closeSlash = () => closeEffect.of(null);

// Python's answer for query `seq`; anything but the latest query's answer is stale.
export function setSlashResults(view, seq, groups) {
  const plugin = view.plugin(queryPlugin);
  if (!plugin || seq !== plugin.seq || !view.state.field(slashField, false)) return;
  view.dispatch({ effects: resultsEffect.of({ groups }) });
}
