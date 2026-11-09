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
import { rtOf, editorContext, measureAgain } from "./context.js";

const IDLE_COMMIT_MS = 600;
const FOCUS_RETRY_MS = 1500;
const LOCAL_ROW_GRACE_MS = 4000; // how long an optimistic new row may wait for Python's edit
const EDGE_PX = 5; // how near a cell's side border the pointer resizes its column
const MIN_COL_PX = 40; // narrowest column a drag makes (core/table_widths.py MIN_WIDTH)

const runtime = { pending: null };

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
  const rt = rtOf(view.state);
  rt.emit("table_op", { docId: rt.getDocId(), from: range.from, op });
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
    const plus = window.ppIconSvg?.("plus", "s") ?? "+";
    const addRow = el("button", "pp-table-add pp-table-addrow");
    addRow.innerHTML = plus;
    addRow.dataset.tip = "Add row";
    addRow.type = "button";
    const addCol = el("button", "pp-table-add pp-table-addcol");
    addCol.innerHTML = plus;
    addCol.dataset.tip = "Add column";
    addCol.type = "button";
    // a 2 × 2 grid: the table, + column at its right (as tall as the table), + row under it (as
    // wide as the table), so neither covers a cell (user 2026-11-09)
    const grid = el("div", "pp-table-grid");
    grid.append(table, addCol, addRow);
    wrap.replaceChildren(grid);
    const widths = storedWidths(wrap._view, rows[0].map((c) => c.value), cols);
    if (widths) applyWidths(table, widths);
    wrap._cells = cells;
    wrap._addRow = addRow;
    wrap._addCol = addCol;
    wrap._model = { rows: rows.length, cols };
    wrap._sel = null;
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
    wrap.tabIndex = -1; // focused while a block of cells is selected: it takes the keys then
    wrap.addEventListener("mousemove", (e) => {
      if (!wrap._resizing) wrap.classList.toggle("pp-table-colresize", edgeAt(wrap, e) !== null);
    });
    wrap.addEventListener("mousedown", (e) => {
      const edge = e.button === 0 ? edgeAt(wrap, e) : null;
      if (edge !== null) {
        e.preventDefault();
        startResize(wrap, edge, e.clientX);
        return;
      }
      const td = e.target.closest && e.target.closest("td, th");
      if (!td || !wrap.contains(td)) return;
      if (e.button === 0 && e.shiftKey) {
        // Shift+click: the block from the cell being typed in (or the block's corner) to here
        e.preventDefault();
        const from = wrap._active || (wrap._sel && wrap._cells[wrap._sel.r0]?.[wrap._sel.c0]) || td;
        selectBlock(wrap, from._r, from._c, td._r, td._c);
        return;
      }
      if (e.button === 0) startDrag(wrap, td);
      if (td._input && e.button === 0) return; // let the caret move inside the input
      e.preventDefault(); // also for the right button: the browser would move the document caret here
      if (e.button !== 0) return;
      clearBlock(wrap);
      startEdit(wrap, td);
    });
    wrap.addEventListener("keydown", (e) => onBlockKey(e, wrap));
    wrap.addEventListener("copy", (e) => copyBlock(e, wrap, false));
    wrap.addEventListener("cut", (e) => copyBlock(e, wrap, true));
    wrap.addEventListener("paste", (e) => pasteCells(e, wrap));
    wrap.addEventListener("focusout", (e) => {
      if (!wrap.contains(e.relatedTarget)) clearBlock(wrap);
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
  input.size = 1; // its default ~20-character width would widen the column (cells jumped on click)
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

// ---- a block of cells (user 2026-11-09: partial selection) ------------------------------------
// Drag from one cell to another, or Shift+click, selects the rectangle between them. While a
// block is selected the table itself has the focus: Copy gives its values as tab-separated rows
// (what spreadsheets paste), Cut and Delete / Backspace empty the cells, Paste writes copied rows
// from its top-left cell, Shift+arrows grow or shrink it, Esc or an arrow leaves it. What the
// markdown becomes is decided in Python (`cells` in core/tables.py).

function selectBlock(wrap, r0, c0, r1, c1) {
  const R = wrap._cells.length;
  const C = wrap._cells[0].length;
  const clamp = (v, n) => Math.max(0, Math.min(n - 1, v));
  wrap._sel = { r0: clamp(r0, R), c0: clamp(c0, C), r1: clamp(r1, R), c1: clamp(c1, C) };
  // the table takes the focus first: the cell's input then blurs (it commits and ends itself)
  // with focus inside the table, so the block is not dropped as "focus left the table"
  if (document.activeElement !== wrap) wrap.focus({ preventScroll: true });
  const td = wrap._active;
  if (td) {
    commit(wrap, td);
    endEdit(wrap, td);
  }
  paintBlock(wrap);
}

function blockBox(sel) {
  return {
    top: Math.min(sel.r0, sel.r1),
    bottom: Math.max(sel.r0, sel.r1),
    left: Math.min(sel.c0, sel.c1),
    right: Math.max(sel.c0, sel.c1),
  };
}

function paintBlock(wrap) {
  const box = wrap._sel && blockBox(wrap._sel);
  wrap._cells.forEach((line, r) =>
    line.forEach((td, c) => {
      const on = !!box && r >= box.top && r <= box.bottom && c >= box.left && c <= box.right;
      td.classList.toggle("pp-tsel", on);
      td.classList.toggle("pp-tsel-top", on && r === box.top);
      td.classList.toggle("pp-tsel-bottom", on && r === box.bottom);
      td.classList.toggle("pp-tsel-left", on && c === box.left);
      td.classList.toggle("pp-tsel-right", on && c === box.right);
    }),
  );
  wrap.classList.toggle("pp-table-block", !!box);
}

function clearBlock(wrap) {
  if (!wrap._sel) return;
  wrap._sel = null;
  paintBlock(wrap);
}

function blockValues(wrap) {
  const b = blockBox(wrap._sel);
  const out = [];
  for (let r = b.top; r <= b.bottom; r++) {
    const line = [];
    for (let c = b.left; c <= b.right; c++) line.push(wrap._cells[r][c]._value ?? "");
    out.push(line);
  }
  return out;
}

// write `values` (rows of strings) from (row, col): shown at once, then confirmed by Python
function writeCells(wrap, row, col, values) {
  values.forEach((line, i) =>
    line.forEach((value, j) => {
      const td = wrap._cells[row + i]?.[col + j];
      if (!td || td._input) return;
      td._value = value;
      td._stale = true;
      td.replaceChildren(document.createTextNode(value));
    }),
  );
  sendOp(wrap, { op: "cells", row, col, values });
}

function clearCells(wrap) {
  const b = blockBox(wrap._sel);
  const empty = blockValues(wrap).map((line) => line.map(() => ""));
  writeCells(wrap, b.top, b.left, empty);
}

// The copied block is a table wherever it is pasted: text/html holds a <table> (Smart Paste turns
// it into a markdown table in a note; spreadsheets and rich editors take it as cells) and
// text/plain a markdown table (other markdown apps, Smart Paste off). The block's first row is the
// header. Pasted back into a table, Python reads it as cells again (`paste`, core/tables.py).
const escHtml = (v) => v.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
const escCell = (v) => v.replace(/\|/g, "\\|").replace(/[\t\n]/g, " ");

function blockHtml(rows) {
  const line = (cells, tag) => `<tr>${cells.map((v) => `<${tag}>${escHtml(v)}</${tag}>`).join("")}</tr>`;
  const [head, ...body] = rows;
  return `<table><thead>${line(head, "th")}</thead><tbody>${body.map((r) => line(r, "td")).join("")}</tbody></table>`;
}

function blockMarkdown(rows) {
  const line = (cells) => `| ${cells.map(escCell).join(" | ")} |`;
  const [head, ...body] = rows;
  return [line(head), `|${head.map(() => " --- ").join("|")}|`, ...body.map(line)].join("\n");
}

function copyBlock(e, wrap, cut) {
  if (!wrap._sel) return; // text copied inside a cell's input: the browser's own copy
  e.preventDefault();
  e.stopPropagation();
  const rows = blockValues(wrap);
  e.clipboardData.setData("text/html", blockHtml(rows));
  e.clipboardData.setData("text/plain", blockMarkdown(rows) + "\n");
  if (cut) clearCells(wrap);
}

function pasteCells(e, wrap) {
  const text = e.clipboardData && e.clipboardData.getData("text/plain");
  if (!text) return;
  const td = wrap._sel ? null : e.target.closest && e.target.closest("td, th");
  // into a cell being typed in, only several cells' worth is ours; one value is a plain paste
  if (!wrap._sel && (!td || !/[\t\n]/.test(text.replace(/\r?\n$/, "")))) return;
  e.preventDefault();
  e.stopPropagation();
  let at;
  if (wrap._sel) {
    const b = blockBox(wrap._sel);
    at = { row: b.top, col: b.left };
  } else {
    at = { row: td._r, col: td._c };
    td.querySelector("input")?.blur();
  }
  // Python reads the cells (a markdown table or tab-separated rows) and writes them
  sendOp(wrap, { op: "paste", row: at.row, col: at.col, text });
}

function onBlockKey(e, wrap) {
  if (!wrap._sel || e.target !== wrap) return;
  const sel = wrap._sel;
  const arrows = { ArrowUp: [-1, 0], ArrowDown: [1, 0], ArrowLeft: [0, -1], ArrowRight: [0, 1] };
  e.stopPropagation();
  if (e.key === "Escape") {
    e.preventDefault();
    clearBlock(wrap);
    focusCell(wrap, sel.r0, sel.c0);
  } else if (e.key === "Delete" || e.key === "Backspace") {
    e.preventDefault();
    clearCells(wrap);
  } else if (arrows[e.key] && e.shiftKey) {
    e.preventDefault();
    const [dr, dc] = arrows[e.key];
    selectBlock(wrap, sel.r0, sel.c0, sel.r1 + dr, sel.c1 + dc);
  } else if (arrows[e.key] || e.key === "Enter" || e.key === "Tab") {
    e.preventDefault();
    clearBlock(wrap);
    focusCell(wrap, sel.r1, sel.c1);
  } else if ((e.ctrlKey || e.metaKey) && (e.key === "z" || e.key === "y" || e.key === "Z")) {
    e.preventDefault();
    const view = wrap._view;
    clearBlock(wrap);
    view.focus();
    (e.key === "y" || e.shiftKey ? redo : undo)(view);
  }
}

// a drag that starts in a cell and moves into another selects the block between them
function startDrag(wrap, from) {
  const move = (e) => {
    if (!(e.buttons & 1)) return up();
    const hit = document.elementFromPoint(e.clientX, e.clientY);
    const td = hit && hit.closest && hit.closest("td, th");
    if (!td || !wrap.contains(td) || td._r === undefined) return;
    if (td === from && !wrap._sel) return; // still inside the first cell: its own text selection
    e.preventDefault();
    window.getSelection()?.removeAllRanges();
    if (!wrap._sel || wrap._sel.r1 !== td._r || wrap._sel.c1 !== td._c) selectBlock(wrap, from._r, from._c, td._r, td._c);
  };
  const up = () => {
    document.removeEventListener("mousemove", move, true);
    document.removeEventListener("mouseup", up, true);
  };
  document.addEventListener("mousemove", move, true);
  document.addEventListener("mouseup", up, true);
}

// ---- column widths (user 2026-11-09) -----------------------------------------------------------
// Drag any cell's side border. Widths are view state, never in the markdown: Python keeps them
// per note in .paper-pile/table_widths.json (core/table_widths.py), keyed by the header cells,
// and sends them all once (`setTableWidths`).

const widthKey = (header) => header.map((h) => h.trim()).join("|");

function storedWidths(view, header, cols) {
  const path = view ? rtOf(view.state).notePath : "";
  const w = editorContext.tableWidths?.[path]?.[widthKey(header)];
  return Array.isArray(w) && w.length === cols ? w : null;
}

function applyWidths(table, widths) {
  let group = table.querySelector("colgroup");
  if (!group) group = table.insertBefore(el("colgroup"), table.firstChild);
  group.replaceChildren(...widths.map((w) => Object.assign(el("col"), { style: `width: ${w}px` })));
  table.style.width = `${widths.reduce((a, b) => a + b, 0)}px`;
  table.classList.add("pp-table-sized");
}

// the column whose right border is under the pointer, or null
function edgeAt(wrap, e) {
  const td = e.target.closest && e.target.closest("td, th");
  if (!td || !wrap.contains(td) || td._c === undefined) return null;
  const box = td.getBoundingClientRect();
  if (e.clientX >= box.right - EDGE_PX) return td._c;
  if (e.clientX <= box.left + EDGE_PX && td._c > 0) return td._c - 1;
  return null;
}

function startResize(wrap, col, x0) {
  const table = wrap.querySelector("table");
  const widths = (wrap._cells[0] || []).map((th) => th.getBoundingClientRect().width);
  const w0 = widths[col];
  commitActive(wrap);
  wrap._resizing = true;
  wrap.classList.add("pp-table-colresize");
  document.body.classList.add("pp-colresizing");
  applyWidths(table, widths);
  const move = (e) => {
    widths[col] = Math.max(MIN_COL_PX, w0 + e.clientX - x0);
    applyWidths(table, widths);
  };
  const up = () => {
    document.removeEventListener("mousemove", move, true);
    document.removeEventListener("mouseup", up, true);
    wrap._resizing = false;
    document.body.classList.remove("pp-colresizing");
    const view = wrap._view;
    if (!view) return;
    const rt = rtOf(view.state);
    const key = widthKey(wrap._cells[0].map((th) => th._value ?? ""));
    const rounded = widths.map((w) => Math.round(w));
    editorContext.tableWidths = editorContext.tableWidths || {};
    (editorContext.tableWidths[rt.notePath] ??= {})[key] = rounded;
    rt.emit("table_widths", { path: rt.notePath, key, widths: rounded });
    measureAgain(view); // rows may wrap to more lines now
  };
  document.addEventListener("mousemove", move, true);
  document.addEventListener("mouseup", up, true);
}
