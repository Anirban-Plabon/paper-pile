// Cases for paper_pile/gui/static/pairs.js (run by tests/gui/test_pairs.py). A case is the text
// with | for the caret (or [..] for a selection), the key, and the text after it.
import { createRequire } from "node:module";
const require = createRequire(import.meta.url);
const P = require("../../paper_pile/gui/static/pairs.js");

const CASES = [
  // marks open where a word can start
  ["hello |", "*", "hello *|*"],
  ["|", "*", "*|*"],
  ["*|*", "*", "**|**"],
  ["**|**", "*", "***|"],
  ["*|*", " ", "* |"],
  ["**bold|**", "*", "**bold*|*"],
  ["**bold*|*", "*", "**bold**|"],
  ["2|", "*", null],
  ["snake|", "_", null],
  ["a |", "_", "a _|_"],
  ["|", "~", "~|~"],
  ["~|~", "~", "~~|~~"],
  ["~~done|~~", "~", "~~done~|~"],
  ["|", "`", "`|`"],
  ["`|`", "`", "``|"],
  ["``|", "`", null],
  ["`code|`", "`", "`code`|"],
  ["word|more", "*", null],
  // highlight
  ["=|", "=", "==|=="],
  ["x=|", "=", null],
  ["a ==|==", " ", "a == |"],
  ["==hi|==", "=", "==hi=|="],
  ["|", "=", null],
  // brackets
  ["|", "(", "(|)"],
  ["|word", "(", null],
  ["(a|)", ")", "(a)|"],
  ["a|)", ")", null],
  ["[|]", "[", "[[|]]"],
  // money
  ["costs |", "$", null],
  ["$x|$", "$", "$x$|"],
  // wrapping a selection
  ["[word]", "*", "*[word]*"],
  ["[word]", "=", "==[word]=="],
  ["[word]", "(", "([word])"],
  ["a [b\nc]", "*", null],
];
const BACK = [
  ["(|)", "|"],
  ["**|**", "*|*"],
  ["`|`", "|"],
  ["a*|", null],
  ["**b|**", null],
];

// "a [b] c" -> before / after / selected
function split(s) {
  const i = s.indexOf("[");
  if (s.includes("|")) return { before: s.slice(0, s.indexOf("|")), sel: "", after: s.slice(s.indexOf("|") + 1) };
  const j = s.indexOf("]", i);
  return { before: s.slice(0, i), sel: s.slice(i + 1, j), after: s.slice(j + 1) };
}

// the result written as the cases are: | for a caret, [..] for a selection
function show(before, after, r) {
  const start = before.length - r.back;
  const full = before.slice(0, start) + r.text + after.slice(r.fwd);
  const a = start + r.a;
  const b = start + r.b;
  return a === b ? `${full.slice(0, a)}|${full.slice(a)}` : `${full.slice(0, a)}[${full.slice(a, b)}]${full.slice(b)}`;
}

let bad = 0;
for (const [input, key, want] of CASES) {
  const { before, sel, after } = split(input);
  const r = P.typed(before, after, sel, key, false);
  const got = r ? show(before, after, r) : null;
  if (got !== want) {
    bad++;
    console.log(`typed ${JSON.stringify(key)} in ${JSON.stringify(input)}: got ${JSON.stringify(got)}, want ${JSON.stringify(want)}`);
  }
}
for (const [input, want] of BACK) {
  const { before, after } = split(input);
  const r = P.back(before, after);
  const got = r ? show(before, after, r) : null;
  if (got !== want) {
    bad++;
    console.log(`Backspace in ${JSON.stringify(input)}: got ${JSON.stringify(got)}, want ${JSON.stringify(want)}`);
  }
}
// code: marks are plain, brackets still pair
if (P.typed("a ", "", "", "*", true) !== null) (bad++, console.log("a mark paired in code"));
if (!P.typed("a ", "", "", "(", true)) (bad++, console.log("a bracket did not pair in code"));
if (!P.inCode("```py\nx = ") || P.inCode("```py\nx\n```\n") || !P.inCode("a `b")) (bad++, console.log("inCode is wrong"));
if (bad) process.exit(1);
console.log(`${CASES.length + BACK.length} pair cases pass`);
