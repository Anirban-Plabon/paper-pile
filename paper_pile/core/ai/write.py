"""Writing one planned change of an AI edit (PLAN §4.29, ``docs/AI_EDITS.md`` §4.5).

The model gets one part to write — the text of one block (or a run of selected blocks), or new
text to go after / before one — with its surroundings as context it must not write, and replies
with plain text. Python then fits that text into the note: list items get the list's own marker,
table rows the table's column count (and its alignment), blocks one blank line around them, and
code / math blocks inside the part come back byte for byte. Pure; no UI imports.
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass

from paper_pile.core.ai.blocks import Block
from paper_pile.core.ai.issues import Issue
from paper_pile.core.ai.plan import PlannedEdit
from paper_pile.core.ai.protect import mask, protected_tokens, unmask
from paper_pile.core.tables import Table, format_table, parse_table, split_row

WRITE_RULES = (
    "You edit one part of a markdown note. Reply with only the new text of that part: no "
    "introduction, no comments, no code fence around it, no heading unless the part is a "
    "heading. Keep the language of the note. Keep links, images, code, math and #tags exactly "
    "as written."
)
CONTEXT_WORDS = 60
EARLIER_CHARS = 1600  # "Already written for this task" (about 400 tokens)
_MARK = re.compile(r"^([ \t]*)([-*+]|(\d{1,9})([.)]))([ \t]+)(\[[ xX]\][ \t]+)?")
_HEADING = re.compile(r"^(#{1,6})[ \t]+(.*)$")
_DELIMITER = re.compile(r"^\s*\|?\s*:?-{1,}:?\s*(\|\s*:?-{1,}:?\s*)*\|?\s*$")


@dataclass(frozen=True, slots=True)
class PlannedChange:
    """One change to the note, in its offsets: ``note[start:end]`` becomes ``new``."""

    start: int
    end: int
    new: str
    why: str = ""
    outside: bool = False
    issues: tuple[Issue, ...] = ()


@dataclass(frozen=True, slots=True)
class WriteJob:
    """One model call: the message to send and what is needed to fit its answer in."""

    edit: PlannedEdit
    task: str
    kept: tuple[str, ...]  # fixed blocks masked in the part (⟦KEEP n⟧)
    old: str  # the part's text now ("" for new text)
    keep: tuple[str, ...]  # inline tokens the answer must keep


def _span(edit: PlannedEdit, blocks: Sequence[Block]) -> list[Block]:
    ids = [b.id for b in blocks]
    a = ids.index(edit.block)
    b = ids.index(edit.last) if edit.last in ids else a
    return list(blocks[min(a, b) : max(a, b) + 1])


def _words(text: str, most: int = CONTEXT_WORDS) -> str:
    words = text.split()
    return " ".join(words[:most]) + (" …" if len(words) > most else "")


def _neighbours(blocks: Sequence[Block], first: Block, last: Block) -> tuple[Block | None, ...]:
    ids = [b.id for b in blocks]
    a, z = ids.index(first.id), ids.index(last.id)
    before = blocks[a - 1] if a > 0 and blocks[a - 1].kind != "front_matter" else None
    after = blocks[z + 1] if z + 1 < len(blocks) else None
    return before, after


def label(edit: PlannedEdit) -> str:
    if edit.last and edit.last != edit.block:
        return f"[{edit.block}–{edit.last}]"
    return f"[{edit.block}]"


def _change(
    edit: PlannedEdit, start: int, end: int, new: str, issues: Sequence[Issue] = ()
) -> PlannedChange:
    return PlannedChange(start, end, new, edit.why, edit.outside, tuple(issues))


def write_job(
    edit: PlannedEdit,
    blocks: Sequence[Block],
    note: str,
    instruction: str,
    earlier: Sequence[str] = (),
) -> WriteJob:
    """The message for writing ``edit`` (not for a delete: that needs no model)."""
    part = _span(edit, blocks)
    first, last = part[0], part[-1]
    where = " › ".join(first.path) or "the top of the note"
    lines = [f"Task: {instruction.strip()}"]
    if edit.why:
        lines.append(f"This change: {edit.why}")
    kept: list[str] = []
    old = ""
    keep: list[str] = []
    if edit.action == "change":
        old = note[first.start : last.end]
        spans = [(b.start - first.start, b.end - first.start) for b in part if b.fixed]
        masked, kept = mask(old, spans)
        keep = list(dict.fromkeys(protected_tokens(masked)))
        before, after = _neighbours(blocks, first, last)
        lines.append(f"Where it is (context, do not write it): {where}")
        if before is not None:
            lines.append(f"Before it (context, do not write it):\n{_words(before.text(note))}")
        lines.append(f"The text to rewrite {label(edit)}:\n<<<\n{masked}\n>>>")
        if after is not None:
            lines.append(f"After it (context, do not write it):\n{_words(after.text(note))}")
    else:
        side = "after" if edit.action == "add_after" else "before"
        lines.append(f"Where it goes (context, do not write it): {where}")
        lines.append(
            f"It goes {side} this text (context, do not write it):\n{_words(first.text(note))}"
        )
        lines.append(style_hint(edit, first, note))
    if earlier:
        done = "\n\n".join(earlier)[-EARLIER_CHARS:]
        lines.append(f"Already written for this task (context, do not write it):\n{done}")
    if keep:
        lines.append("Keep exactly: " + ", ".join(keep))
    if kept:
        lines.append("Keep every ⟦KEEP n⟧ line exactly as it is, on its own line.")
    reply = (
        f"Reply with the new text for {label(edit)} only."
        if edit.action == "change"
        else ("Reply with only the new text.")
    )
    lines.append(reply)
    return WriteJob(edit, "\n".join(lines), tuple(kept), old, tuple(keep))


def style_hint(edit: PlannedEdit, anchor: Block, note: str) -> str:
    """How new text next to ``anchor`` must look (by kind of block, never by case)."""
    if edit.new_section:
        marks = "#" * max(1, edit.level)
        return (
            f"Write the new section. Start with one heading line at level {edit.level} "
            f"(`{marks} `), then its text. No other heading of level {edit.level} or higher."
        )
    if anchor.kind == "item":
        first = anchor.text(note).split("\n", 1)[0]
        m = _MARK.match(first)
        marker = m.group(2) + " " if m else "- "
        example = _words(first, 8)
        return (
            f"Write only the new list item(s) for this list. Start each with `{marker}` like "
            f"its items, for example: `{example}`"
        )
    if anchor.kind == "table" and edit.action == "add_after":
        table = parse_table(anchor.text(note))
        if table is not None:
            header = "| " + " | ".join(table.header) + " |"
            cells = " | ".join("…" for _ in table.header)
            return (
                f"Write only the new row(s) for this table. Each row has exactly "
                f"{table.columns} cells: `| {cells} |`. The header is: `{header}`"
            )
    return "Write only the new paragraph(s)."


def fit_answer(
    job: WriteJob, blocks: Sequence[Block], note: str, text: str
) -> PlannedChange | None:
    """The change ``text`` (the model's cleaned answer) makes to ``note``; None when it cannot
    be made safely (a code or math block of the part would be lost). Issues found while fitting
    (cells padded, a heading level set) go with it."""
    edit = job.edit
    part = _span(edit, blocks)
    first, last = part[0], part[-1]
    issues: list[Issue] = []
    if edit.action == "change":
        new, bad = unmask(text.strip("\n"), job.kept)
        if bad:
            return None
        return _change(edit, first.start, last.end, new.rstrip())
    body = text.strip("\n").rstrip()
    if not body:
        return None
    if edit.new_section:
        body, fixed = _section_heading(body, edit.level)
        issues.extend(fixed)
        return _place_block(edit, first, body, issues)
    if first.kind == "item":
        return _place_items(edit, blocks, first, note, body, issues)
    if first.kind == "table" and edit.action == "add_after":
        return _place_rows(edit, first, note, body, issues)
    return _place_block(edit, first, body, issues)


def delete_change(edit: PlannedEdit, blocks: Sequence[Block], note: str) -> PlannedChange:
    """Removing the block(s) of ``edit`` with the blank lines after them."""
    part = _span(edit, blocks)
    start, end = part[0].start, part[-1].end
    while end < len(note) and note[end] in "\r\n":
        end += 1
    rest = ""
    if end == len(note):  # the last block: the blank lines before it go instead
        while start > 0 and note[start - 1] in "\r\n":
            start -= 1
        rest = "\n" if start and note.endswith("\n") else ""  # the note's last line break
    return _change(edit, start, end, rest)


def _place_block(edit: PlannedEdit, anchor: Block, body: str, issues: list[Issue]) -> PlannedChange:
    if edit.action == "add_before":
        return _change(edit, anchor.start, anchor.start, body + "\n\n", issues)
    return _change(edit, anchor.end, anchor.end, "\n\n" + body, issues)


def _section_heading(body: str, level: int) -> tuple[str, list[Issue]]:
    """The new section's first line as a heading of ``level`` (set when the model chose
    another level)."""
    first, _, rest = body.partition("\n")
    m = _HEADING.match(first.strip())
    if m is None or level < 1 or len(m.group(1)) == level:
        return body, []
    fixed = f"{'#' * level} {m.group(2).strip()}"
    issue = Issue("heading", "fixed", f"The new heading was set to level {level}.")
    return fixed + ("\n" + rest if rest else ""), [issue]


def _loose(blocks: Sequence[Block], anchor: Block, note: str) -> bool:
    """Items of ``anchor``'s list are separated by blank lines."""
    items = [b for b in blocks if b.list_id == anchor.list_id]
    return any("\n\n" in note[a.end : b.start] for a, b in zip(items, items[1:], strict=False))


def _place_items(
    edit: PlannedEdit,
    blocks: Sequence[Block],
    anchor: Block,
    note: str,
    body: str,
    issues: list[Issue],
) -> PlannedChange:
    m = _MARK.match(anchor.text(note).split("\n", 1)[0])
    indent = m.group(1) if m else ""
    bullet = m.group(2) if m and not m.group(3) else None
    number = int(m.group(3)) if m and m.group(3) else None
    close = m.group(4) if m and m.group(3) else "."
    number = None if number is None else number + (1 if edit.action == "add_after" else 0)
    items: list[list[str]] = []
    for line in body.split("\n"):
        own = _MARK.match(line)
        if own:  # a new item: its text, with its checkbox if it has one
            items.append([(own.group(6) or "") + line[own.end() :].strip()])
        elif not line.strip():
            continue
        elif items and line[:1] in " \t":  # indented: more of the item above
            items[-1].append(line.strip())
        else:  # text without a marker: an item of its own
            items.append([line.strip()])
    out = []
    for n, (head, *more) in enumerate(items):
        marker = f"{bullet} " if bullet else f"{(number or 1) + n}{close} "
        pad = indent + " " * len(marker)
        out.append("\n".join([indent + marker + head, *(pad + x for x in more)]))
    gap = "\n\n" if _loose(blocks, anchor, note) else "\n"
    text = gap.join(out)
    if edit.action == "add_before":
        return _change(edit, anchor.start, anchor.start, text + gap, issues)
    return _change(edit, anchor.end, anchor.end, gap + text, issues)


def _place_rows(
    edit: PlannedEdit, anchor: Block, note: str, body: str, issues: list[Issue]
) -> PlannedChange:
    old = anchor.text(note)
    table = parse_table(old)
    if table is None:
        return _place_block(edit, anchor, body, issues)
    rows: list[list[str]] = []
    header = [c.strip().lower() for c in table.header]
    for line in body.split("\n"):
        if not line.strip() or _DELIMITER.match(line):
            continue
        cells = [c.strip() for c in split_row(line)]
        if [c.lower() for c in cells] == header:
            continue  # the header again
        if len(cells) != table.columns:
            issues.append(
                Issue(
                    "cells",
                    "warn",
                    f"A new row had {len(cells)} cells; the table has {table.columns}.",
                )
            )
            cells = (cells + [""] * table.columns)[: table.columns]
        rows.append(cells)
    if not rows:
        return _place_block(edit, anchor, body, issues)
    if format_table(table) == old:  # an aligned table stays aligned
        grown = Table(table.header, table.aligns, [*table.rows, *rows], table.prefix)
        return _change(edit, anchor.start, anchor.end, format_table(grown), issues)
    lines = ["| " + " | ".join(c.replace("|", "\\|") for c in r) + " |" for r in rows]
    return _change(edit, anchor.end, anchor.end, "\n" + "\n".join(lines), issues)
