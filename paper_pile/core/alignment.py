"""Text alignment of whole notes and of single blocks (user 2026-11-11, PLAN §4.34).

Markdown has no alignment, so — like table column widths (``core/table_widths.py``) — it is
view state, kept per vault in ``<vault>/.paper-pile/alignment.json`` and never in the note::

    {"notes/a.md": {"note": "center", "blocks": {"Heading:# Title": "right"}}}

``note`` is the whole note's alignment (absent: the Settings default ``editor.align``);
``blocks`` maps a block's key (made by the editor, ``tools/editor_src/align.js``: the block's
kind and first line, ``#n`` for repeats) to its own alignment. Precedence: block > note >
setting. Losing the file loses nothing but the alignment.
"""

import json
import logging
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from markdown_it.token import Token

from paper_pile.core.fsutil import atomic_write_bytes

log = logging.getLogger("paper_pile.alignment")

ALIGN_FILE = "alignment.json"
ALIGNS = ("left", "center", "right", "justify")
MAX_KEY = 300  # a block key longer than this is not a key the editor makes

Entry = dict[str, Any]  # {"note"?: str, "blocks"?: {key: str}}


def clean_align(value: object) -> str | None:
    """``value`` if it is one of :data:`ALIGNS`, else None."""
    return value if isinstance(value, str) and value in ALIGNS else None


def clean_blocks(blocks: object) -> dict[str, str]:
    """Only the well-formed ``{key: align}`` pairs of ``blocks``."""
    if not isinstance(blocks, dict):
        return {}
    out: dict[str, str] = {}
    for key, value in blocks.items():
        align = clean_align(value)
        if isinstance(key, str) and key and len(key) <= MAX_KEY and align:
            out[key] = align
    return out


class Alignment:
    """The store for one vault. Reads once; every change is written at once (it is tiny)."""

    def __init__(self, vault: Path) -> None:
        self._file = vault / ".paper-pile" / ALIGN_FILE
        self._data: dict[str, Entry] = self._load()

    def _load(self) -> dict[str, Entry]:
        try:
            raw = json.loads(self._file.read_text(encoding="utf-8"))
        except (FileNotFoundError, ValueError, OSError):
            return {}
        if not isinstance(raw, dict):
            return {}
        out: dict[str, Entry] = {}
        for path, entry in raw.items():
            if not isinstance(entry, dict):
                continue
            clean = _entry(clean_align(entry.get("note")), clean_blocks(entry.get("blocks")))
            if clean:
                out[str(path)] = clean
        return out

    def _save(self) -> None:
        try:
            self._file.parent.mkdir(parents=True, exist_ok=True)
            data = json.dumps(self._data, ensure_ascii=False, sort_keys=True).encode("utf-8")
            atomic_write_bytes(self._file, data)
        except OSError:
            log.warning("could not save alignment to %s", self._file, exc_info=True)

    def all(self) -> dict[str, Entry]:
        """Every stored alignment (a copy), for the editor."""
        return {p: json.loads(json.dumps(e)) for p, e in self._data.items()}

    def note(self, path: str) -> str | None:
        """The whole note's own alignment (None: it follows the setting)."""
        return self._data.get(path, {}).get("note")

    def set_note(self, path: str, align: object) -> bool:
        """Align the whole note; None (or a bad value) makes it follow the setting again.
        False when nothing changed."""
        entry = self._data.get(path, {})
        return self._put(path, _entry(clean_align(align), entry.get("blocks", {})))

    def set_blocks(self, path: str, blocks: object) -> bool:
        """Replace the note's block alignments (the editor sends them all at once)."""
        entry = self._data.get(path, {})
        return self._put(path, _entry(entry.get("note"), clean_blocks(blocks)))

    def _put(self, path: str, entry: Entry) -> bool:
        if entry == self._data.get(path, {}):
            return False
        if entry:
            self._data[path] = entry
        else:
            self._data.pop(path, None)
        self._save()
        return True

    def renamed(self, old: str, new: str) -> bool:
        """A note or folder was renamed / moved: its alignment follows it."""
        inside = [p for p in self._data if p == old or p.startswith(old.rstrip("/") + "/")]
        if not inside:
            return False
        for p in inside:
            self._data[new + p[len(old) :]] = self._data.pop(p)
        self._save()
        return True

    def deleted(self, path: str) -> bool:
        """A note or folder went to the trash: forget its alignment."""
        gone = [p for p in self._data if p == path or p.startswith(path.rstrip("/") + "/")]
        for p in gone:
            del self._data[p]
        if gone:
            self._save()
        return bool(gone)


# ---- export / print (PLAN §4.34): the same alignment on the rendered blocks ------------------

# the editor's block kinds (Lezer node names, align.js `kindOf`) for markdown-it's top-level tokens
_KINDS = {
    "heading_open": "Heading",
    "paragraph_open": "Paragraph",
    "bullet_list_open": "BulletList",
    "ordered_list_open": "OrderedList",
    "blockquote_open": "Blockquote",
    "table_open": "Table",
    "fence": "FencedCode",
    "code_block": "CodeBlock",
    "math_block": "BlockMath",
    "hr": "HorizontalRule",
    "page_break": "PageBreak",
    "html_block": "HTMLBlock",
}
KEY_CHARS = 120  # align.js KEY_CHARS


def block_keys(tokens: Sequence[Token], lines: Sequence[str]) -> list[tuple[int, str]]:
    """``(token index, key)`` of every top-level block, keyed as the editor keys it: kind and
    first line (``lines`` = the note's own text, so a rewritten line, an inlined image, does
    not change the key), ``#n`` from the second repeat on."""
    seen: dict[str, int] = {}
    out: list[tuple[int, str]] = []
    for i, tok in enumerate(tokens):
        kind = _KINDS.get(tok.type)
        if tok.level != 0 or kind is None or not tok.map or tok.map[0] >= len(lines):
            continue
        base = f"{kind}:{lines[tok.map[0]].strip()[:KEY_CHARS]}"
        seen[base] = seen.get(base, 0) + 1
        out.append((i, base if seen[base] == 1 else f"{base}#{seen[base]}"))
    return out


def align_tokens(
    tokens: Sequence[Token], lines: Sequence[str], entry: Entry | None, default: str = "left"
) -> None:
    """Put the alignment on the rendered blocks as ``pp-al-<align>`` classes: a block's own,
    else the note's (else ``default``, the setting). On the block's own element, never a
    wrapper, so the print page splits the same blocks onto sheets and keeps it."""
    blocks = clean_blocks((entry or {}).get("blocks"))
    note = clean_align((entry or {}).get("note")) or clean_align(default) or "left"
    for i, key in block_keys(tokens, lines):
        align = blocks.get(key, note)
        if align != "left":
            tokens[i].attrJoin("class", f"pp-al-{align}")


# CSS for exported pages: text aligns; a table, a code block or a diagram is placed as a whole
ALIGN_CSS = """
/* PLAN §4.34 */
.pp-al-left { text-align: left; } .pp-al-center { text-align: center; }
.pp-al-right { text-align: right; } .pp-al-justify { text-align: justify; }
pre:has(> code.pp-al-center), pre:has(> code.pp-al-right) { width: fit-content; max-width: 100%; }
pre:has(> code.pp-al-center), table.pp-al-center { margin-left: auto; margin-right: auto; }
pre:has(> code.pp-al-right), table.pp-al-right { margin-left: auto; margin-right: 0; }
table.pp-al-center, table.pp-al-right, code.pp-al-center, code.pp-al-right { text-align: left; }
"""


def _entry(note: str | None, blocks: dict[str, str]) -> Entry:
    out: Entry = {}
    if note:
        out["note"] = note
    if blocks:
        out["blocks"] = dict(blocks)
    return out
