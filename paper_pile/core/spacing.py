"""Blocks on lines of their own, with an empty line above and below (Settings → Editor →
Advanced → "Blank lines around blocks", on by default).

Tables, images, embeds, code / math / diagram blocks, callouts, headings, lists and quotes are
hard to get the caret around when they touch other text: an empty line on each side always
leaves somewhere to click or type. Pure: callers apply the returned text.
"""

QUOTE = ">"


def _joins(line: str, body: str) -> bool:
    """Would an empty line between ``line`` and ``body`` split one block in two? (A quote
    inserted next to a quote line continues that quote.)"""
    return line.lstrip().startswith(QUOTE) and body.lstrip().startswith(QUOTE)


def spaced_block(
    text: str, start: int, end: int, body: str, *, blank_lines: bool = True
) -> tuple[str, int]:
    """Put ``body`` in place of ``text[start:end]`` as a block of its own.

    Returns ``(insert, offset)``: the text to insert there and where ``body`` starts inside it.
    The block always gets its own lines; with ``blank_lines`` an empty line separates it from
    text above and below. At the end of the note a line is left below it either way.
    """
    body = body.rstrip("\n")
    before, after = text[:start], text[end:]
    line_start = before.rfind("\n") + 1
    head = before[line_start:]  # what precedes the block on its line
    above = before[: line_start - 1].rsplit("\n", 1)[-1] if line_start else None
    rest, newline, below = after.partition("\n")
    under = below.split("\n", 1)[0] if newline else None

    lead = ""
    if head.strip():
        lead = "\n\n" if blank_lines else "\n"
    elif blank_lines and above is not None and above.strip() and not _joins(above, body):
        lead = "\n"

    tail = ""
    if rest.strip():
        tail = "\n\n" if blank_lines else "\n"
    elif not newline:
        tail = "\n"  # end of the note: leave a line to go to
    elif blank_lines and under is not None and under.strip() and not _joins(under, body):
        tail = "\n"
    return lead + body + tail, len(lead)
