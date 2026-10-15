"""GitHub-flavoured markdown tables: parse, format and edit them as data.

The editor shows a table as a grid of cells the user types into. Every rule about what that means
for the markdown lives here: the browser only reports what was done (``apply_op``) and applies the
text that comes back. The file text stays the single source of truth; a table is rewritten as a
tidy, column-aligned GFM table whenever it is edited.

Cells are handled as *values* (``a | b``); on the way out ``|`` becomes ``\\|`` and newlines become
spaces. Row 0 is the header.
"""

import logging
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any

log = logging.getLogger("paper_pile.tables")

ALIGNS = ("", "left", "center", "right")  # "" = no alignment given
MIN_WIDTH = 3
_PREFIX = re.compile(r"^[ \t]*(?:>[ \t]?)*[ \t]*")
_DELIM_CELL = re.compile(r"^\s*(:?)-+(:?)\s*$")


@dataclass(slots=True)
class Table:
    header: list[str]
    aligns: list[str]
    rows: list[list[str]] = field(default_factory=list)
    prefix: str = ""  # shared line start of a table inside a quote or list

    @property
    def columns(self) -> int:
        return len(self.header)

    def grid(self) -> list[list[str]]:
        """All rows, header first."""
        return [self.header, *self.rows]


@dataclass(frozen=True, slots=True)
class TableResult:
    text: str
    focus: tuple[int, int]  # (row, col) to put the cursor in afterwards; row 0 is the header


# ---- parsing ---------------------------------------------------------------------------------


def split_row(line: str) -> list[str]:
    """The cell values of one table row: split on ``|`` that is not escaped, outer pipes dropped,
    ``\\|`` turned back into ``|``."""
    body = line.strip()
    cells: list[str] = []
    current: list[str] = []
    i = 0
    while i < len(body):
        ch = body[i]
        if ch == "\\" and i + 1 < len(body) and body[i + 1] == "|":
            current.append("|")
            i += 2
            continue
        if ch == "|":
            cells.append("".join(current))
            current = []
        else:
            current.append(ch)
        i += 1
    cells.append("".join(current))
    if body.startswith("|"):
        cells = cells[1:]
    if body.endswith("|") and not body.endswith("\\|") and cells:
        cells = cells[:-1]
    return [c.strip() for c in cells]


def _parse_delimiter(line: str) -> list[str] | None:
    cells = split_row(line)
    aligns = []
    for cell in cells:
        m = _DELIM_CELL.match(cell)
        if not m:
            return None
        left, right = m.group(1), m.group(2)
        aligns.append("center" if left and right else "right" if right else "left" if left else "")
    return aligns or None


def parse_table(text: str) -> Table | None:
    """The table in ``text`` (whole lines, no blank lines), or ``None`` if it is not one."""
    lines = [ln for ln in text.split("\n") if ln.strip()]
    if len(lines) < 2:
        return None
    prefix_match = _PREFIX.match(lines[0])
    prefix = prefix_match.group(0) if prefix_match else ""
    stripped = []
    for ln in lines:
        stripped.append(ln[len(prefix) :] if ln.startswith(prefix) else ln.lstrip(" \t>").lstrip())
    header = split_row(stripped[0])
    aligns = _parse_delimiter(stripped[1])
    if not header or aligns is None or len(aligns) != len(header) or "|" not in stripped[0]:
        return None
    rows = []
    for ln in stripped[2:]:
        cells = split_row(ln)
        rows.append((cells + [""] * len(header))[: len(header)])
    return Table(header, aligns, rows, prefix)


# ---- formatting ------------------------------------------------------------------------------


def display_width(text: str) -> int:
    """Columns ``text`` takes in a monospace font (wide East-Asian characters take two)."""
    return sum(2 if unicodedata.east_asian_width(ch) in "WF" else 1 for ch in text)


def _escape(value: str) -> str:
    """A cell value as it is written in the file: one line, pipes escaped."""
    return " ".join(value.splitlines()).replace("|", "\\|").strip()


def format_table(table: Table) -> str:
    """The table as aligned GFM, without a trailing newline."""
    grid = [[_escape(c) for c in row] for row in table.grid()]
    widths = [
        max(MIN_WIDTH, *(display_width(row[i]) for row in grid)) for i in range(table.columns)
    ]

    def line(cells: list[str]) -> str:
        padded = []
        for i, cell in enumerate(cells):
            gap = widths[i] - display_width(cell)
            align = table.aligns[i]
            if align == "right":
                padded.append(" " * gap + cell)
            elif align == "center":
                padded.append(" " * (gap // 2) + cell + " " * (gap - gap // 2))
            else:
                padded.append(cell + " " * gap)
        return table.prefix + "| " + " | ".join(padded) + " |"

    def delimiter() -> str:
        marks = []
        for i, align in enumerate(table.aligns):
            w = widths[i]
            if align == "center":
                marks.append(":" + "-" * (w - 2) + ":")
            elif align == "right":
                marks.append("-" * (w - 1) + ":")
            elif align == "left":
                marks.append(":" + "-" * (w - 1))
            else:
                marks.append("-" * w)
        return table.prefix + "| " + " | ".join(marks) + " |"

    out = [line(grid[0]), delimiter(), *(line(row) for row in grid[1:])]
    return "\n".join(out)


def table_extent(text: str, start: int) -> int | None:
    """Where the table that starts at offset ``start`` (a line start) ends in ``text``: the end of
    its last line. The table is its consecutive non-blank lines, up to a line that starts another
    block (heading or code fence). ``None`` if no table starts there.

    The editor only tells us where a table *starts*: the table's length changes with every edit,
    so a length measured by the browser could already be out of date when the edit arrives.
    """
    if start < 0 or start > len(text) or (start and text[start - 1] != "\n"):
        return None
    end = start
    lines: list[str] = []
    for line in text[start:].split("\n"):
        body = line.lstrip(" \t>").lstrip()
        if not line.strip() or (lines and body.startswith(("#", "```", "~~~"))):
            break
        lines.append(line)
        end += len(line) + 1
    end = max(start, end - 1)
    return end if parse_table("\n".join(lines)) is not None else None


# ---- operations ------------------------------------------------------------------------------


def _int(op: dict[str, Any], key: str) -> int | None:
    value = op.get(key)
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def apply_op(text: str, op: dict[str, Any]) -> TableResult | None:
    """Apply one user action to the table in ``text``; the new table text and where the cursor
    goes. ``None`` if ``text`` is not a table or the action is unknown or out of range."""
    table = parse_table(text)
    kind = op.get("op")
    if table is None or not isinstance(kind, str):
        return None
    handler = _OPS.get(kind)
    focus = handler(table, op) if handler else None
    if focus is None:
        log.warning("ignored table operation %r", op)
        return None
    return TableResult(format_table(table), focus)


def _op_cell(t: Table, op: dict[str, Any]) -> tuple[int, int] | None:
    row, col, value = _int(op, "row"), _int(op, "col"), op.get("value")
    if row is None or col is None or not isinstance(value, str):
        return None
    if not (0 <= row <= len(t.rows) and 0 <= col < t.columns):
        return None
    t.grid()[row][col] = " ".join(value.splitlines()).strip()
    return row, col


def _op_insert_row(t: Table, op: dict[str, Any]) -> tuple[int, int] | None:
    at = _int(op, "at")  # body row index in the grid (1 = first body row) the new row takes
    if at is None or not 1 <= at <= len(t.rows) + 1:
        return None
    t.rows.insert(at - 1, [""] * t.columns)
    return at, 0


def _op_delete_row(t: Table, op: dict[str, Any]) -> tuple[int, int] | None:
    row = _int(op, "row")
    if row is None or not 1 <= row <= len(t.rows):
        return None  # the header cannot be deleted
    del t.rows[row - 1]
    return min(row, len(t.rows)), 0


def _op_move_row(t: Table, op: dict[str, Any]) -> tuple[int, int] | None:
    row, to = _int(op, "row"), _int(op, "to")
    if row is None or to is None or not (1 <= row <= len(t.rows) and 1 <= to <= len(t.rows)):
        return None
    t.rows.insert(to - 1, t.rows.pop(row - 1))
    return to, 0


def _op_insert_col(t: Table, op: dict[str, Any]) -> tuple[int, int] | None:
    at = _int(op, "at")
    if at is None or not 0 <= at <= t.columns:
        return None
    t.header.insert(at, "")
    t.aligns.insert(at, "")
    for row in t.rows:
        row.insert(at, "")
    return 0, at


def _op_delete_col(t: Table, op: dict[str, Any]) -> tuple[int, int] | None:
    col = _int(op, "col")
    if col is None or not 0 <= col < t.columns or t.columns == 1:
        return None  # a table keeps at least one column
    del t.header[col], t.aligns[col]
    for row in t.rows:
        del row[col]
    return 0, min(col, t.columns - 1)


def _op_align(t: Table, op: dict[str, Any]) -> tuple[int, int] | None:
    col, align = _int(op, "col"), op.get("align")
    if col is None or not 0 <= col < t.columns or align not in ALIGNS:
        return None
    t.aligns[col] = str(align)
    return 0, col


_OPS = {
    "cell": _op_cell,
    "insert_row": _op_insert_row,
    "delete_row": _op_delete_row,
    "move_row": _op_move_row,
    "insert_col": _op_insert_col,
    "delete_col": _op_delete_col,
    "align": _op_align,
}
