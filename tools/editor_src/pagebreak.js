// Lezer block parser for manual page breaks. Same contract as the Python reference
// (paper_pile/core/pagebreak.py `LINE` + parser.py `_page_break_rule`), checked against
// tests/fixtures/pagebreak_cases.json by check_sync.mjs:
//   * the whole line is `---/` or a page break div (see LINE), indent < 4;
//   * top level only (not in a quote or list item);
//   * the line above and the line below are empty (or the document starts / ends).
// It never interrupts a paragraph. Whether a break takes effect (content on both sides, not
// right after another break) is decided by the Python side, not here.
const Q = `(["'])`;
export const LINE = new RegExp(
  "^ {0,3}(?:---/|<div[ \\t]+(?:" +
    `style[ \\t]*=[ \\t]*${Q}[ \\t]*` +
    "(?:page-break-after[ \\t]*:[ \\t]*always|break-after[ \\t]*:[ \\t]*page)" +
    "[ \\t]*;?[ \\t]*\\1" +
    `|class[ \\t]*=[ \\t]*${Q}[ \\t]*page-break[ \\t]*\\2` +
    ")[ \\t]*>[ \\t]*</div[ \\t]*>)[ \\t]*$",
  "i",
);

const blank = (text) => /^[ \t]*$/.test(text);

function prevLineBlank(cx) {
  if (cx.lineStart === 0) return true;
  const end = cx.lineStart - 1; // the "\n" ending the previous line
  let from = end;
  while (from > 0 && cx.input.read(from - 1, from) !== "\n") from--;
  return blank(cx.input.read(from, end));
}

export const PageBreakExt = {
  defineNodes: [{ name: "PageBreak", block: true }],
  parseBlock: [
    {
      name: "PageBreak",
      before: "HTMLBlock",
      parse(cx, line) {
        if (cx.parentType().name !== "Document" || !LINE.test(line.text)) return false;
        if (!prevLineBlank(cx)) return false;
        const end = cx.lineStart + line.text.length;
        if (end < cx.input.length && !blank(cx.peekLine())) return false;
        cx.addElement(cx.elt("PageBreak", cx.lineStart, end));
        cx.nextLine();
        return true;
      },
    },
  ],
};
