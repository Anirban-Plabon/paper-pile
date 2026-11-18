// Renders every formula of tests/fixtures/tex_cases.json the way the app does (tex.js: macros,
// environment fallbacks, mhchem) and fails if KaTeX cannot typeset one. Run by
// tests/core/test_tex_render.py and tools/build_editor.sh.
import fs from "node:fs";
import katex from "katex";
import { texOptions, texSource } from "./tex.js";

const cases = JSON.parse(fs.readFileSync(new URL("../../tests/fixtures/tex_cases.json", import.meta.url), "utf8"));
const failed = [];
for (const c of cases) {
  try {
    // throwOnError: a formula the app would show as red source text fails here
    katex.renderToString(texSource(c.tex, c.display), { ...texOptions(c.display), throwOnError: true });
  } catch (e) {
    failed.push(`${c.name}: ${String(e.message).split("\n")[0]}`);
  }
}
if (failed.length) {
  console.log(`${failed.length} of ${cases.length} formulas do not render:\n  ${failed.join("\n  ")}`);
  process.exit(1);
}
console.log(`all ${cases.length} formulas render`);
