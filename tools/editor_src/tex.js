// One way to typeset TeX for every view (editor widgets, table cells, chat, print page), so a
// formula never renders in one place and fails in another.
//
// KaTeX lacks some LaTeX that notes and AI answers use a lot. What has a faithful KaTeX spelling is
// mapped to it here; anything else still shows KaTeX's red source text (never a thrown error).
// tools/editor_src/check_tex.mjs renders tests/fixtures/tex_cases.json with these options.
import katex from "katex";
import "katex/contrib/mhchem"; // \ce{H2O}, \pu{5 m}: chemistry (registers itself on katex)

// a macro that reads `n` arguments and writes nothing (`\label{eq:1}` only names an equation)
const drop = (n) => (ctx) => {
  ctx.consumeArgs(n);
  return "";
};

const MACROS = {
  "\\label": drop(1),
  "\\require": drop(1), // MathJax's extension loader
  "\\eqref": "(\\text{#1})",
  "\\ref": "\\text{#1}",
  "\\DeclareMathOperator": "\\newcommand{#1}{\\operatorname{#2}}",
  "\\mathbbm": "\\mathbb{#1}",
  "\\mathds": "\\mathbb{#1}",
  "\\abs": "\\left\\lvert #1\\right\\rvert",
  "\\norm": "\\left\\lVert #1\\right\\rVert",
  "\\textsc": "\\text{#1}",
  "\\mbox": "\\text{#1}",
  "\\hdots": "\\ldots",
  "\\C": "\\mathbb{C}",
};

// environments KaTeX does not know -> the nearest one it does
const DISPLAY_ENVS = [
  [/\\(begin|end)\{multline(\*?)\}/g, "\\$1{gather$2}"],
  [/\\(begin|end)\{flalign(\*?)\}/g, "\\$1{align$2}"],
  [/\\begin\{eqnarray\*?\}/g, "\\begin{array}{rcl}"],
  [/\\end\{eqnarray\*?\}/g, "\\end{array}"],
  [/\\(begin|end)\{subequations\}/g, ""],
];
// display-only environments written inside inline math -> their inline form
const INLINE_ENVS = [
  [/\\(begin|end)\{(?:align|flalign|eqnarray)\*?\}/g, "\\$1{aligned}"],
  [/\\(begin|end)\{(?:gather|multline)\*?\}/g, "\\$1{gathered}"],
  [/\\(begin|end)\{equation\*?\}/g, ""],
];

export function texSource(src, displayMode) {
  let out = src;
  for (const [re, to] of DISPLAY_ENVS) out = out.replace(re, to);
  if (!displayMode) for (const [re, to] of INLINE_ENVS) out = out.replace(re, to);
  return out;
}

export function texOptions(displayMode) {
  // a fresh macro table per formula: \newcommand inside one formula must not leak into the next
  return { displayMode, throwOnError: false, strict: "ignore", macros: { ...MACROS } };
}

export function renderTex(src, displayMode = false) {
  return katex.renderToString(texSource(src, displayMode), texOptions(displayMode));
}

export function renderTexInto(el, src, displayMode = false) {
  katex.render(texSource(src, displayMode), el, texOptions(displayMode));
}
