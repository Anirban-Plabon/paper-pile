"""Moving a page break by dragging it in page view (PLAN §4.17).

The editor reports which break line was dragged (or that a page line the layout drew was) and
the line the page should now start at; this works out the new text. A break keeps how it was
written and gets the empty line above and below that it needs; the empty line it leaves
behind is dropped, so moving breaks around does not pile up empty lines.
"""

from paper_pile.core.pagebreak import PAGE_BREAK, is_break_line
from paper_pile.core.parser import page_breaks


def _blank(line: str) -> bool:
    return not line.strip()


def move_page_break(text: str, line: int | None, target: int) -> str | None:
    """``text`` with the page break on (1-based) ``line`` moved so the page starts at line
    ``target`` (the line the break goes above, as numbered in ``text``); ``line=None`` adds a
    new break there. ``None`` when nothing changes or a break would not count there (inside a
    code block, a list, a quote…)."""
    lines = text.split("\n")
    at = target - 1
    written = PAGE_BREAK
    if line is not None:
        idx = line - 1
        if not 0 <= idx < len(lines) or not is_break_line(lines[idx]):
            return None
        after = idx + 1
        while after < len(lines) and _blank(lines[after]):
            after += 1
        if idx <= at <= after:
            return None  # the page already starts there
        written = lines[idx]
        removed = 1
        del lines[idx]
        if idx < len(lines) and _blank(lines[idx]) and (idx == 0 or _blank(lines[idx - 1])):
            del lines[idx]  # the empty line the break needed
            removed += 1
        if at > idx:
            at -= removed
    at = max(0, min(at, len(lines)))
    while at < len(lines) and _blank(lines[at]):
        at += 1  # right above the text the page starts with
    insert = [written]
    if at > 0 and not _blank(lines[at - 1]):
        insert.insert(0, "")
    if at < len(lines):
        insert.append("")
    lines[at:at] = insert
    new = "\n".join(lines)
    break_line = at + insert.index(written) + 1
    if new == text or not any(b.line == break_line for b in page_breaks(new)):
        return None
    return new
