// Lezer markdown extension for inline #tags. Mirrors the Python reference
// (paper_pile/core/tags.py + parser.py `_hashtag_rule`); tests/fixtures/tag_cases.json is checked
// against both (`node check_sync.mjs`).
//
// `#` at the start of the inline text or after whitespace, then letters / marks / digits / `_` /
// `-` / `/` (trailing `/` dropped, no leading `/`), not digits only. Code spans are consumed by
// their own rule first, so a tag inside them is never seen here.
import { tags as t } from "@lezer/highlight";

const HASH = 35; // #
const TAG_CHAR = /[\p{L}\p{M}\p{N}_\-/]/u;
const DIGITS = /^\p{N}+$/u;

// The tag body that starts at `text[0]` ("" if none), as Python's `tag_body`.
export function tagBody(text) {
  let body = "";
  for (const ch of text) {
    if (!TAG_CHAR.test(ch)) break;
    body += ch;
  }
  body = body.replace(/\/+$/, "");
  if (!body || body.startsWith("/") || DIGITS.test(body)) return "";
  return body;
}

export const TagExt = {
  defineNodes: [{ name: "HashTag", style: t.labelName }],
  parseInline: [
    {
      name: "HashTag",
      before: "Escape",
      parse(cx, next, pos) {
        if (next !== HASH) return -1;
        if (pos > cx.offset && !/\s/.test(String.fromCharCode(cx.char(pos - 1)))) return -1;
        const body = tagBody(cx.slice(pos + 1, cx.end));
        if (!body) return -1;
        return cx.addElement(cx.elt("HashTag", pos, pos + 1 + body.length));
      },
    },
  ],
};
