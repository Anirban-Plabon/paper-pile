"""Rewrite links after notes were renamed or moved, without touching anything else.

The rule: **every link keeps pointing at the note it pointed at before the move.** For each link
we resolve it from the source's old place against the old note list (what it meant), map that note
through the moves (what it should mean now), and resolve it again from the source's new place
against the new list (what it would mean if left alone). Only when those two differ is the link
edited, and only its target part: aliases, ``#headings``, ``!`` embeds, titles, ``#fragments`` and
every other byte of the note stay as they were.

A link is edited only when its place in the file is certain; otherwise it is counted as skipped.
This module is pure (no file access): callers pass the texts and apply the edits.
"""

import posixpath
from collections.abc import Collection, Mapping
from dataclasses import dataclass, field
from urllib.parse import quote, unquote

from markdown_it.common.normalize_url import normalizeLink
from markdown_it.common.utils import unescapeAll

from paper_pile.core.links import (
    parse_wikilink,
    resolve_md_link,
    resolve_wikilink,
    wikilink_forms,
)
from paper_pile.core.parser import LinkSpan, link_spans


@dataclass(frozen=True, slots=True)
class Edit:
    start: int
    end: int
    insert: str


@dataclass(slots=True)
class RewritePlan:
    edits: dict[str, list[Edit]] = field(default_factory=dict)  # by (new) note path
    texts: dict[str, str] = field(default_factory=dict)  # the rewritten text of those notes
    updated: int = 0  # links edited
    skipped: int = 0  # links that needed an edit but could not be located safely

    @property
    def notes_changed(self) -> int:
        return len(self.edits)


def apply_edits(text: str, edits: list[Edit]) -> str:
    """``text`` with non-overlapping ``edits`` applied."""
    out: list[str] = []
    pos = 0
    for edit in sorted(edits, key=lambda e: e.start):
        if edit.start < pos:
            raise ValueError("overlapping edits")
        out.append(text[pos : edit.start])
        out.append(edit.insert)
        pos = edit.end
    out.append(text[pos:])
    return "".join(out)


def plan_rewrites(
    moves: Mapping[str, str],
    new_paths: Collection[str],
    texts: Mapping[str, str],
    media: str = "",
) -> RewritePlan:
    """Edits that keep every link in ``texts`` pointing where it did.

    ``moves`` maps each moved note's old path to its new one; ``new_paths`` is every note path
    after the move; ``texts`` holds the notes to examine, keyed by their *new* path; ``media``
    is the shared images folder (its pictures do not move with a note).
    """
    old_of = {new: old for old, new in moves.items()}
    new_set = set(new_paths)
    old_set = {old_of.get(p, p) for p in new_set}
    plan = RewritePlan()
    for src_new, text in texts.items():
        if not src_new.lower().endswith(".md"):
            continue  # plain text has no links
        src_old = old_of.get(src_new, src_new)
        edits, skipped = plan_note(text, src_old, src_new, moves, old_set, new_set, media)
        plan.skipped += skipped
        if edits:
            plan.edits[src_new] = edits
            plan.texts[src_new] = apply_edits(text, edits)
            plan.updated += len(edits)
    return plan


def plan_note(
    text: str,
    src_old: str,
    src_new: str,
    moves: Mapping[str, str],
    old_set: set[str],
    new_set: set[str],
    media: str = "",
) -> tuple[list[Edit], int]:
    """The edits for one note whose text was at ``src_old`` and is now at ``src_new``, and how
    many links needed an edit but could not be located (``old_set``/``new_set``: every note
    path before/after)."""
    edits: list[Edit] = []
    if src_old != src_new:
        # the note's images folder is named after the note: a rename changes the paths
        from paper_pile.core.assets import plan_media_edits, plan_ref_edits

        edits.extend(plan_ref_edits(text, src_old, src_new))
        edits.extend(plan_media_edits(text, src_old, src_new, media))
    spans = link_spans(text)
    if not spans:
        return edits, 0
    starts = locate_spans(text, spans)
    skipped = 0
    for span, start in zip(spans, starts, strict=True):
        wanted = _wanted_target(span, src_old, src_new, moves, old_set, new_set)
        if wanted is None:
            continue  # nothing to change
        edit = (
            _make_edit(text, span, start, src_new, wanted, new_set) if start is not None else None
        )
        if edit is None:
            skipped += 1
        else:
            edits.append(edit)
    return edits, skipped


def _wanted_target(
    span: LinkSpan,
    src_old: str,
    src_new: str,
    moves: Mapping[str, str],
    old_set: set[str],
    new_set: set[str],
) -> str | None:
    """The note the link must be repointed at, or ``None`` if it already does the right thing."""
    if span.kind == "wiki":
        parsed = parse_wikilink(span.raw)
        if parsed is None or not parsed.note:
            return None  # [[#heading]] points into its own note, wherever that lives
        old_target = resolve_wikilink(parsed.note, src_old, old_set)
        if old_target is None:
            return None
        expected = moves.get(old_target, old_target)
        return None if resolve_wikilink(parsed.note, src_new, new_set) == expected else expected
    old_target = resolve_md_link(span.raw, src_old, old_set)
    if old_target is None:
        return None
    expected = moves.get(old_target, old_target)
    return None if resolve_md_link(span.raw, src_new, new_set) == expected else expected


# ---- where a link is in the file -----------------------------------------------------------


def locate_spans(text: str, spans: list[LinkSpan]) -> list[int | None]:
    """Absolute offset of each link's source text in ``text``, or ``None`` when not certain.

    Per line, links are matched to the textual occurrences of their source in order if the counts
    agree; otherwise each is placed by aligning the end of the line (container prefixes only ever
    add text at the start) and checked against the file. Anything else stays unlocated.
    """
    lines = text.split("\n")
    line_start = [0]
    for line in lines:
        line_start.append(line_start[-1] + len(line) + 1)
    groups: dict[tuple[int, str], list[int]] = {}
    for i, span in enumerate(spans):
        groups.setdefault((span.line, span.source), []).append(i)
    result: list[int | None] = [None] * len(spans)
    for (line_no, source), members in groups.items():
        if not 1 <= line_no <= len(lines):
            continue
        raw_line = lines[line_no - 1]
        found = _occurrences(raw_line, source)
        if len(found) == len(members):
            for i, col in zip(members, found, strict=True):
                result[i] = line_start[line_no - 1] + col
            continue
        for i in members:
            span = spans[i]
            tail = len(raw_line.rstrip()) - len(span.line_text.rstrip())
            col = tail + span.line_offset
            if tail >= 0 and raw_line[col : col + len(source)] == source:
                result[i] = line_start[line_no - 1] + col
    return result


def _occurrences(line: str, needle: str) -> list[int]:
    found = []
    i = line.find(needle)
    while i >= 0:
        found.append(i)
        i = line.find(needle, i + len(needle))
    return found


# ---- building the edit ------------------------------------------------------------------------


def _make_edit(
    text: str, span: LinkSpan, start: int, src_new: str, target: str, new_set: set[str]
) -> Edit | None:
    if text[start : start + len(span.source)] != span.source:
        return None
    if span.kind == "wiki":
        return _wiki_edit(span, start, src_new, target, new_set)
    return _md_edit(span, start, src_new, target)


def _wiki_edit(
    span: LinkSpan, start: int, src_new: str, target: str, new_set: set[str]
) -> Edit | None:
    inner = span.raw
    parsed = parse_wikilink(inner)
    if parsed is None:
        return None
    cut = min((i for i in (inner.find("#"), inner.find("|")) if i >= 0), default=len(inner))
    segment = inner[:cut]
    lead = len(segment) - len(segment.lstrip())
    old_note = parsed.note
    with_ext = old_note.lower().endswith((".md", ".txt"))
    forms = wikilink_forms(target, ext=with_ext)
    if "/" in old_note and len(forms) > 2:
        forms = [*forms[1:-1], forms[-1]]  # the author wrote a path: keep writing paths
    for form in forms:
        if resolve_wikilink(form, src_new, new_set) == target:
            begin = start + 2 + lead
            return Edit(begin, begin + len(old_note), form)
    return None


def _md_edit(span: LinkSpan, start: int, src_new: str, target: str) -> Edit | None:
    dest = scan_destination(span.source)
    if dest is None:
        return None
    d_start, d_end, angle = dest
    written = span.source[d_start:d_end]
    if normalizeLink(unescapeAll(written)) != span.raw:
        return None  # not the destination we think it is
    cut = min((i for i in (written.find("#"), written.find("?")) if i >= 0), default=len(written))
    suffix = written[cut:]
    folder = posixpath.dirname(src_new) or "."
    relative = posixpath.relpath(target, folder)
    if angle:
        new = relative if not any(c in relative for c in "<>\n\\") else quote(relative, safe="/")
    else:
        new = quote(relative, safe="/._-~")
    if unquote(new) != relative and not angle:
        return None
    return Edit(start + d_start, start + d_end, new + suffix)


def scan_destination(source: str) -> tuple[int, int, bool] | None:
    """Where the destination of an inline link ``[label](dest "title")`` sits in ``source``:
    ``(start, end, in_angle_brackets)``, or ``None`` if the link has no inline destination."""
    i, depth = 1, 1
    while i < len(source) and depth:
        c = source[i]
        if c == "\\":
            i += 2
            continue
        depth += (c == "[") - (c == "]")
        i += 1
    if depth or i >= len(source) or source[i] != "(":
        return None
    i += 1
    while i < len(source) and source[i] in " \t\n":
        i += 1
    if i >= len(source):
        return None
    if source[i] == "<":
        j = i + 1
        while j < len(source) and source[j] not in ">\n":
            j += 2 if source[j] == "\\" else 1
        return (i + 1, j, True) if j < len(source) and source[j] == ">" else None
    j, parens = i, 0
    while j < len(source):
        c = source[j]
        if c == "\\":
            j += 2
            continue
        if c in " \t\n":
            break
        if c == "(":
            parens += 1
        elif c == ")":
            if parens == 0:
                break
            parens -= 1
        j += 1
    return (i, j, False) if j > i else None
