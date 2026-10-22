"""Manual page breaks (PLAN §4.17).

A page break is a line of its own written as :data:`PAGE_BREAK` (``---/``, what paper-pile
writes) or one of the HTML forms other tools write (see :data:`LINE`), at top level, with an empty
line (or the start/end of the file) above and below. The block rule that applies those conditions
lives in ``core/parser.py``; the editor grammar (``tools/editor_src/pagebreak.js``) copies both,
checked against ``tests/fixtures/pagebreak_cases.json``.

A break only *does* something with content on both sides of it: one at the start or end of the
note is ignored, and a run of breaks with nothing but empty lines between them counts once.
"""

import re
from collections.abc import Sequence

PAGE_BREAK = "---/"

_Q = r"""(["'])"""
LINE = re.compile(
    r"^ {0,3}(?:---/|<div[ \t]+(?:"
    rf"style[ \t]*=[ \t]*{_Q}[ \t]*"
    r"(?:page-break-after[ \t]*:[ \t]*always|break-after[ \t]*:[ \t]*page)"
    r"[ \t]*;?[ \t]*\1"
    rf"|class[ \t]*=[ \t]*{_Q}[ \t]*page-break[ \t]*\2"
    r")[ \t]*>[ \t]*</div[ \t]*>)[ \t]*$",
    re.IGNORECASE,
)


def is_break_line(line: str) -> bool:
    """Is ``line`` (without its newline) written as a page break."""
    return LINE.match(line) is not None


def effective(blocks: Sequence[bool]) -> list[bool]:
    """For a note's top-level blocks in order (``True`` = a page break), which of the breaks
    start a new page: content before and after it, and not right after another break."""
    out = [False] * len(blocks)
    seen_content = False
    pending: int | None = None  # the break waiting for content after it
    for i, is_break in enumerate(blocks):
        if not is_break:
            if pending is not None:
                out[pending] = True
                pending = None
            seen_content = True
        elif seen_content and pending is None:
            pending = i
    return out
