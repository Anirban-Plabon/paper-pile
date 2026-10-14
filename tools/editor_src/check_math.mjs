// Checks the editor's Lezer math grammar (math.js) against tests/fixtures/math_cases.json,
// which is generated from the Python reference parser (paper_pile/core/parser.py).
// Run by tools/build_editor.sh and by tests/core/test_math_sync.py: the two must not drift.
import fs from "node:fs";
import { GFM, parser } from "@lezer/markdown";
import { MathExt } from "./math.js";

const cases = JSON.parse(fs.readFileSync(new URL("../../tests/fixtures/math_cases.json", import.meta.url), "utf8"));
const md = parser.configure([GFM, MathExt]);

// Container prefixes (list indent, "> ") are not part of the formula.
const clean = (s) => s.split("\n").map((l) => l.replace(/^[\s>]+/, "")).join("\n").trim();

function extract(src) {
  const inline = [];
  const block = [];
  md.parse(src).iterate({
    enter(node) {
      if (node.name === "InlineMath") {
        const text = src.slice(node.from, node.to);
        const d = text.startsWith("$$") ? 2 : 1;
        inline.push(text.slice(d, text.length - d));
      } else if (node.name === "BlockMath") {
        const marks = node.node.getChildren("BlockMathMark");
        block.push(clean(src.slice(marks[0].to, marks.length > 1 ? marks[marks.length - 1].from : node.to)));
      }
    },
  });
  return { inline, block };
}

let failed = 0;
for (const c of cases) {
  const got = extract(c.src);
  const same = JSON.stringify(got.inline) === JSON.stringify(c.inline) && JSON.stringify(got.block) === JSON.stringify(c.block);
  if (!same) {
    failed++;
    console.log(`MISMATCH ${c.name}: ${JSON.stringify(c.src)}`);
    console.log(`  python: inline=${JSON.stringify(c.inline)} block=${JSON.stringify(c.block)}`);
    console.log(`  lezer : inline=${JSON.stringify(got.inline)} block=${JSON.stringify(got.block)}`);
  }
}
console.log(failed ? `${failed} of ${cases.length} cases differ` : `all ${cases.length} math cases agree with the Python parser`);
process.exit(failed ? 1 : 0);
