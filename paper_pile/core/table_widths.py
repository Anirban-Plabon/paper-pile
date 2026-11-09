"""Column widths the user dragged in rendered tables (user 2026-11-09).

Markdown has no place for a column width, so they are view state, kept per vault in
``<vault>/.paper-pile/table_widths.json`` (like the session) and never in the note: the note
stays plain GFM, other apps show it at its natural width, and losing the file loses nothing but
the widths. Only resized tables have an entry::

    {"notes/a.md": {"Name|Value|Note": [120, 80, 240]}}

A table is known by its header cells (joined with ``|``), so a table keeps its widths when rows
are edited or text is added around it; renaming a header column or changing the column count
starts it fresh. Widths are CSS pixels.
"""

import json
import logging
from pathlib import Path

from paper_pile.core.fsutil import atomic_write_bytes

log = logging.getLogger("paper_pile.table_widths")

WIDTHS_FILE = "table_widths.json"
MIN_WIDTH = 40  # px: narrower columns are not kept (the editor never draws them so)
MAX_WIDTH = 4000

Widths = dict[str, dict[str, list[int]]]


def table_key(header: list[str]) -> str:
    """How a table is known in the store: its header cells, trimmed, joined with ``|``."""
    return "|".join(cell.strip() for cell in header)


class TableWidths:
    """The store for one vault. Reads once; every change is written at once (it is tiny)."""

    def __init__(self, vault: Path) -> None:
        self._file = vault / ".paper-pile" / WIDTHS_FILE
        self._data: Widths = self._load()

    def _load(self) -> Widths:
        try:
            raw = json.loads(self._file.read_text(encoding="utf-8"))
        except (FileNotFoundError, ValueError, OSError):
            return {}
        if not isinstance(raw, dict):
            return {}
        out: Widths = {}
        for path, tables in raw.items():
            if not isinstance(tables, dict):
                continue
            kept = {k: _clean(v) for k, v in tables.items() if isinstance(k, str)}
            kept = {k: v for k, v in kept.items() if v}
            if kept:
                out[str(path)] = kept
        return out

    def _save(self) -> None:
        try:
            data = json.dumps(self._data, ensure_ascii=False, sort_keys=True).encode("utf-8")
            atomic_write_bytes(self._file, data)
        except OSError:
            log.warning("could not save table widths to %s", self._file, exc_info=True)

    def all(self) -> Widths:
        """Every stored width (a copy), for the editor."""
        return {p: {k: list(v) for k, v in t.items()} for p, t in self._data.items()}

    def set(self, path: str, key: str, widths: object) -> bool:
        """Remember ``widths`` for table ``key`` of note ``path``; an empty list forgets it.
        False when nothing changed (bad input included)."""
        clean = _clean(widths)
        tables = self._data.get(path, {})
        if clean == tables.get(key) or (not clean and key not in tables):
            return False
        if clean:
            tables[key] = clean
            self._data[path] = tables
        else:
            tables.pop(key, None)
            if not tables:
                self._data.pop(path, None)
        self._save()
        return True

    def renamed(self, old: str, new: str) -> bool:
        """A note or folder was renamed / moved: its widths follow it."""
        moved = {
            new + p[len(old) :]: t
            for p, t in self._data.items()
            if p == old or p.startswith(old.rstrip("/") + "/")
        }
        if not moved:
            return False
        for p in list(self._data):
            if p == old or p.startswith(old.rstrip("/") + "/"):
                del self._data[p]
        self._data.update(moved)
        self._save()
        return True

    def deleted(self, path: str) -> bool:
        """A note or folder went to the trash: forget its widths."""
        gone = [p for p in self._data if p == path or p.startswith(path.rstrip("/") + "/")]
        for p in gone:
            del self._data[p]
        if gone:
            self._save()
        return bool(gone)


def _clean(widths: object) -> list[int]:
    if not isinstance(widths, list) or not widths:
        return []
    out: list[int] = []
    for w in widths:
        if isinstance(w, bool) or not isinstance(w, int | float):
            return []
        out.append(max(MIN_WIDTH, min(MAX_WIDTH, round(w))))
    return out
