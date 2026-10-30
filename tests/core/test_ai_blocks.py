"""P26.2: the note as numbered blocks for AI edits (PLAN §4.29)."""

from paper_pile.core.ai.blocks import block_map

NOTE = """---
title: T
---
# Hosting

We compare three options.

- **Docker**: one container
- **VM**: a whole machine

  with a second paragraph
- **Bare metal**

## Table

| Name | Price |
|---|---|
| Docker | 0 |

```python
print("x")
```

```mermaid
graph TD
```

$$
x^2
$$

Setext title
---

1. one
2. two
"""


def test_ids_kinds_and_text() -> None:
    blocks = block_map(NOTE)
    got = [(b.id, b.kind, b.text(NOTE).split("\n")[0]) for b in blocks]
    assert got == [
        ("B0", "front_matter", "---"),
        ("B1", "heading", "# Hosting"),
        ("B2", "paragraph", "We compare three options."),
        ("B3", "item", "- **Docker**: one container"),
        ("B4", "item", "- **VM**: a whole machine"),
        ("B5", "item", "- **Bare metal**"),
        ("B6", "heading", "## Table"),
        ("B7", "table", "| Name | Price |"),
        ("B8", "code", "```python"),
        ("B9", "diagram", "```mermaid"),
        ("B10", "math", "$$"),
        ("B11", "heading", "Setext title"),
        ("B12", "item", "1. one"),
        ("B13", "item", "2. two"),
    ]
    by_id = {b.id: b for b in blocks}
    assert by_id["B4"].text(NOTE) == "- **VM**: a whole machine\n\n  with a second paragraph"
    assert by_id["B7"].text(NOTE).endswith("| Docker | 0 |")  # one block, no trailing newline


def test_levels_paths_lists_and_fixed() -> None:
    by_id = {b.id: b for b in block_map(NOTE)}
    assert (by_id["B1"].level, by_id["B6"].level, by_id["B11"].level) == (1, 2, 2)
    assert by_id["B2"].path == ("Hosting",)
    assert by_id["B7"].path == ("Hosting", "Table")
    assert by_id["B12"].path == ("Hosting", "Setext title")  # a sibling of Table, not under it
    assert by_id["B3"].list_id == by_id["B5"].list_id != by_id["B12"].list_id != ""
    assert by_id["B2"].list_id == ""
    assert {i for i, b in by_id.items() if b.fixed} == {"B0", "B8", "B9", "B10"}
    assert [b.line for b in block_map(NOTE)][:3] == [1, 4, 6]


def test_offsets_with_windows_line_endings() -> None:
    crlf = NOTE.replace("\n", "\r\n")
    for plain, windows in zip(block_map(NOTE), block_map(crlf), strict=True):
        assert windows.text(crlf).replace("\r\n", "\n") == plain.text(NOTE)
        assert not windows.text(crlf).endswith("\r")


def test_lines_in_no_block_and_empty_notes() -> None:
    assert block_map("") == []
    assert [b.kind for b in block_map("[ref]: https://x.org\n\ntext\n")] == ["raw", "paragraph"]
