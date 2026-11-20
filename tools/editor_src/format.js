// Lezer markdown extension for the formatting menu's syntax (PLAN §4.38). Mirrors the Python
// reference (paper_pile/core/parser.py: `_highlight_rule`, `_format_tag_rule`, `_comment_rule`,
// `_line_comment_rule`); tests/fixtures/format_cases.json is checked against both
// (`node check_sync.mjs`).
//
//  * `==highlight==`: exactly two `=` as a delimiter (like GFM's `~~`), flanking rules of
//    CommonMark, so it nests with emphasis.
//  * `<u>`, `</u>`, `<span style="color:…">`, `</span>`: FormatTag (paired by livepreview.js).
//  * `%%comment%%` on one line: Comment (+ CommentMark at both ends).
//  * `//` at the start of a line or after a space: LineComment to the end of the line.
// Code spans are consumed by their own rule first, so none of these is seen inside code.
import { tags as t } from "@lezer/highlight";

const EQ = 61; // =
const LT = 60; // <
const PCT = 37; // %
const SLASH = 47; // /
const PUNCT = /[\p{P}\p{S}]/u;
const SPACE = /\s|^$/;

// The text colours of the formatting menu (Python: core/formatting.py COLORS; a test keeps the two
// equal). The editor draws them as `pp-fc-<name>` (app.css, a dark-theme variant each); any other
// colour code is shown as written.
export const PALETTE = {
  "#787774": "gray",
  "#e03e3e": "red",
  "#d9730d": "orange",
  "#cb912f": "yellow",
  "#448361": "green",
  "#337ea9": "blue",
  "#9065b0": "purple",
  "#c14c8a": "pink",
};

export const FORMAT_TAG = /^(?:<u>|<\/u>|<span style="color:\s*(?:#[0-9a-fA-F]{3,8}|[a-zA-Z]+)\s*;?">|<\/span>)/;
const COMMENT = /^%%((?:[^\n%]|%(?!%))*)%%/;
const HighlightDelim = { resolve: "Highlight", mark: "HighlightMark" };

export const FormatExt = {
  defineNodes: [
    { name: "Highlight", style: t.special(t.content) },
    { name: "HighlightMark", style: t.processingInstruction },
    { name: "FormatTag", style: t.processingInstruction },
    { name: "Comment", style: t.comment },
    { name: "CommentMark", style: t.comment },
    { name: "LineComment", style: t.lineComment },
  ],
  parseInline: [
    {
      name: "Highlight",
      before: "Emphasis",
      parse(cx, next, pos) {
        if (next !== EQ || cx.char(pos + 1) !== EQ || cx.char(pos + 2) === EQ || cx.char(pos - 1) === EQ) return -1;
        const before = cx.slice(pos - 1, pos);
        const after = cx.slice(pos + 2, pos + 3);
        const sBefore = SPACE.test(before), sAfter = SPACE.test(after);
        const pBefore = PUNCT.test(before), pAfter = PUNCT.test(after);
        return cx.addDelimiter(
          HighlightDelim,
          pos,
          pos + 2,
          !sAfter && (!pAfter || sBefore || pBefore),
          !sBefore && (!pBefore || sAfter || pAfter),
        );
      },
    },
    {
      name: "FormatTag",
      before: "HTMLTag",
      parse(cx, next, pos) {
        if (next !== LT) return -1;
        const m = FORMAT_TAG.exec(cx.slice(pos, Math.min(cx.end, pos + 80)));
        return m ? cx.addElement(cx.elt("FormatTag", pos, pos + m[0].length)) : -1;
      },
    },
    {
      name: "Comment",
      before: "Emphasis",
      parse(cx, next, pos) {
        if (next !== PCT || cx.char(pos + 1) !== PCT) return -1;
        const m = COMMENT.exec(cx.slice(pos, cx.end));
        if (!m) return -1;
        const end = pos + m[0].length;
        return cx.addElement(cx.elt("Comment", pos, end, [cx.elt("CommentMark", pos, pos + 2), cx.elt("CommentMark", end - 2, end)]));
      },
    },
    {
      name: "LineComment",
      before: "Emphasis",
      parse(cx, next, pos) {
        if (next !== SLASH || cx.char(pos + 1) !== SLASH) return -1;
        if (pos > cx.offset && !/[ \t\n]/.test(String.fromCharCode(cx.char(pos - 1)))) return -1;
        const rest = cx.slice(pos, cx.end);
        const nl = rest.indexOf("\n");
        return cx.addElement(cx.elt("LineComment", pos, nl < 0 ? cx.end : pos + nl));
      },
    },
  ],
};
