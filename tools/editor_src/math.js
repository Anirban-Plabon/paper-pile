// Lezer markdown extension: inline math `$...$` with the pandoc dollar rule.
//   - no whitespace right after the opening `$`
//   - no whitespace right before the closing `$`
//   - closing `$` is not followed by a digit  ("$5 and $10" stays text)
// `$$` display blocks are added with the widget work in S2 (P0.5).
import { tags as t } from "@lezer/highlight";

const DOLLAR = 36;
const BACKSLASH = 92;

const isSpace = (c) => c === 32 || c === 9 || c === 10 || c === 13;
const isDigit = (c) => c >= 48 && c <= 57;

export const MathExt = {
  defineNodes: [
    { name: "InlineMath", style: t.special(t.content) },
    { name: "InlineMathMark", style: t.processingInstruction },
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
