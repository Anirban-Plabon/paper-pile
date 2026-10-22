// The print layout (PLAN §4.17): moves a rendered note (`#pp-source`, written by
// paper_pile/core/printdoc.py) onto sheets of paper. Each sheet is a fixed box exactly one page
// tall, so what is measured here is what prints: the PDF and the editor's page lines come from the
// same sheets. Render-only: the rules below decide where a page ends, nothing else.
//
// Rules:
//   * pages break only between source lines (never inside a wrapped line): every block carries its
//     source line (`data-line`), each <br> in a paragraph is one more line, code lines and table
//     rows are one line each, so every page start is an exact line of the note;
//   * a manual page break (`.pp-page-break`) starts a new sheet;
//   * empty lines are space (`.pp-blank`, one line each), but never at the top of a sheet after the
//     first: text pushed down with Enter starts at the top of its page;
//   * a heading stays with what follows it;
//   * code, tables, quotes/callouts, math, diagrams, images and embeds are not split unless one is
//     taller than a page (then code splits between lines, tables between rows with the header
//     repeated, quotes between their blocks; pictures are scaled down to fit);
//   * paragraphs and lists split between lines / items, keeping 2 lines on each side when they can.

const MIN_LINES = 2;
const EPS = 0.5; // px of rounding allowed at the bottom of a sheet
const HEADINGS = new Set(["H1", "H2", "H3", "H4", "H5", "H6"]);
const WHOLE_TAGS = new Set(["PRE", "TABLE", "BLOCKQUOTE", "HR", "IMG", ...HEADINGS]);
const WHOLE_CLASSES = ["math", "pp-diagram", "pp-embed"];
const BLOCK_TAGS = new Set(["P", "UL", "OL", "PRE", "BLOCKQUOTE", "TABLE", "DIV", ...HEADINGS]);

const isHeading = (el) => HEADINGS.has(el.tagName);
const isBlank = (el) => el.classList.contains("pp-blank");
const pictureOnly = (el) => el.tagName === "P" && el.children.length > 0 && [...el.childNodes].every((n) => n.nodeName === "IMG" || (n.nodeType === 3 && !n.textContent.trim()));
const keepWhole = (el) => WHOLE_TAGS.has(el.tagName) || WHOLE_CLASSES.some((c) => el.classList.contains(c)) || pictureOnly(el);

// The source line an element starts on (its own, else its first marked descendant's).
export function lineOf(el) {
  if (el.dataset && el.dataset.line) return Number(el.dataset.line);
  const marked = el.querySelector && el.querySelector("[data-line]");
  return marked ? Number(marked.dataset.line) : 0;
}

class Book {
  constructor(doc) {
    this.doc = doc;
    this.sheets = [];
    this.newSheet();
  }

  newSheet() {
    const sheet = this.doc.createElement("section");
    sheet.className = "pp-sheet";
    this.body = this.doc.createElement("div");
    this.body.className = "pp-sheet-body";
    const foot = this.doc.createElement("div");
    foot.className = "pp-sheet-foot";
    sheet.append(this.body, foot);
    this.doc.body.insertBefore(sheet, this.doc.getElementById("pp-source"));
    this.sheets.push(sheet);
  }

  bottom() {
    return this.body.getBoundingClientRect().bottom + EPS;
  }

  fits(el) {
    return el.getBoundingClientRect().bottom <= this.bottom();
  }

  // Nothing but headings (carried along with the block that follows them) and empty lines on this
  // sheet so far.
  fresh() {
    return [...this.body.children].every((c) => isHeading(c) || isBlank(c));
  }

  place(el) {
    if (el.classList.contains("pp-page-break")) {
      el.remove();
      if (this.body.firstElementChild) this.newSheet();
      return;
    }
    if (isBlank(el)) {
      // empty lines: dropped at the top of a sheet (after the first) and where they do not fit
      if (this.sheets.length > 1 && !this.body.firstElementChild) return el.remove();
      this.body.appendChild(el);
      if (!this.fits(el)) {
        el.remove();
        this.newSheet();
      }
      return;
    }
    const fresh = this.fresh();
    this.body.appendChild(el);
    if (this.fits(el)) return;
    if (!fresh && keepWhole(el)) return this.moveOn(el);
    const tail = split(el, this, fresh ? 1 : MIN_LINES, false);
    if (tail) {
      this.newSheet();
      return this.place(tail);
    }
    if (!fresh) return this.moveOn(el);
    // alone on its sheet and still too tall
    shrink(el, this);
    if (this.fits(el)) return;
    const forced = split(el, this, 1, true);
    if (forced) {
      this.newSheet();
      this.place(forced);
    }
    // else: one thing that cannot be cut, taller than a page: it is clipped
  }

  // `el` goes to the next sheet, with the headings right above it.
  moveOn(el) {
    el.remove();
    while (this.body.lastElementChild && isBlank(this.body.lastElementChild)) this.body.lastElementChild.remove();
    const carried = [];
    let last = this.body.lastElementChild;
    while (last && isHeading(last) && last.previousElementSibling) {
      carried.unshift(last);
      last = last.previousElementSibling;
    }
    for (const h of carried) h.remove();
    this.newSheet();
    for (const h of carried) this.body.appendChild(h);
    this.place(el);
  }
}

// Cut `el` so that it ends on this sheet; returns the rest (a detached copy holding the remainder),
// or null when no allowed cut leaves at least `minHead` lines here. `force`: also cut what is
// normally kept whole (it is taller than a page).
function split(el, book, minHead, force) {
  if (keepWhole(el) && !force) return null;
  const tag = el.tagName;
  if (tag === "PRE") return splitCode(el, book);
  if (tag === "TABLE") return splitTable(el, book);
  if (tag === "UL" || tag === "OL" || tag === "BLOCKQUOTE" || hasBlocks(el)) return splitContainer(el, book, minHead, force);
  if (tag === "P" || tag === "LI") return splitLines(el, book, minHead);
  return null;
}

const hasBlocks = (el) => [...el.children].some((c) => BLOCK_TAGS.has(c.tagName));

// Where each source line of `el` ends on screen: the bottom of the text up to each <br>.
function lineBottoms(el, brs) {
  const doc = el.ownerDocument;
  const out = [];
  let from = null;
  for (const br of brs) {
    const r = doc.createRange();
    if (from) r.setStartAfter(from);
    else r.setStart(el, 0);
    r.setEndBefore(br);
    let bottom = 0;
    for (const rect of r.getClientRects()) bottom = Math.max(bottom, rect.bottom);
    if (!bottom) bottom = br.getBoundingClientRect().bottom; // an empty line
    out.push(bottom);
    from = br;
  }
  return out;
}

// A paragraph (or list item) of several source lines: keep as many whole lines as fit.
function splitLines(el, book, minHead) {
  const brs = [...el.querySelectorAll("br")];
  const total = brs.length + 1;
  if (total < 2) return null;
  const minTail = minHead > 1 ? MIN_LINES : 1;
  const limit = book.bottom();
  let keep = 0;
  for (const bottom of lineBottoms(el, brs)) {
    if (bottom > limit) break;
    keep++;
  }
  keep = Math.min(keep, total - minTail);
  if (keep < minHead) return null;
  const cut = brs[keep - 1];
  const r = el.ownerDocument.createRange();
  r.setStartAfter(cut);
  r.setEndAfter(el.lastChild);
  const rest = r.extractContents();
  cut.remove();
  const tail = el.cloneNode(false);
  tail.appendChild(rest);
  tail.dataset.line = String(lineOf(el) + keep);
  return tail;
}

// A list, a quote, or an item holding blocks: keep the children that fit, cut the first one that
// does not (if it can be cut), and move the rest.
function splitContainer(el, book, minHead, force) {
  const kids = [...el.children];
  const limit = book.bottom();
  const i = kids.findIndex((c) => c.getBoundingClientRect().bottom > limit);
  if (i < 0) return null;
  const childTail = split(kids[i], book, i === 0 ? minHead : MIN_LINES, force);
  if (!childTail && i === 0) return null;
  const tail = el.cloneNode(false);
  if (childTail) {
    if (childTail.tagName === "LI") childTail.classList.add("pp-cont"); // the item goes on: no new bullet
    tail.append(childTail, ...kids.slice(i + 1));
  } else {
    tail.append(...kids.slice(i));
  }
  tail.dataset.line = String(lineOf(tail.firstElementChild));
  return tail;
}

// Code taller than a page: as many lines as fit (each code line is one source line).
function splitCode(pre, book) {
  const code = pre.querySelector("code") ?? pre;
  const lines = code.textContent.replace(/\n$/, "").split("\n");
  if (lines.length < 2) return null;
  const first = Number(code.dataset.codeLine || pre.dataset.codeLine || lineOf(pre));
  const show = (n) => {
    code.textContent = lines.slice(0, n).join("\n") + "\n";
  };
  let lo = 0;
  let hi = lines.length - 1; // the largest count that fits, at least one line moves on
  while (lo < hi) {
    const mid = Math.ceil((lo + hi) / 2);
    show(mid);
    if (book.fits(pre)) lo = mid;
    else hi = mid - 1;
  }
  if (lo < 1) {
    show(lines.length);
    return null;
  }
  show(lo);
  const tail = pre.cloneNode(true);
  const tailCode = tail.querySelector("code") ?? tail;
  tailCode.textContent = lines.slice(lo).join("\n") + "\n";
  tailCode.dataset.codeLine = String(first + lo);
  tail.dataset.line = String(first + lo);
  return tail;
}

// A table taller than a page: whole rows; the rest gets the header again.
function splitTable(table, book) {
  const body = table.tBodies[0];
  if (!body) return null;
  const rows = [...body.rows];
  const limit = book.bottom();
  const i = rows.findIndex((r) => r.getBoundingClientRect().bottom > limit);
  if (i <= 0) return null;
  const tail = table.cloneNode(false);
  if (table.tHead) tail.appendChild(table.tHead.cloneNode(true));
  const rest = body.cloneNode(false);
  rest.append(...rows.slice(i));
  tail.appendChild(rest);
  tail.dataset.line = rows[i].dataset.line || String(lineOf(rows[i]));
  return tail;
}

// Something that cannot be cut is taller than the sheet: scale its pictures (or itself) down.
function shrink(el, book) {
  const room = book.bottom() - el.getBoundingClientRect().top - EPS;
  if (room <= 0) return;
  for (const pic of el.querySelectorAll("img, svg")) {
    pic.style.maxHeight = `${Math.floor(room)}px`;
    pic.style.width = "auto";
  }
  if (el.tagName === "IMG") el.style.maxHeight = `${Math.floor(room)}px`;
  const height = el.getBoundingClientRect().height;
  if (height > room) el.style.zoom = String(Math.max(0.2, room / height));
}

// Lay out the note; returns the pages: where each starts in the note and its text.
export function paginate(doc = document) {
  const source = doc.getElementById("pp-source");
  const book = new Book(doc);
  for (const el of [...source.children]) book.place(el);
  source.remove();
  const total = book.sheets.length;
  const pages = book.sheets.map((sheet, i) => {
    sheet.querySelector(".pp-sheet-foot").textContent = total > 1 ? String(i + 1) : "";
    const body = sheet.querySelector(".pp-sheet-body");
    return { page: i + 1, line: body.firstElementChild ? lineOf(body.firstElementChild) : 0, text: body.innerText };
  });
  return pages;
}
