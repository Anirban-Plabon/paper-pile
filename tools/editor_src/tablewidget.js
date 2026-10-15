// Tables in Live Preview: a real <table> whose cells can be typed into.
//
// JS only draws and captures. Every rule about what an edit does to the markdown (escaping, column
// padding, adding/deleting/moving rows and columns, alignment) lives in Python (core/tables.py):
// the widget sends `table_op {docId, from, to, op}` and Python answers by editing the document,
// after which the widget patches its DOM in place (focus and caret in the cell being typed in are
// kept). A cell shows rendered markdown until it is focused, then an <input> with its raw value.
import { undo, redo } from "@codemirror/commands";
import { syntaxTree } from "@codemirror/language";
import { Prec } from "@codemirror/state";
import { WidgetType, keymap } from "@codemirror/view";
import { renderInline } from "./widgets.js";

const IDLE_COMMIT_MS = 600;
const FOCUS_RETRY_MS = 1500;
const LOCAL_ROW_GRACE_MS = 4000; // how long an optimistic new row may wait for Python's edit

const runtime = { emit: () => {}, getDocId: () => 0, pending: null };

export function tablesRuntime({ emit, getDocId }) {
  runtime.emit = emit;
  runtime.getDocId = getDocId;
}

// Ask the next table build/patch to focus a cell. `from` (table start line offset) narrows it to
// one table; used after `/table` and after structure changes.
export function focusTableCell(row, col, from = null, root = null) {
  runtime.pending = { row, col, from, until: Date.now() + FOCUS_RETRY_MS };
  // the table may already be on screen (a new table was just inserted): focus it now
  if (root) for (const wrap of root.querySelectorAll(".pp-table-edit")) applyPending(wrap);
}

function el(tag, cls, text) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text !== undefined) e.textContent = text;
  return e;
}

// ---- reading a table out of the syntax tree ---------------------------------------------------

const unescapeCell = (s) => s.trim().replace(/\\\|/g, "|");

function readTable(state, table) {
  const doc = state.doc;
  const head = table.getChild("TableHeader");
  const rows = [];
  const add = (node) => rows.push(node.getChildren("TableCell").map((n) => ({ node: n, value: unescapeCell(doc.sliceString(n.from, n.to)) })));
  if (head) add(head);
  for (const row of table.getChildren("TableRow")) add(row);
  const delimLine = doc.lineAt(head ? head.to : table.from).number + 1;
  const delim = delimLine <= doc.lines ? doc.line(delimLine).text : "";
  const aligns = delim
    .trim()
    .replace(/^[\s>]*\|?|\|$/g, "")
    .split("|")
    .map((c) => {
      const m = /^\s*(:?)-+(:?)\s*$/.exec(c);
      return m ? (m[1] && m[2] ? "center" : m[2] ? "right" : m[1] ? "left" : "") : "";
    });
  const cols = Math.max(aligns.length, ...rows.map((r) => r.length));
  for (const r of rows) while (r.length < cols) r.push({ node: null, value: "" });
  return { rows, aligns, cols };
}

// Where the table that contains this widget is in the document right now (never cached).
function tableRange(view, dom) {
  let node = syntaxTree(view.state).resolveInner(view.posAtDOM(dom), 1);
  while (node && node.name !== "Table") node = node.parent;
  if (!node) return null;
  const doc = view.state.doc;
  return { from: doc.lineAt(node.from).from, to: doc.lineAt(node.to).to };
}

function sendOp(dom, op) {
  const view = dom._view;
  const range = view && tableRange(view, dom);
  if (!range) return;
  // only the start: the table's length changes with every edit, so Python measures it itself
  runtime.emit("table_op", { docId: runtime.getDocId(), from: range.from, op });
}

// ---- the editable table ------------------------------------------------------------------------

export class TableWidget extends WidgetType {
  constructor(src, state, table) {
    super();
    this.src = src;
    this.state = state;
    this.data = readTable(state, table);
  }
  eq(other) {
    return other.src === this.src;
  }
  toDOM(view) {
    const wrap = el("div", "pp-table pp-table-edit");
    wrap._view = view;
    wrap._model = null;
    this.fill(wrap);
    this.wire(wrap);
    queueMicrotask(() => applyPending(wrap));
    return wrap;
  }
  updateDOM(dom, view) {
    if (!dom.classList.contains("pp-table-edit")) return false;
    dom._view = view;
    const old = dom._model;
    const { rows, cols } = this.data;
    // rows the user added a moment ago may not have reached the document yet: keep them
    const waiting = old && old.cols === cols && rows.length < old.rows && Date.now() - (dom._localSince || 0) < LOCAL_ROW_GRACE_MS;
    if (old && (old.rows === rows.length || waiting) && old.cols === cols) {
      if (old.rows === rows.length) dom._localSince = 0; // everything the user added has arrived
      this.patch(dom);
    } else {
      closeMenu();
      this.fill(dom);
    }
    queueMicrotask(() => applyPending(dom));
    return true;
  }
  ignoreEvent() {
    return true; // everything inside the table is ours; the document selection stays untouched
  }

  // (re)build the whole DOM of the table
  fill(wrap) {
    const { rows, aligns, cols } = this.data;
    const table = el("table");
    const cells = [];
    rows.forEach((row, r) => {
      const tr = el("tr");
      const line = [];
      for (let c = 0; c < cols; c++) {
        const td = el(r === 0 ? "th" : "td");
        td._r = r;
        td._c = c;
        td._value = row[c].value;
        if (aligns[c]) td.style.textAlign = aligns[c];
        showValue(td, this.state, row[c].node, row[c].value);
        tr.appendChild(td);
        line.push(td);
      }
      cells.push(line);
      (r === 0 ? (table._head ??= table.appendChild(el("thead"))) : (table._body ??= table.appendChild(el("tbody")))).appendChild(tr);
    });
    const addRow = el("button", "pp-table-add pp-table-addrow", "+");
    addRow.title = "Add row";
    addRow.type = "button";
    const addCol = el("button", "pp-table-add pp-table-addcol", "+");
    addCol.title = "Add column";
    addCol.type = "button";
    const grid = el("div", "pp-table-grid");
    grid.append(table, addCol);
    wrap.replaceChildren(grid, addRow);
    wrap._cells = cells;
    wrap._addRow = addRow;
    wrap._addCol = addCol;
    wrap._model = { rows: rows.length, cols };
    addRow.addEventListener("mousedown", (e) => {
      e.preventDefault();
      commitActive(wrap);
      const r = appendRowLocal(wrap);
      sendOp(wrap, { op: "insert_row", at: r });
      focusCell(wrap, r, 0);
    });
    addCol.addEventListener("mousedown", (e) => {
      e.preventDefault();
      commitActive(wrap);
      focusTableCell(0, wrap._cells[0].length);
      sendOp(wrap, { op: "insert_col", at: wrap._cells[0].length });
    });
  }

  // same shape: only refresh cells whose text changed, and never the one being typed in
  patch(wrap) {
    const { rows, aligns } = this.data;
    rows.forEach((row, r) =>
      row.forEach((cell, c) => {
        const td = wrap._cells[r][c];
        td.style.textAlign = aligns[c] || "";
        if (td._input) return; // being edited: the typed text wins
        if (td._value !== cell.value || td._stale) {
          td._value = cell.value;
          td._stale = false;
          showValue(td, this.state, cell.node, cell.value);
        }
      }),
    );
  }

  wire(wrap) {
    wrap.addEventListener("mousedown", (e) => {
      const td = e.target.closest && e.target.closest("td, th");
      if (!td || !wrap.contains(td)) return;
      if (td._input && e.button === 0) return; // let the caret move inside the input
      e.preventDefault(); // also for the right button: the browser would move the document caret here
      if (e.button === 0) startEdit(wrap, td);
    });
    wrap.addEventListener("contextmenu", (e) => {
      const td = e.target.closest && e.target.closest("td, th");
      if (!td || !wrap.contains(td)) return;
      e.preventDefault();
      openMenu(wrap, td, e.clientX, e.clientY);
    });
  }
}

// ---- cells -------------------------------------------------------------------------------------

function showValue(td, state, node, value) {
  td.replaceChildren();
  if (node && value !== "") td.appendChild(renderInline(state, node));
  else if (value !== "") td.textContent = value;
}

function startEdit(wrap, td) {
  commitActive(wrap, td);
  if (td._input) return;
  const input = el("input", "pp-table-input");
  input.type = "text";
  input.spellcheck = false;
  input.value = td._value;
  input._original = td._value;
  td._input = input;
  td.replaceChildren(input);
  wrap._active = td;
  input.focus();
  input.setSelectionRange(input.value.length, input.value.length);
  let timer = null;
  input.addEventListener("input", () => {
    clearTimeout(timer);
    timer = setTimeout(() => commit(wrap, td), IDLE_COMMIT_MS);
  });
  input.addEventListener("blur", () => {
    clearTimeout(timer);
    commit(wrap, td);
    endEdit(wrap, td);
  });
  input.addEventListener("keydown", (e) => onKey(e, wrap, td));
}

// send the typed text to Python if it changed
function commit(wrap, td) {
  const input = td._input;
  if (!input || input.value === input._original) return;
  const value = input.value;
  input._original = value;
  td._value = value;
  td._stale = true; // shown as typed until Python's answer re-renders it
  sendOp(wrap, { op: "cell", row: td._r, col: td._c, value });
}

function endEdit(wrap, td) {
  if (!td._input) return;
  td._input = null;
  if (wrap._active === td) wrap._active = null;
  td.replaceChildren(document.createTextNode(td._value)); // plain until the patch re-renders it
}

function commitActive(wrap, except = null) {
  const td = wrap._active;
  if (td && td !== except) commit(wrap, td);
}

// A new last row appears (and gets the cursor) at once; Python's edit then only confirms it. This
// keeps fast typing from landing in the wrong cell while the round trip is in flight.
function appendRowLocal(wrap) {
  const r = wrap._cells.length;
  const tr = el("tr");
  const line = [];
  for (const above of wrap._cells[r - 1]) {
    const td = el("td");
    td._r = r;
    td._c = above._c;
    td._value = "";
    td.style.textAlign = above.style.textAlign;
    tr.appendChild(td);
    line.push(td);
  }
  const table = wrap.querySelector("table");
  (table.querySelector("tbody") ?? table.appendChild(el("tbody"))).appendChild(tr);
  wrap._cells.push(line);
  wrap._model.rows = r + 1;
  wrap._localSince = Date.now();
  return r;
}

function focusCell(wrap, r, c) {
  const td = wrap._cells[r] && wrap._cells[r][c];
  if (!td) return false;
  startEdit(wrap, td);
  return true;
}

function applyPending(wrap) {
  const p = runtime.pending;
  if (!p || Date.now() > p.until || !wrap.isConnected) return;
  const row = p.row < 0 ? wrap._cells.length - 1 : p.row; // -1: the last row
  const td = wrap._cells[row] && wrap._cells[row][p.col];
  if (!td) return; // the structure change has not arrived yet; a later patch retries
  if (p.from !== null) {
    const range = tableRange(wrap._view, wrap);
    if (!range || range.from !== p.from) return;
  }
  runtime.pending = null;
  startEdit(wrap, td);
}

function leaveTable(wrap, td, up) {
  const view = wrap._view;
  const range = tableRange(view, wrap);
  td.querySelector("input")?.blur();
  if (!range) return;
  const doc = view.state.doc;
  const target = up ? Math.max(0, range.from - 1) : Math.min(doc.length, range.to + 1);
  view.dispatch({ selection: { anchor: target }, scrollIntoView: true });
  view.focus();
}

function onKey(e, wrap, td) {
  const input = td._input;
  const R = wrap._cells.length;
  const C = wrap._cells[0].length;
  const r = td._r;
  const c = td._c;
  const go = (nr, nc) => {
    e.preventDefault();
    focusCell(wrap, nr, nc);
  };
  const addRowAndGo = (col) => {
    e.preventDefault();
    commit(wrap, td);
    const row = appendRowLocal(wrap);
    sendOp(wrap, { op: "insert_row", at: row });
    focusCell(wrap, row, col);
  };
  e.stopPropagation();
  if (e.key === "Tab") {
    if (!e.shiftKey && r === R - 1 && c === C - 1) return addRowAndGo(0);
    const i = r * C + c + (e.shiftKey ? -1 : 1);
    if (i < 0 || i >= R * C) return e.preventDefault();
    return go(Math.floor(i / C), i % C);
  }
  if (e.key === "Enter") {
    if (r === R - 1) return addRowAndGo(c);
    return go(r + 1, c);
  }
  if (e.key === "Escape") {
    e.preventDefault();
    return leaveTable(wrap, td, false);
  }
  if (e.key === "ArrowDown") {
    if (r === R - 1) {
      e.preventDefault();
      return leaveTable(wrap, td, false);
    }
    return go(r + 1, c);
  }
  if (e.key === "ArrowUp") {
    if (r === 0) {
      e.preventDefault();
      return leaveTable(wrap, td, true);
    }
    return go(r - 1, c);
  }
  if (e.key === "ArrowLeft" && input.selectionStart === 0 && input.selectionEnd === 0 && (c > 0 || r > 0)) {
    return go(c > 0 ? r : r - 1, c > 0 ? c - 1 : C - 1);
  }
  const end = input.value.length;
  if (e.key === "ArrowRight" && input.selectionStart === end && input.selectionEnd === end && (c < C - 1 || r < R - 1)) {
    return go(c < C - 1 ? r : r + 1, c < C - 1 ? c + 1 : 0);
  }
  if ((e.ctrlKey || e.metaKey) && (e.key === "z" || e.key === "y" || e.key === "Z")) {
    e.preventDefault();
    if (input.value !== input._original) {
      input.value = input._original; // uncommitted typing: take it back
      return;
    }
    const view = wrap._view;
    input.blur();
    view.focus();
    (e.key === "y" || e.shiftKey ? redo : undo)(view);
  }
}

// ---- right-click menu --------------------------------------------------------------------------

let openMenuEl = null;

function closeMenu() {
  if (openMenuEl) openMenuEl.remove();
  openMenuEl = null;
}

function openMenu(wrap, td, x, y) {
  closeMenu();
  commitActive(wrap);
  const R = wrap._cells.length;
  const C = wrap._cells[0].length;
  const r = td._r;
  const c = td._c;
  const run = (op, row = null, col = null) => () => {
    if (row !== null) focusTableCell(row, col);
    sendOp(wrap, op);
  };
  const items = [];
  if (r >= 1) items.push(["Insert row above", run({ op: "insert_row", at: r }, r, c)]);
  items.push(["Insert row below", run({ op: "insert_row", at: r === 0 ? 1 : r + 1 }, r === 0 ? 1 : r + 1, c)]);
  if (r >= 2) items.push(["Move row up", run({ op: "move_row", row: r, to: r - 1 }, r - 1, c)]);
  if (r >= 1 && r < R - 1) items.push(["Move row down", run({ op: "move_row", row: r, to: r + 1 }, r + 1, c)]);
  if (r >= 1) items.push(["Delete row", run({ op: "delete_row", row: r })]);
  items.push(null);
  items.push(["Insert column left", run({ op: "insert_col", at: c }, r, c)]);
  items.push(["Insert column right", run({ op: "insert_col", at: c + 1 }, r, c + 1)]);
  if (C > 1) items.push(["Delete column", run({ op: "delete_col", col: c })]);
  items.push(null);
  for (const [label, align] of [["Align left", "left"], ["Align center", "center"], ["Align right", "right"], ["No alignment", ""]]) {
    items.push([label, run({ op: "align", col: c, align })]);
  }
  const menu = el("div", "pp-tmenu");
  for (const item of items) {
    if (!item) {
      menu.appendChild(el("div", "pp-tmenu-sep"));
      continue;
    }
    const row = el("div", "pp-tmenu-item", item[0]);
    row.addEventListener("mousedown", (e) => {
      e.preventDefault();
      closeMenu();
      item[1]();
    });
    menu.appendChild(row);
  }
  menu.style.left = `${x}px`;
  menu.style.top = `${y}px`;
  (wrap.closest(".pp-editor") || document.body).appendChild(menu);
  const box = menu.getBoundingClientRect();
  if (box.bottom > innerHeight) menu.style.top = `${Math.max(0, y - box.height)}px`;
  if (box.right > innerWidth) menu.style.left = `${Math.max(0, x - box.width)}px`;
  openMenuEl = menu;
  const away = (e) => {
    if (e.type === "keydown" && e.key !== "Escape") return;
    if (e.type === "mousedown" && menu.contains(e.target)) return;
    closeMenu();
    document.removeEventListener("mousedown", away, true);
    document.removeEventListener("keydown", away, true);
  };
  document.addEventListener("mousedown", away, true);
  document.addEventListener("keydown", away, true);
}

// ---- read-only preview, shown above the source while the document caret is inside the table ----

export class TablePreview extends WidgetType {
  constructor(src, state, table) {
    super();
    this.src = src;
    this.state = state;
    this.data = readTable(state, table);
  }
  eq(other) {
    return other.src === this.src;
  }
  toDOM() {
    const wrap = el("div", "pp-table pp-table-preview");
    const table = el("table");
    const { rows, aligns, cols } = this.data;
    const thead = el("thead");
    const tbody = el("tbody");
    rows.forEach((row, r) => {
      const tr = el("tr");
      for (let c = 0; c < cols; c++) {
        const cell = el(r === 0 ? "th" : "td");
        if (aligns[c]) cell.style.textAlign = aligns[c];
        showValue(cell, this.state, row[c].node, row[c].value);
        tr.appendChild(cell);
      }
      (r === 0 ? thead : tbody).appendChild(tr);
    });
    table.append(thead, tbody);
    wrap.appendChild(table);
    return wrap;
  }
  ignoreEvent() {
    return false;
  }
}

// ---- arrow keys from the text into a table -----------------------------------------------------
// A rendered table is one block to the editor, so the caret would jump over it. ArrowDown on the
// line above a table (ArrowUp on the line below) puts the cursor in its first (last) row instead.

function tableLinesAt(state, pos) {
  let node = syntaxTree(state).resolveInner(pos, 1);
  while (node && node.name !== "Table") node = node.parent;
  if (!node) return null;
  return { from: state.doc.lineAt(node.from).from, to: state.doc.lineAt(node.to).to };
}

function enterTable(view, direction) {
  const { state } = view;
  const sel = state.selection.main;
  if (!sel.empty) return false;
  const line = state.doc.lineAt(sel.head);
  const next = direction > 0 ? line.number + 1 : line.number - 1;
  if (next < 1 || next > state.doc.lines) return false;
  const target = state.doc.line(next);
  const table = tableLinesAt(state, target.from);
  if (!table) return false;
  const edge = direction > 0 ? table.from === target.from : table.to === target.to;
  if (!edge) return false;
  focusTableCell(direction > 0 ? 0 : -1, 0, table.from, view.dom);
  return true;
}

export const tableKeys = Prec.high(
  keymap.of([
    { key: "ArrowDown", run: (view) => enterTable(view, 1) },
    { key: "ArrowUp", run: (view) => enterTable(view, -1) },
  ]),
);
