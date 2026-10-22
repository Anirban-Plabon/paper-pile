// The print page (`/_pp/print/<key>`, built by paper_pile/core/printdoc.py): typesets the note
// with the editor's own code (KaTeX, Mermaid), lays it out on sheets (paginate.js) and reports the
// pages in `window.ppPrint`. Used three ways: in a hidden frame of the editor's page (page view's
// page lines), by the native window's PDF export (Qt prints the page), and in web mode with
// `?mode=print`, where it opens the browser's print dialog.
import katex from "katex";
import { renderMermaid } from "./mermaidrender.js";
import { paginate } from "./paginate.js";

const IMAGE_WAIT_MS = 8000;

// Numbered items keep their numbers when a list is cut between pages.
function numberItems(doc) {
  for (const ol of doc.querySelectorAll("#pp-source ol")) {
    let n = ol.start || 1;
    for (const li of ol.children) if (li.tagName === "LI") li.value = n++;
  }
}

// An item with text and then a nested list: its text becomes a block of its own, so the item can be
// cut between its text and the nested items.
const ITEM_BLOCKS = new Set(["UL", "OL", "P", "PRE", "BLOCKQUOTE", "TABLE", "DIV"]);

function wrapItemText(doc) {
  for (const li of doc.querySelectorAll("#pp-source li")) {
    if (![...li.children].some((c) => ITEM_BLOCKS.has(c.tagName))) continue;
    const lead = [];
    for (const node of li.childNodes) {
      if (node.nodeType === 1 && ITEM_BLOCKS.has(node.tagName)) break;
      lead.push(node);
    }
    if (!lead.some((n) => n.textContent.trim() || n.nodeName === "IMG" || n.nodeName === "INPUT")) continue;
    const box = doc.createElement("div");
    box.className = "pp-li-text";
    box.dataset.line = li.dataset.line || "";
    li.insertBefore(box, lead[0]);
    box.append(...lead);
  }
}

function typesetMath(doc) {
  for (const el of doc.querySelectorAll("#pp-source .math")) {
    try {
      katex.render(el.textContent, el, { displayMode: el.classList.contains("block"), throwOnError: false });
    } catch {
      /* leave the TeX */
    }
  }
}

async function drawDiagrams(doc) {
  for (const code of doc.querySelectorAll("#pp-source pre > code.language-mermaid")) {
    const pre = code.parentElement;
    try {
      const svg = await renderMermaid(code.textContent.trim(), "light");
      const box = doc.createElement("div");
      box.className = "pp-diagram";
      box.dataset.line = code.dataset.line || pre.dataset.line || "";
      box.innerHTML = svg;
      pre.replaceWith(box);
    } catch {
      /* not valid mermaid: printed as code */
    }
  }
}

function imagesLoaded(doc) {
  const waits = [...doc.images].map((img) => (img.complete ? null : img.decode().catch(() => {}))).filter(Boolean);
  const timeout = new Promise((resolve) => setTimeout(resolve, IMAGE_WAIT_MS));
  return Promise.race([Promise.all(waits), timeout]);
}

async function run() {
  const doc = document;
  numberItems(doc);
  wrapItemText(doc);
  typesetMath(doc);
  await drawDiagrams(doc);
  await imagesLoaded(doc);
  await doc.fonts.ready;
  const pages = paginate(doc);
  return { done: true, pages };
}

window.ppPrintReady = run().then(
  (result) => (window.ppPrint = result),
  (err) => (window.ppPrint = { done: true, pages: [], error: String(err && err.stack ? err.stack : err) }),
);

if (new URLSearchParams(location.search).get("mode") === "print") {
  window.ppPrintReady.then(() => window.print());
}
