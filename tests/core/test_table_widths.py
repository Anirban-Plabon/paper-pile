import json
from pathlib import Path

from paper_pile.core.table_widths import MIN_WIDTH, WIDTHS_FILE, TableWidths, table_key
from paper_pile.core.tables import apply_op, pasted_cells


def store(tmp_path: Path) -> TableWidths:
    (tmp_path / ".paper-pile").mkdir(exist_ok=True)
    return TableWidths(tmp_path)


def test_key_is_the_trimmed_header() -> None:
    assert table_key([" Name ", "Value"]) == "Name|Value"


def test_set_saves_and_reloads(tmp_path: Path) -> None:
    s = store(tmp_path)
    assert s.set("a.md", "A|B", [120, 80.6])
    assert TableWidths(tmp_path).all() == {"a.md": {"A|B": [120, 81]}}
    assert not s.set("a.md", "A|B", [120, 81])  # unchanged: no write needed


def test_bad_input_is_ignored_and_widths_are_clamped(tmp_path: Path) -> None:
    s = store(tmp_path)
    assert not s.set("a.md", "A", "wide")
    assert not s.set("a.md", "A", [True])
    assert s.set("a.md", "A", [1, 10**9])
    assert s.all()["a.md"]["A"][0] == MIN_WIDTH


def test_empty_list_forgets(tmp_path: Path) -> None:
    s = store(tmp_path)
    s.set("a.md", "A", [100])
    assert s.set("a.md", "A", [])
    assert s.all() == {}


def test_rename_and_delete_follow_the_note(tmp_path: Path) -> None:
    s = store(tmp_path)
    s.set("d/a.md", "A", [100])
    s.set("other.md", "A", [90])
    assert s.renamed("d", "e")
    assert set(s.all()) == {"e/a.md", "other.md"}
    assert s.deleted("e/a.md")
    assert set(TableWidths(tmp_path).all()) == {"other.md"}


def test_corrupt_file_is_ignored(tmp_path: Path) -> None:
    (tmp_path / ".paper-pile").mkdir()
    (tmp_path / ".paper-pile" / WIDTHS_FILE).write_text("{not json")
    assert TableWidths(tmp_path).all() == {}
    (tmp_path / ".paper-pile" / WIDTHS_FILE).write_text(json.dumps({"a.md": {"A": ["x"]}}))
    assert TableWidths(tmp_path).all() == {}


TABLE = "| A | B | C |\n|---|---|---|\n| 1 | 2 | 3 |\n| 4 | 5 | 6 |\n"


def test_cells_op_clears_a_block() -> None:
    out = apply_op(TABLE, {"op": "cells", "row": 1, "col": 1, "values": [["", ""], ["", ""]]})
    assert out is not None
    rows = [[c.strip() for c in line.split("|")[1:-1]] for line in out.text.splitlines()]
    assert rows[2:] == [["1", "", ""], ["4", "", ""]]


def test_cells_op_pastes_and_clips_at_the_edges() -> None:
    out = apply_op(TABLE, {"op": "cells", "row": 2, "col": 2, "values": [["x", "y"], ["z"]]})
    assert out is not None
    assert out.text.splitlines()[3].replace(" ", "") == "|4|5|x|"
    assert len(out.text.splitlines()) == 4  # no row added


def test_cells_op_rejects_bad_input() -> None:
    assert apply_op(TABLE, {"op": "cells", "row": 9, "col": 0, "values": [["x"]]}) is None
    assert apply_op(TABLE, {"op": "cells", "row": 0, "col": 0, "values": "x"}) is None


def test_pasted_cells_reads_a_markdown_table_or_tsv() -> None:
    assert pasted_cells("| a | b |\n|---|---|\n| 1 | x \\| y |\n") == [["a", "b"], ["1", "x | y"]]
    assert pasted_cells("a\tb\r\n1\t2\n") == [["a", "b"], ["1", "2"]]


def test_paste_op_writes_a_copied_markdown_block() -> None:
    block = "| X | Y |\n|---|---|\n| Z | W |"
    out = apply_op(TABLE, {"op": "paste", "row": 1, "col": 0, "text": block})
    assert out is not None
    rows = [[c.strip() for c in line.split("|")[1:-1]] for line in out.text.splitlines()]
    assert rows[2:] == [["X", "Y", "3"], ["Z", "W", "6"]]
