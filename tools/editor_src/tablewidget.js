// Tables in Live Preview: a real <table> whose cells can be typed into.
//
// JS only draws and captures. Every rule about what an edit does to the markdown (escaping, column
// padding, adding/deleting/moving rows and columns, alignment) lives in Python (core/tables.py):
// the widget sends `table_op {docId, from, to, op}` and Python answers by editing the document,
// after which the widget patches its DOM in place (focus and caret in the cell being typed in are
// kept). A cell shows rendered markdown until it is focused, then an <input> with its raw value.
import { undo, redo, isolateHistory } from "@codemirror/commands";
import { syntaxTree } from "@codemirror/language";
import { Prec } from "@codemirror/state";
import { WidgetType, keymap } from "@codemirror/view";
import { renderInline } from "./widgets.js";
import { rtOf, editorContext, measureAgain } from "./context.js";
import { clearSelection, reportSelection } from "./selectpopup.js";
import { setBlockAlign } from "./align.js";

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
  // GFM: the header row decides the columns; a row's extra cells are not part of the table
  // (Python's renderer and core/tables.py read it the same way)
  const cols = rows.length && rows[0].length ? rows[0].length : aligns.length;
  for (const r of rows) {
    r.length = Math.min(r.length, cols);
    while (r.length < cols) r.push({ node: null, value: "" });
  }
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

// Align the whole table like any block (align.js: own undo step, saved by Python).
function alignTable(wrap, align) {
  const view = wrap._view;
  const range = view && tableRange(view, wrap);
  if (!range) return;
  view.dispatch({ effects: setBlockAlign.of({ ranges: [range], align }), annotations: isolateHistory.of("full") });
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
    installHandles(view);
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
    wrap._widget = this; // the latest parse: a cell left after editing renders from it (endEdit)
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
    wrap._widget = this;
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
        reportBlock(wrap);
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
      if (wrap.contains(e.relatedTarget)) return;
      if (inAskBox(e.relatedTarget)) keepForAskBox(wrap); // asking about the block: it stays shown
      else clearBlock(wrap, false);
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
  // the input is one line: the cell keeps the height it had (a wrapped cell would shrink the row,
  // and everything under the table — in page view the page edges too — would move)
  const cs = getComputedStyle(td);
  const inner = td.getBoundingClientRect().height - ["paddingTop", "paddingBottom", "borderTopWidth", "borderBottomWidth"].reduce((a, k) => a + (parseFloat(cs[k]) || 0), 0);
  td.style.height = `${Math.max(0, inner)}px`; // a cell's CSS height is its content box
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
  input.addEventListener("blur", (e) => {
    clearTimeout(timer);
    commit(wrap, td);
    const [start, end] = [input.selectionStart, input.selectionEnd];
    const asked = inAskBox(e.relatedTarget) && start !== end && input.value === td._value;
    endEdit(wrap, td);
    if (asked) {
      // the Ask box took the caret to ask about text in this cell: that text stays highlighted
      markAsked(td, start, end);
      keepForAskBox(wrap, () => {
        if (!td._input && td.querySelector(".pp-table-asked")) renderCell(wrap, td);
      });
    }
  });
  input.addEventListener("keydown", (e) => onKey(e, wrap, td));
  // text selected in the cell (double-click a word, drag, Shift+arrows): the Ask box, as in text
  const select = () => setTimeout(() => reportCellText(wrap, td, input), 0);
  for (const type of ["mouseup", "keyup", "select"]) input.addEventListener(type, select);
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
  td.style.height = "";
  if (wrap._active === td) wrap._active = null;
  renderCell(wrap, td);
}

// The cell rendered (math, code, links) when the latest parse already holds its value: nothing
// was changed, or Python's answer came while the cell was still being typed in (that patch
// skipped it). Otherwise plain until the patch with Python's answer re-renders it.
function renderCell(wrap, td) {
  const widget = wrap._widget;
  const cell = widget && widget.data.rows[td._r] && widget.data.rows[td._r][td._c];
  if (cell && cell.value === td._value) {
    td._stale = false;
    showValue(td, widget.state, cell.node, cell.value);
  } else {
    td.replaceChildren(document.createTextNode(td._value));
  }
}

// While the Ask box is about text in a cell: the cell's text as it was selected, with exactly the
// asked part highlighted like the note's own Ask target (class pp-ai-band).
function markAsked(td, start, end) {
  const value = td._value;
  const mark = el("span", "pp-ai-band pp-table-asked", value.slice(start, end));
  td.replaceChildren(document.createTextNode(value.slice(0, start)), mark, document.createTextNode(value.slice(end)));
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
  if (c >= 1) items.push(["Move column left", run({ op: "move_col", col: c, to: c - 1 }, r, c - 1)]);
  if (c < C - 1) items.push(["Move column right", run({ op: "move_col", col: c, to: c + 1 }, r, c + 1)]);
  if (C > 1) items.push(["Delete column", run({ op: "delete_col", col: c })]);
  items.push(null);
  // the column's markdown alignment (`:---:`) — its cells only
  for (const [label, align] of [["Align column left", "left"], ["Align column center", "center"], ["Align column right", "right"], ["Column: no alignment", ""]]) {
    items.push([label, run({ op: "align", col: c, align })]);
  }
  items.push(null);
  // the whole table as a block (PLAN §4.34): the caret cannot stand in a table for /align-…
  for (const [label, align] of [["Align table left", "left"], ["Align table center", "center"], ["Align table right", "right"]]) {
    items.push([label, () => alignTable(wrap, align)]);
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

// `kind`: "row" / "col" when whole rows / columns were picked with their handle (Delete and
// Backspace then remove them), else a block of cells (the keys empty them).
function selectBlock(wrap, r0, c0, r1, c1, kind = null) {
  const R = wrap._cells.length;
  const C = wrap._cells[0].length;
  const clamp = (v, n) => Math.max(0, Math.min(n - 1, v));
  wrap._sel = { r0: clamp(r0, R), c0: clamp(c0, C), r1: clamp(r1, R), c1: clamp(c1, C), kind };
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
  paintHandles(wrap);
}

// `report`: also tell the Ask box the block is gone (not when the focus merely left the table —
// that is the user clicking into the box to ask about the block)
function clearBlock(wrap, report = true) {
  if (!wrap._sel) return;
  wrap._sel = null;
  paintBlock(wrap);
  if (report && wrap._view) clearSelection(wrap._view);
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

const span = (a, b) => Array.from({ length: b - a + 1 }, (_, i) => a + i);

// Delete / Backspace on a selection: picked rows / columns go (Python decides what that means:
// the header's place is taken by the next row; deleting all of them removes the table), a block of
// cells is emptied.
function deleteBlock(wrap) {
  const sel = wrap._sel;
  if (!sel) return;
  const b = blockBox(sel);
  if (sel.kind === "row" || sel.kind === "col") {
    const op = sel.kind === "row" ? { op: "delete_rows", rows: span(b.top, b.bottom) } : { op: "delete_cols", cols: span(b.left, b.right) };
    clearBlock(wrap);
    sendOp(wrap, op);
    return;
  }
  clearCells(wrap);
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
    deleteBlock(wrap);
  } else if (arrows[e.key] && e.shiftKey) {
    e.preventDefault();
    const [dr, dc] = arrows[e.key];
    // whole rows grow up / down, whole columns left / right; anything else makes a block of cells
    if (sel.kind === "row" && dr) selectBlock(wrap, sel.r0, sel.c0, sel.r1 + dr, sel.c1, "row");
    else if (sel.kind === "col" && dc) selectBlock(wrap, sel.r0, sel.c0, sel.r1, sel.c1 + dc, "col");
    else selectBlock(wrap, sel.r0, sel.c0, sel.r1 + dr, sel.c1 + dc);
    reportBlock(wrap);
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
    if (wrap._sel) reportBlock(wrap);
  };
  document.addEventListener("mousemove", move, true);
  document.addEventListener("mouseup", up, true);
}

// ---- the Ask box for selections inside the table -----------------------------------------------
// The editor's own selection never enters a table, so the table reports its selections itself
// (selectpopup.js `reportSelection`), as places in the note read from the current syntax tree.

function liveRows(wrap) {
  const view = wrap._view;
  if (!view) return null;
  let node = syntaxTree(view.state).resolveInner(view.posAtDOM(wrap), 1);
  while (node && node.name !== "Table") node = node.parent;
  if (!node) return null;
  const head = node.getChild("TableHeader");
  return [...(head ? [head] : []), ...node.getChildren("TableRow")];
}

// Text selected in the input of cell `td`: its place in the note. Only while the input shows what
// the note holds (typed text not sent yet has no place in the note).
function reportCellText(wrap, td, input) {
  const view = wrap._view;
  if (!view || td._input !== input) return;
  const start = input.selectionStart;
  const end = input.selectionEnd;
  if (start === null || end === null) return;
  if (start === end) return clearSelection(view); // a caret, no selection: as a click in text
  if (input.value !== input._original) return;
  const row = liveRows(wrap)?.[td._r];
  const cell = row && row.getChildren("TableCell")[td._c];
  if (!cell) return;
  const raw = view.state.sliceDoc(cell.from, cell.to);
  const lead = raw.length - raw.trimStart().length;
  // value offset -> note offset (`\|` in the note is one `|` in the value)
  const at = [];
  for (let i = lead; i < raw.trimEnd().length; i++) {
    at.push(i);
    if (raw[i] === "\\" && raw[i + 1] === "|") i++;
  }
  at.push(raw.trimEnd().length);
  if (at.length - 1 !== input.value.length) return; // not the same text: leave it
  const r = input.getBoundingClientRect();
  reportSelection(view, cell.from + at[start], cell.from + at[end], { left: r.left, top: r.top, bottom: r.bottom });
}

// the Ask box, or the formatting menu its Format button opens (its Copy / Cut / Delete are for
// the block, so the block stays selected while it is open)
const inAskBox = (el) => !!(el && el.closest && el.closest(".pp-askpop, .pp-fmenu"));

// The Ask box took the focus to ask about a selection in this table: the block stays painted
// until the user goes on elsewhere (a click or the focus outside the box).
function keepForAskBox(wrap, done = () => clearBlock(wrap, false)) {
  const away = (e) => {
    if (inAskBox(e.target)) return;
    document.removeEventListener("mousedown", away, true);
    document.removeEventListener("focusin", away, true);
    // a click in the table (or on its row / column grips) handles itself
    if (!wrap.contains(e.target) && !(e.target.closest && e.target.closest(".pp-thandles"))) done();
  };
  document.addEventListener("mousedown", away, true);
  document.addEventListener("focusin", away, true);
}

// A block of cells: the rows it covers, whole lines (a column block is not one piece of text).
function reportBlock(wrap) {
  const view = wrap._view;
  const rows = liveRows(wrap);
  if (!view || !wrap._sel || !rows) return;
  const b = blockBox(wrap._sel);
  if (!rows[b.top] || !rows[b.bottom]) return;
  const doc = view.state.doc;
  const tl = wrap._cells[b.top][b.left].getBoundingClientRect();
  const br = wrap._cells[b.bottom][b.right].getBoundingClientRect();
  reportSelection(view, doc.lineAt(rows[b.top].from).from, doc.lineAt(rows[b.bottom].to).to, { left: tl.left, top: tl.top, bottom: br.bottom });
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

// ---- the selected block from outside the table (the Ask box, the formatting menu) --------------
// With the AI on, the Ask box opens over a block a moment after it is selected and takes the
// focus. The keys and edit items meant for the block come back here (askpop.js, `clipboard` in
// index.js): copy / cut / paste give the table the focus before the browser acts, Delete goes to
// `deleteBlock`.

function selectedBlock(root = document) {
  for (const w of root.querySelectorAll(".pp-table-edit.pp-table-block")) if (w._sel && w.isConnected) return w;
  return null;
}

// `op`: copy / cut / paste / delete. True when a block was there to take it. Copy and cut go
// through the browser's own copy (`copyBlock` fills the clipboard); paste reads the clipboard.
export async function blockClipboard(op, root = document) {
  const wrap = selectedBlock(root);
  if (!wrap) return false;
  wrap.focus({ preventScroll: true });
  if (op === "copy" || op === "cut") {
    // with no text selected the browser's copy event goes to <body>, not to the table: catch it
    // there for this one copy (a cut is a copy, then the cells are emptied)
    const once = (e) => copyBlock(e, wrap, op === "cut");
    document.addEventListener("copy", once, true);
    try {
      document.execCommand("copy");
    } finally {
      document.removeEventListener("copy", once, true);
    }
  } else if (op === "delete") {
    deleteBlock(wrap);
  } else if (op === "paste") {
    let text = "";
    try {
      text = await navigator.clipboard.readText();
    } catch (_) {
      return true; // no clipboard access here: Ctrl+V into the table still works
    }
    if (!text) return true;
    const b = blockBox(wrap._sel);
    sendOp(wrap, { op: "paste", row: b.top, col: b.left, text });
  }
  return true;
}

window.ppTableBlock = {
  // Ctrl+C / X / V in the Ask box: the table takes the focus now, the browser then acts on it
  focus() {
    const wrap = selectedBlock();
    if (wrap) wrap.focus({ preventScroll: true });
    return !!wrap;
  },
  run: (op) => blockClipboard(op),
  active: () => !!selectedBlock(),
};

// ---- row and column handles, + between rows / columns (user 2026-11-26) -----------------------
// Over the table the pointer's row gets a grip at the table's left edge and its column one on the
// top edge. Click a grip: that row / column is selected (Shift+click: up to it); then Delete or
// Backspace removes it, Copy copies it. Drag a grip: the row / column moves where the line shows.
// Near the line between two rows (at the left edge) or two columns (at the top edge) a + appears
// that inserts one there. One overlay per editor, in the editor's own box (the table's box clips
// what sticks out of it); it follows the pointer and hides on scroll.

const GRIP_ZONE_X = 34; // px left of the table's left edge where its row grips stay shown
const GRIP_ZONE_Y = 28; // px above the table's top edge where its column grips stay shown
const PLUS_SNAP = 8; // px from a row / column line where its + appears
const DRAG_PX = 4; // a grip moved further than this is a drag, not a click

function installHandles(view) {
  const host = view.dom;
  if (host._ppHandles) return;
  const layer = el("div", "pp-thandles");
  const button = (cls, icon, tip) => {
    const b = el("button", `pp-thandle ${cls}`);
    b.type = "button";
    b.tabIndex = -1;
    b.innerHTML = window.ppIconSvg?.(icon, "s") ?? "";
    b.dataset.tip = tip;
    layer.appendChild(b);
    return b;
  };
  const h = {
    layer,
    rowGrip: button("pp-thandle-row", "grip-vertical", "Click to select row · drag to move"),
    colGrip: button("pp-thandle-col", "grip-horizontal", "Click to select column · drag to move"),
    rowPlus: button("pp-thandle-plus", "plus", "Insert row here"),
    colPlus: button("pp-thandle-plus", "plus", "Insert column here"),
    line: layer.appendChild(el("div", "pp-thandle-line")),
    wrap: null,
    row: -1,
    col: -1,
    rowAt: -1, // where the row + inserts (grid index), or -1
    colAt: -1,
    drag: null,
  };
  host._ppHandles = h;
  host.appendChild(layer);
  hideHandles(h);

  host.addEventListener("mousemove", (e) => {
    if (!h.drag) trackHandles(h, host, e);
  });
  host.addEventListener("mouseleave", () => {
    if (!h.drag) hideHandles(h);
  });
  view.scrollDOM.addEventListener("scroll", () => {
    if (!h.drag) hideHandles(h);
  }, { passive: true });

  const plus = (b, which) => {
    b.addEventListener("mouseenter", () => showLine(h, which, which === "row" ? h.rowAt : h.colAt));
    b.addEventListener("mouseleave", () => (h.line.style.display = "none"));
    b.addEventListener("mousedown", (e) => {
      e.preventDefault();
      e.stopPropagation();
      const wrap = h.wrap;
      if (!wrap || !wrap.isConnected) return;
      commitActive(wrap);
      clearBlock(wrap);
      if (which === "row" && h.rowAt >= 1) {
        focusTableCell(h.rowAt, 0);
        sendOp(wrap, { op: "insert_row", at: h.rowAt });
      } else if (which === "col" && h.colAt >= 0) {
        focusTableCell(0, h.colAt);
        sendOp(wrap, { op: "insert_col", at: h.colAt });
      }
      hideHandles(h);
    });
  };
  plus(h.rowPlus, "row");
  plus(h.colPlus, "col");
  h.rowGrip.addEventListener("mousedown", (e) => startGrip(h, host, e, "row"));
  h.colGrip.addEventListener("mousedown", (e) => startGrip(h, host, e, "col"));
}

function hideHandles(h) {
  for (const b of [h.rowGrip, h.colGrip, h.rowPlus, h.colPlus, h.line]) b.style.display = "none";
  h.wrap = null;
  h.row = h.col = h.rowAt = h.colAt = -1;
}

// the rows' and columns' edges on screen: `rows[i] = [top, bottom]`, `cols[j] = [left, right]`
function tableEdges(wrap) {
  const rows = wrap._cells.map((line) => {
    const r = line[0].getBoundingClientRect();
    return [r.top, r.bottom];
  });
  const cols = wrap._cells[0].map((td) => {
    const r = td.getBoundingClientRect();
    return [r.left, r.right];
  });
  return { rows, cols };
}

const place = (node, host, x, y) => {
  node.style.display = "";
  node.style.left = `${x - host.left}px`;
  node.style.top = `${y - host.top}px`;
};

function trackHandles(h, host, e) {
  if (e.target.closest && e.target.closest(".pp-thandles")) return; // on a handle: it stays put
  const x = e.clientX;
  const y = e.clientY;
  let wrap = null;
  let box = null;
  for (const w of host.querySelectorAll(".pp-table-edit")) {
    const t = w.querySelector("table");
    const r = t && t.getBoundingClientRect();
    if (r && x >= r.left - GRIP_ZONE_X && x <= r.right + 4 && y >= r.top - GRIP_ZONE_Y && y <= r.bottom + 4) {
      wrap = w;
      box = r;
      break;
    }
  }
  if (!wrap || !wrap._cells || wrap._resizing) return hideHandles(h);
  const hb = host.getBoundingClientRect();
  const { rows, cols } = tableEdges(wrap);
  const nearest = (edges, v) => {
    const i = edges.findIndex(([a, b]) => v >= a && v <= b);
    return i >= 0 ? i : v < edges[0][0] ? 0 : edges.length - 1;
  };
  h.wrap = wrap;
  h.row = nearest(rows, y);
  h.col = nearest(cols, x);
  const [rt, rb] = rows[h.row];
  const [cl, cr] = cols[h.col];
  // the grips leave the lines free at both ends, for the + there
  h.rowGrip.style.height = `${Math.max(10, Math.min(22, rb - rt - 2 * PLUS_SNAP))}px`;
  h.colGrip.style.width = `${Math.max(10, Math.min(22, cr - cl - 2 * PLUS_SNAP))}px`;
  place(h.rowGrip, hb, box.left - 1, (rt + rb) / 2);
  place(h.colGrip, hb, (cl + cr) / 2, box.top - 1);
  // a + on the line between two rows (not above the header: a table starts with it)
  h.rowAt = -1;
  if (x <= box.left + GRIP_ZONE_X) {
    for (let k = 1; k <= rows.length; k++) {
      const line = k < rows.length ? rows[k][0] : rows[k - 1][1];
      if (Math.abs(y - line) <= PLUS_SNAP) h.rowAt = k;
    }
  }
  if (h.rowAt >= 1) place(h.rowPlus, hb, box.left - 22, h.rowAt < rows.length ? rows[h.rowAt][0] : rows[rows.length - 1][1]);
  else h.rowPlus.style.display = "none";
  h.colAt = -1;
  if (y <= box.top + GRIP_ZONE_Y) {
    for (let k = 0; k <= cols.length; k++) {
      const line = k < cols.length ? cols[k][0] : cols[k - 1][1];
      if (Math.abs(x - line) <= PLUS_SNAP) h.colAt = k;
    }
  }
  if (h.colAt >= 0) place(h.colPlus, hb, h.colAt < cols.length ? cols[h.colAt][0] : cols[cols.length - 1][1], box.top - 20);
  else h.colPlus.style.display = "none";
  if (h.line.dataset.kind !== "drag") h.line.style.display = "none";
  paintHandles(wrap);
}

// the guide line where a row / column would go: row line `at` (grid index of the row that will be
// there) or column line `at`
function showLine(h, which, at) {
  const wrap = h.wrap;
  if (!wrap || at < 0) return;
  const host = wrap._view.dom.getBoundingClientRect();
  const table = wrap.querySelector("table").getBoundingClientRect();
  const { rows, cols } = tableEdges(wrap);
  const s = h.line.style;
  s.display = "";
  if (which === "row") {
    const y = at < rows.length ? rows[at][0] : rows[rows.length - 1][1];
    Object.assign(s, { left: `${table.left - host.left}px`, top: `${y - host.top - 1}px`, width: `${table.width}px`, height: "2px" });
  } else {
    const x = at < cols.length ? cols[at][0] : cols[cols.length - 1][1];
    Object.assign(s, { left: `${x - host.left - 1}px`, top: `${table.top - host.top}px`, width: "2px", height: `${table.height}px` });
  }
}

// the grips of picked rows / columns are drawn picked
function paintHandles(wrap) {
  const h = wrap._view && wrap._view.dom._ppHandles;
  if (!h || h.wrap !== wrap) return;
  const sel = wrap._sel;
  const b = sel && blockBox(sel);
  h.rowGrip.classList.toggle("pp-thandle-on", !!b && sel.kind === "row" && h.row >= b.top && h.row <= b.bottom);
  h.colGrip.classList.toggle("pp-thandle-on", !!b && sel.kind === "col" && h.col >= b.left && h.col <= b.right);
}

function startGrip(h, host, e, which) {
  if (e.button !== 0) return;
  e.preventDefault();
  e.stopPropagation();
  const wrap = h.wrap;
  if (!wrap || !wrap.isConnected) return;
  commitActive(wrap);
  const from = which === "row" ? h.row : h.col;
  const R = wrap._cells.length;
  const C = wrap._cells[0].length;
  const x0 = e.clientX;
  const y0 = e.clientY;
  const pick = (a, b) => (which === "row" ? selectBlock(wrap, a, 0, b, C - 1, "row") : selectBlock(wrap, 0, a, R - 1, b, "col"));
  let target = -1; // the line the row / column is dropped on (grid index), during a drag
  const move = (ev) => {
    if (!h.drag && Math.hypot(ev.clientX - x0, ev.clientY - y0) <= DRAG_PX) return;
    if (!h.drag) {
      h.drag = which;
      h.line.dataset.kind = "drag";
      document.body.classList.add("pp-tdragging");
      pick(from, from);
    }
    const { rows, cols } = tableEdges(wrap);
    const edges = which === "row" ? rows : cols;
    const v = which === "row" ? ev.clientY : ev.clientX;
    target = edges.filter(([a, b]) => v > (a + b) / 2).length; // lines above / left of the pointer
    showLine(h, which, target);
  };
  const up = () => {
    document.removeEventListener("mousemove", move, true);
    document.removeEventListener("mouseup", up, true);
    document.body.classList.remove("pp-tdragging");
    h.line.dataset.kind = "";
    h.line.style.display = "none";
    if (!h.drag) {
      // a click: the row / column is picked (Shift: from the one picked before)
      const sel = wrap._sel;
      const anchor = e.shiftKey && sel && sel.kind === which ? (which === "row" ? sel.r0 : sel.c0) : from;
      pick(anchor, from);
      reportBlock(wrap);
      return;
    }
    h.drag = null;
    const to = target > from ? target - 1 : target;
    if (target < 0 || to === from) return;
    sendOp(wrap, which === "row" ? { op: "move_row", row: from, to } : { op: "move_col", col: from, to });
    pick(to, to); // the same shape: the table is patched in place and the moved one stays picked
    hideHandles(h);
  };
  document.addEventListener("mousemove", move, true);
  document.addEventListener("mouseup", up, true);
}
