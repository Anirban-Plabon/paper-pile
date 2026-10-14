// Lezer markdown extension for math. These rules mirror the Python reference parser
// (paper_pile/core/parser.py, markdown-it dollarmath); tests/fixtures/math_cases.json is
// checked against both (`node check_math.mjs`), so they cannot drift apart silently.
//
// Inline `$x$`: no whitespace right after the opening `$` or right before the closing one, no
// digit directly before the opening or after the closing `$` ("$5 and $10" stays text), `\$` is
// a literal dollar, content not empty. The FIRST unescaped closing `$` decides: if it is not
// valid, the opening `$` is plain text (no scanning further).
// Inline `$$x$$` inside a paragraph: no whitespace rules.
// Block `$$`: a line starting with `$$` (indent < 4) that closes on the same line (`$$x$$`) or on
// a later line ending in `$$`. Unclosed, or a blank line before the closing `$$`: plain text.
// A block may start right after a paragraph line.
import { tags as t } from "@lezer/highlight";

const DOLLAR = 36;
const BACKSLASH = 92;
const LOOKAHEAD_CHARS = 20000; // how far to search for a closing `$$` line

const isSpace = (c) => c === 32 || c === 9 || c === 10 || c === 13;
const isDigit = (c) => c >= 48 && c <= 57;

// Where would a block that starts on the current line end? Looks at the raw text without
// consuming anything: {sameLine} for `$$x$$`, {lines: n} when the closing `$$` is n lines
// further down, or null when this line does not start a block.
function findBlock(cx, line) {
  if (line.indent - line.baseIndent >= 4) return null; // indented code block
  const rest = line.text.slice(line.pos).trimEnd();
  if (!rest.startsWith("$$")) return null;
  if (rest.length > 3 && rest.endsWith("$$")) return { sameLine: true, length: rest.length };
  const tail = cx.input.read(cx.lineStart, Math.min(cx.input.length, cx.lineStart + LOOKAHEAD_CHARS));
  const lines = tail.split("\n");
  for (let k = 1; k < lines.length; k++) {
    // list indentation and blockquote markers are not part of the line's content
    const text = lines[k].replace(/^[\s>]*/, "").trimEnd();
    if (text.endsWith("$$")) return { sameLine: false, lines: k };
    if (text === "") return null; // a blank line before the closing `$$`: not a block
  }
  return null; // unclosed
}

export const MathExt = {
  defineNodes: [
    { name: "InlineMath", style: t.special(t.content) },
    { name: "InlineMathMark", style: t.processingInstruction },
    { name: "BlockMath", block: true, style: t.special(t.content) },
    { name: "BlockMathMark", style: t.processingInstruction },
  ],
  parseInline: [
    {
      name: "InlineMath",
      before: "Escape",
      parse(cx, next, pos) {
        if (next !== DOLLAR) return -1;
        if (isDigit(cx.char(pos - 1))) return -1; // a digit directly before the opening `$`
        const mark = (from, to) => cx.elt("InlineMathMark", from, to);
        if (cx.char(pos + 1) === DOLLAR) {
          // $$ ... $$ inside a paragraph
          for (let i = pos + 2; i < cx.end - 1; i++) {
            const c = cx.char(i);
            if (c === BACKSLASH) {
              i++;
              continue;
            }
            if (c !== DOLLAR || cx.char(i + 1) !== DOLLAR) continue;
            if (i === pos + 2 || isDigit(cx.char(i + 2))) return -1;
            return cx.addElement(
              cx.elt("InlineMath", pos, i + 2, [mark(pos, pos + 2), mark(i, i + 2)]),
            );
          }
          return -1;
        }
        const first = cx.char(pos + 1);
        if (first < 0 || isSpace(first)) return -1;
        for (let i = pos + 1; i < cx.end; i++) {
          const c = cx.char(i);
          if (c === BACKSLASH) {
            i++;
            continue;
          }
          if (c !== DOLLAR) continue;
          // the first unescaped `$` after the opening one is the closing candidate: it decides
          if (i === pos + 1 || isSpace(cx.char(i - 1)) || isDigit(cx.char(i + 1))) return -1;
          return cx.addElement(
            cx.elt("InlineMath", pos, i + 1, [mark(pos, pos + 1), mark(i, i + 1)]),
          );
        }
        return -1;
      },
    },
  ],
  parseBlock: [
    {
      name: "BlockMath",
      before: "FencedCode",
      parse(cx, line) {
        const found = findBlock(cx, line);
        if (!found) return false;
        const from = cx.lineStart + line.pos;
        const element = (to) =>
          cx.elt("BlockMath", from, to, [
            cx.elt("BlockMathMark", from, from + 2),
            cx.elt("BlockMathMark", to - 2, to),
          ]);
        if (found.sameLine) {
          cx.addElement(element(from + found.length));
        } else {
          for (let k = 0; k < found.lines; k++) if (!cx.nextLine()) break;
          const text = line.text.slice(line.pos).trimEnd();
          cx.addElement(element(cx.lineStart + line.pos + text.length));
        }
        cx.nextLine();
        return true;
      },
      // a block may start right after a paragraph line (same test as above, nothing consumed)
      endLeaf: (cx, line) => findBlock(cx, line) !== null,
    },
  ],
};
