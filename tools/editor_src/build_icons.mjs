// Writes every Lucide icon's inner SVG markup to one JSON file that Python reads
// (paper_pile/gui/icons.py). Dev-only, run by tools/build_editor.sh; the output is committed.
import { readFileSync, readdirSync, writeFileSync, mkdirSync, copyFileSync } from "node:fs";
const src = "node_modules/lucide-static";
const out = "../../paper_pile/gui/static/vendor/lucide";
const version = JSON.parse(readFileSync(`${src}/package.json`, "utf8")).version;
const icons = {};
for (const file of readdirSync(`${src}/icons`).sort()) {
  if (!file.endsWith(".svg")) continue;
  const svg = readFileSync(`${src}/icons/${file}`, "utf8");
  const inner = svg.slice(svg.indexOf(">", svg.indexOf("<svg")) + 1, svg.lastIndexOf("</svg>"));
  icons[file.slice(0, -4)] = inner.replace(/\s*\n\s*/g, "").trim();
}
mkdirSync(out, { recursive: true });
writeFileSync(`${out}/icons.json`, JSON.stringify({ version, icons }));
copyFileSync(`${src}/LICENSE`, `${out}/LICENSE`);
console.log(`lucide ${version}: ${Object.keys(icons).length} icons`);
