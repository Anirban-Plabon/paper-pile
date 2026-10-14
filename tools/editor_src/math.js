// Lezer markdown extension: inline math `$...$` with the pandoc dollar rule.
//   - no whitespace right after the opening `$`
//   - no whitespace right before the closing `$`
//   - closing `$` is not followed by a digit  ("$5 and $10" stays text)
// Display math: a block starting with a `$$` line, closed by a line ending in `$$`
// (`$$x^2$$` on one line counts). An unclosed block runs to the end of the document.
// Keep in sync with markdown-it `dollarmath` in core/parser.py.
import { tags as t } from "@lezer/highlight";

const DOLLAR = 36;
const BACKSLASH = 92;

const isSpace = (c) => c === 32 || c === 9 || c === 10 || c === 13;
const isDigit = (c) => c >= 48 && c <= 57;

export const MathExt = {
  defineNodes: [
    { name: "InlineMath", style: t.special(t.content) },
    { name: "InlineMathMark", style: t.processingInstruction },
    { name: "BlockMath", block: true, style: t.special(t.content) },
    { name: "BlockMathMark", style: t.processingInstruction },
  ],
  parseBlock: [
    {
      name: "BlockMath",
      before: "FencedCode",
      parse(cx, line) {
        const rest = line.text.slice(line.pos).trimEnd();
        if (!rest.startsWith("$$")) return false;
        const from = cx.lineStart + line.pos;
        const element = (to, closed) =>
          cx.elt("BlockMath", from, to, [
            cx.elt("BlockMathMark", from, from + 2),
            ...(closed ? [cx.elt("BlockMathMark", to - 2, to)] : []),
          ]);
        if (rest.length > 4 && rest.endsWith("$$") && rest.slice(2, -2).trim()) {
          cx.addElement(element(from + rest.length, true));
          cx.nextLine();
          return true;
        }
        while (cx.nextLine()) {
          const text = line.text.slice(line.pos).trimEnd();
          if (text.endsWith("$$")) {
            cx.addElement(element(cx.lineStart + line.pos + text.length, true));
            cx.nextLine();
            return true;
          }
        }
        cx.addElement(element(cx.prevLineEnd(), false));
        return true;
      },
      endLeaf: (_cx, line) => line.text.startsWith("$$", line.pos),
    },
  ],
  parseInline: [
    {
      name: "InlineMath",
      before: "Escape",
      parse(cx, next, pos) {
        if (next !== DOLLAR) return -1;
        if (cx.char(pos + 1) === DOLLAR || cx.char(pos - 1) === DOLLAR) return -1;
        const first = cx.char(pos + 1);
        if (first < 0 || isSpace(first)) return -1;
        for (let i = pos + 1; i < cx.end; i++) {
          const c = cx.char(i);
          if (c === BACKSLASH) {
            i++;
            continue;
          }
          if (c !== DOLLAR) continue;
          if (isSpace(cx.char(i - 1)) || isDigit(cx.char(i + 1))) continue;
          if (i === pos + 1) return -1; // empty `$$`
          return cx.addElement(
            cx.elt("InlineMath", pos, i + 1, [
              cx.elt("InlineMathMark", pos, pos + 1),
              cx.elt("InlineMathMark", i, i + 1),
            ]),
          );
        }
        return -1;
      },
    },
  ],
};
