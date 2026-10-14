// Lezer block parser for YAML front matter. Same contract as the Python parser
// (paper_pile/core/parser.py `_front_matter_rule`), checked against
// tests/fixtures/front_matter_cases.json by check_sync.mjs:
//   * only at the very top of the document;
//   * the first line is exactly `---` (trailing spaces allowed);
//   * it closes on the next line that is exactly `---` (trailing spaces allowed);
//   * otherwise it is not front matter (and the lines parse as ordinary markdown).
// Without this, the grammar would read the opening `---` as a horizontal rule and the first
// key as a Setext heading.
const LOOKAHEAD_CHARS = 20000;

export const FrontMatterExt = {
  defineNodes: [{ name: "FrontMatter", block: true }, { name: "FrontMatterMark" }],
  parseBlock: [
    {
      name: "FrontMatter",
      before: "HorizontalRule",
      parse(cx, line) {
        if (cx.lineStart !== 0 || line.text.trimEnd() !== "---") return false;
        const tail = cx.input.read(0, Math.min(cx.input.length, LOOKAHEAD_CHARS));
        const lines = tail.split("\n");
        const close = lines.findIndex((l, i) => i > 0 && l.trimEnd() === "---");
        if (close < 0) return false;
        for (let k = 0; k < close; k++) if (!cx.nextLine()) return false;
        const to = cx.lineStart + line.text.trimEnd().length;
        cx.addElement(
          cx.elt("FrontMatter", 0, to, [cx.elt("FrontMatterMark", 0, 3), cx.elt("FrontMatterMark", to - 3, to)]),
        );
        cx.nextLine();
        return true;
      },
    },
  ],
};
