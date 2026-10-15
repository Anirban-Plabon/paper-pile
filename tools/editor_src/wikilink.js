// Lezer markdown extension for [[wikilinks]]. Mirrors the Python reference
// (paper_pile/core/parser.py `_wikilink_rule`, core/links.py `parse_wikilink`);
// tests/fixtures/wikilink_cases.json is checked against both (`node check_sync.mjs`).
//
// `[[` + text on ONE line without `[` or `]` + the first `]]`, and the text must name a note or a
// heading. Code spans / fences are consumed by other rules first, so they never reach this one.
import { tags as t } from "@lezer/highlight";

const BANG = 33; // !
const OPEN = 91; // [
const CLOSE = 93; // ]
const NEWLINE = 10;

// "note#heading|alias" -> {note, heading, alias}, or null when it points at nothing.
export function parseWikilink(inner) {
  const bar = inner.indexOf("|");
  const target = bar < 0 ? inner : inner.slice(0, bar);
  const alias = bar < 0 ? "" : inner.slice(bar + 1).trim();
  const hash = target.indexOf("#");
  const note = (hash < 0 ? target : target.slice(0, hash)).trim();
  const heading = hash < 0 ? "" : target.slice(hash + 1).trim();
  return note || heading ? { note, heading, alias } : null;
}

// `[[...]]` starting at `pos`: the end of the link, or -1
function parseLink(cx, pos) {
  if (cx.char(pos) !== OPEN || cx.char(pos + 1) !== OPEN) return -1;
  for (let i = pos + 2; i < cx.end; i++) {
    const c = cx.char(i);
    if (c === NEWLINE || c === OPEN) return -1;
    if (c !== CLOSE) continue;
    if (cx.char(i + 1) !== CLOSE) return -1;
    if (!parseWikilink(cx.slice(pos + 2, i))) return -1;
    return cx.addElement(
      cx.elt("WikiLink", pos, i + 2, [cx.elt("WikiLinkMark", pos, pos + 2), cx.elt("WikiLinkMark", i, i + 2)]),
    );
  }
  return -1;
}

export const WikiLinkExt = {
  defineNodes: [
    { name: "WikiLink", style: t.link },
    { name: "WikiLinkMark", style: t.processingInstruction },
  ],
  parseInline: [
    {
      name: "WikiLink",
      before: "Link",
      parse(cx, next, pos) {
        // `![[note]]` (an embed): the `!` stays plain text, but the markdown Image rule must not
        // get to swallow `![`, so the link is claimed here, one character later
        if (next === BANG && cx.char(pos + 1) === OPEN && cx.char(pos + 2) === OPEN) {
          return parseLink(cx, pos + 1);
        }
        return next === OPEN ? parseLink(cx, pos) : -1;
      },
    },
  ],
};
