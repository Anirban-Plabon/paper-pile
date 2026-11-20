// Checks the editor's Lezer grammar (grammar.js: math, front matter, wikilinks, tags, page breaks) against the shared fixtures
// in tests/fixtures/, which are generated from the Python reference parser
// (paper_pile/core/parser.py). Run by tools/build_editor.sh and tests/core/test_grammar_sync.py:
// the two engines must not drift.
import fs from "node:fs";
import { GFM, parser } from "@lezer/markdown";
import { editorExtensions } from "./grammar.js";
import { blockMathSource } from "./math.js";
import { parseWikilink } from "./wikilink.js";

const load = (name) => JSON.parse(fs.readFileSync(new URL(`../../tests/fixtures/${name}`, import.meta.url), "utf8"));
const md = parser.configure([GFM, ...editorExtensions]);


function extractMath(src) {
  const inline = [];
  const block = [];
  md.parse(src).iterate({
    enter(node) {
      if (node.name === "InlineMath") {
        const text = src.slice(node.from, node.to);
        const d = text.startsWith("$$") ? 2 : 1;
        inline.push(text.slice(d, text.length - d));
      } else if (node.name === "BlockMath") {
        block.push(blockMathSource(node.node, (a, b) => src.slice(a, b)));
      }
    },
  });
  return { inline, block };
}

function extractFrontMatter(src) {
  let raw = null;
  md.parse(src).iterate({
    enter(node) {
      if (node.name === "FrontMatter" && raw === null) {
        const marks = node.node.getChildren("FrontMatterMark");
        raw = src.slice(marks[0].to, marks[1].from).trim();
      }
    },
  });
  return raw;
}

function extractWikilinks(src) {
  const found = [];
  md.parse(src).iterate({
    enter(node) {
      if (node.name === "WikiLink") found.push(parseWikilink(src.slice(node.from + 2, node.to - 2)));
    },
  });
  return found;
}

function extractTags(src) {
  const found = [];
  md.parse(src).iterate({
    enter(node) {
      if (node.name === "HashTag") found.push(src.slice(node.from + 1, node.to));
    },
  });
  return found;
}

// what the formatting syntax amounts to (as Python's `format_marks`): a highlight's text is its
// source without any *Mark node inside it (`==a **b** c==` -> "a b c")
function extractFormat(src) {
  const found = { highlights: [], tags: [], comments: [], line_comments: [] };
  md.parse(src).iterate({
    enter(node) {
      if (node.name === "Highlight") {
        const marks = [];
        node.node.toTree().iterate({ enter: (n) => { if (n.name.endsWith("Mark")) marks.push([n.from + node.from, n.to + node.from]); } });
        let text = "";
        for (let i = node.from; i < node.to; i++) if (!marks.some(([a, b]) => i >= a && i < b)) text += src[i];
        found.highlights.push(text);
      } else if (node.name === "FormatTag") found.tags.push(src.slice(node.from, node.to));
      else if (node.name === "Comment") found.comments.push(src.slice(node.from + 2, node.to - 2));
      else if (node.name === "LineComment") found.line_comments.push(src.slice(node.from + 2, node.to));
    },
  });
  return found;
}

function extractPageBreaks(src) {
  const found = [];
  md.parse(src).iterate({
    enter(node) {
      if (node.name === "PageBreak") found.push(src.slice(0, node.from).split("\n").length);
    },
  });
  return found;
}

let failed = 0;
const math = load("math_cases.json");
for (const c of math) {
  const got = extractMath(c.src);
  if (JSON.stringify(got.inline) !== JSON.stringify(c.inline) || JSON.stringify(got.block) !== JSON.stringify(c.block)) {
    failed++;
    console.log(`MISMATCH math/${c.name}: ${JSON.stringify(c.src)}`);
    console.log(`  python: inline=${JSON.stringify(c.inline)} block=${JSON.stringify(c.block)}`);
    console.log(`  lezer : inline=${JSON.stringify(got.inline)} block=${JSON.stringify(got.block)}`);
  }
}
const fm = load("front_matter_cases.json");
for (const c of fm) {
  const got = extractFrontMatter(c.src);
  if (got !== c.raw) {
    failed++;
    console.log(`MISMATCH front_matter/${c.name}: ${JSON.stringify(c.src)}`);
    console.log(`  python: ${JSON.stringify(c.raw)}`);
    console.log(`  lezer : ${JSON.stringify(got)}`);
  }
}
const wiki = load("wikilink_cases.json");
for (const c of wiki) {
  const got = extractWikilinks(c.src);
  if (JSON.stringify(got) !== JSON.stringify(c.links)) {
    failed++;
    console.log(`MISMATCH wikilink/${c.name}: ${JSON.stringify(c.src)}`);
    console.log(`  python: ${JSON.stringify(c.links)}`);
    console.log(`  lezer : ${JSON.stringify(got)}`);
  }
}
const tagCases = load("tag_cases.json");
for (const c of tagCases) {
  const got = extractTags(c.src);
  if (JSON.stringify(got) !== JSON.stringify(c.tags)) {
    failed++;
    console.log(`MISMATCH tag/${c.name}: ${JSON.stringify(c.src)}`);
    console.log(`  python: ${JSON.stringify(c.tags)}`);
    console.log(`  lezer : ${JSON.stringify(got)}`);
  }
}
const breakCases = load("pagebreak_cases.json");
for (const c of breakCases) {
  const got = extractPageBreaks(c.src);
  const want = c.breaks.map((b) => b.line);
  if (JSON.stringify(got) !== JSON.stringify(want)) {
    failed++;
    console.log(`MISMATCH pagebreak/${c.name}: ${JSON.stringify(c.src)}`);
    console.log(`  python: ${JSON.stringify(want)}`);
    console.log(`  lezer : ${JSON.stringify(got)}`);
  }
}
const formatCases = load("format_cases.json");
for (const c of formatCases) {
  const got = extractFormat(c.src);
  const want = { highlights: c.highlights, tags: c.tags, comments: c.comments, line_comments: c.line_comments };
  if (JSON.stringify(got) !== JSON.stringify(want)) {
    failed++;
    console.log(`MISMATCH format/${c.name}: ${JSON.stringify(c.src)}`);
    console.log(`  python: ${JSON.stringify(want)}`);
    console.log(`  lezer : ${JSON.stringify(got)}`);
  }
}
const total = math.length + fm.length + wiki.length + tagCases.length + breakCases.length + formatCases.length;
console.log(failed ? `${failed} of ${total} cases differ` : `all ${total} grammar cases agree with the Python parser (${math.length} math, ${fm.length} front matter, ${wiki.length} wikilink, ${tagCases.length} tag, ${breakCases.length} page break, ${formatCases.length} format)`);
process.exit(failed ? 1 : 0);
