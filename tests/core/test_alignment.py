"""core/alignment.py: note and block alignment kept beside the vault (PLAN §4.34)."""

import json
from pathlib import Path

from paper_pile.core.alignment import ALIGN_FILE, Alignment


def _file(vault: Path) -> Path:
    return vault / ".paper-pile" / ALIGN_FILE


def test_note_and_blocks_are_saved_and_read_back(tmp_path: Path) -> None:
    a = Alignment(tmp_path)
    assert a.set_note("a.md", "center")
    assert a.set_blocks("a.md", {"Heading:# T": "right", "Table:| x |": "justify"})
    again = Alignment(tmp_path)
    assert again.note("a.md") == "center"
    assert again.all()["a.md"]["blocks"] == {"Heading:# T": "right", "Table:| x |": "justify"}


def test_no_change_writes_nothing(tmp_path: Path) -> None:
    a = Alignment(tmp_path)
    assert not a.set_note("a.md", None)
    assert not _file(tmp_path).exists()
    a.set_note("a.md", "right")
    assert not a.set_note("a.md", "right")


def test_clearing_everything_drops_the_note(tmp_path: Path) -> None:
    a = Alignment(tmp_path)
    a.set_note("a.md", "center")
    a.set_blocks("a.md", {"Paragraph:x": "right"})
    a.set_note("a.md", None)
    assert a.note("a.md") is None and a.all()["a.md"] == {"blocks": {"Paragraph:x": "right"}}
    a.set_blocks("a.md", {})
    assert "a.md" not in a.all()
    assert json.loads(_file(tmp_path).read_text()) == {}


def test_bad_values_are_dropped(tmp_path: Path) -> None:
    a = Alignment(tmp_path)
    assert not a.set_note("a.md", "middle")
    a.set_blocks("a.md", {"ok": "left", "bad": "up", "": "right", "n": 3})
    assert a.all()["a.md"]["blocks"] == {"ok": "left"}


def test_a_broken_file_is_ignored(tmp_path: Path) -> None:
    _file(tmp_path).parent.mkdir()
    _file(tmp_path).write_text('{"a.md": {"note": "up", "blocks": {"k": "center"}}, "b.md": 5')
    assert Alignment(tmp_path).all() == {}
    _file(tmp_path).write_text('{"a.md": {"note": "up", "blocks": {"k": "center"}}, "b.md": 5}')
    assert Alignment(tmp_path).all() == {"a.md": {"blocks": {"k": "center"}}}


def test_rename_and_delete_follow_notes_and_folders(tmp_path: Path) -> None:
    a = Alignment(tmp_path)
    a.set_note("d/a.md", "center")
    a.set_note("d/b.md", "right")
    a.set_note("x.md", "justify")
    assert a.renamed("d", "e")
    assert set(a.all()) == {"e/a.md", "e/b.md", "x.md"}
    assert a.renamed("x.md", "y.md") and a.note("y.md") == "justify"
    assert a.deleted("e")
    assert set(Alignment(tmp_path).all()) == {"y.md"}


# ---- export / print (PLAN §4.34) ---------------------------------------------------------

NOTE = """---
title: x
---
# Title

Some text.

| a | b |
| --- | --- |
| 1 | 2 |

$$
x^2
$$

```py
x = 1
```

Some text.
"""


def test_export_html_puts_block_and_note_alignment_on_the_blocks(tmp_path: Path) -> None:
    from paper_pile.core.export import export_html
    from paper_pile.core.vault import Vault

    vault = Vault(tmp_path)
    entry = {
        "note": "justify",
        "blocks": {
            "Heading:# Title": "center",
            "Table:| a | b |": "right",
            "BlockMath:$$": "left",
            "FencedCode:```py": "center",
            "Paragraph:Some text.#2": "right",
        },
    }
    html = export_html(vault, "n.md", NOTE, "n", (entry, "left"))
    assert '<h1 class="pp-al-center">Title</h1>' in html
    assert '<p class="pp-al-justify">Some text.</p>' in html  # the first one: the note's
    assert '<p class="pp-al-right">Some text.</p>' in html  # the repeat: its own
    assert '<table class="pp-al-right">' in html
    assert '<div class="math block">' in html  # left: no class
    assert 'class="pp-al-center language-py"' in html
    assert ".pp-al-center { text-align: center; }" in html


def test_without_alignment_the_html_is_unchanged(tmp_path: Path) -> None:
    from paper_pile.core.export import export_html
    from paper_pile.core.vault import Vault

    vault = Vault(tmp_path)
    plain = export_html(vault, "n.md", NOTE, "n")
    assert "pp-al-" not in plain.split("</style>")[1]
    assert export_html(vault, "n.md", NOTE, "n", (None, "left")) == plain


def test_print_page_keeps_alignment_without_wrappers() -> None:
    from paper_pile.core.printdoc import render_print_body

    entry = {"blocks": {"Heading:# Title": "right", "BlockMath:$$": "center"}}
    plain = render_print_body(NOTE, "n.md")
    aligned = render_print_body(NOTE, "n.md", align=(entry, "left"))
    assert '<h1 class="pp-al-right"' in aligned or 'class="pp-al-right"' in aligned
    assert 'class="math block pp-al-center"' in aligned
    # the same blocks: only class attributes added, so pages split the same way
    assert aligned.count("<") == plain.count("<")
    assert aligned.count("data-line=") == plain.count("data-line=")


def test_the_setting_aligns_notes_without_their_own() -> None:
    from paper_pile.core.printdoc import render_print_body

    body = render_print_body(NOTE, "n.md", align=(None, "center"))
    assert '<table class="pp-al-center"' in body or 'class="pp-al-center"' in body
    assert body.count("pp-al-center") >= 5
