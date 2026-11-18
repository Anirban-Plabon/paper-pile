// Typesets rendered markdown that lives outside the editor (the AI chat): KaTeX for
// `<span class="math inline">` / `<div class="math block">` (what Python's markdown parser writes)
// and Mermaid for ```mermaid blocks. Links are made inert here; Python decides what may open.
import { renderTexInto } from "./tex.js";
import { renderMermaid } from "./mermaidrender.js";

// KaTeX for the `.math` elements under `root` (also used by embedded notes, which handle their own
// clicks)
export function typesetMath(root) {
  for (const el of root.querySelectorAll(".math:not([data-typeset])")) {
    el.dataset.typeset = "1";
    try {
      renderTexInto(el, el.textContent, el.classList.contains("block"));
    } catch {
      /* leave the source text */
    }
  }
}

export async function typeset(root, theme = "light") {
  if (!root) return;
  typesetMath(root);
  for (const code of root.querySelectorAll("pre > code.language-mermaid:not([data-typeset])")) {
    code.dataset.typeset = "1";
    const pre = code.parentElement;
    try {
      const svg = await renderMermaid(code.textContent.trim(), theme);
      const box = document.createElement("div");
      box.className = "pp-chat-diagram";
      box.innerHTML = svg;
      pre.replaceWith(box);
    } catch {
      /* not valid mermaid: keep it as code */
    }
  }
  if (!root.dataset.linksHandled) {
    root.dataset.linksHandled = "1";
    root.addEventListener("click", (e) => {
      const a = e.target.closest && e.target.closest("a[href]");
      if (!a) return;
      e.preventDefault();
      const href = a.getAttribute("href") || "";
      if (/^https?:\/\//i.test(href) && window.emitEvent) window.emitEvent("pp_open_url", href);
    });
  }
}
