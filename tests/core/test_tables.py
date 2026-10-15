import random
import re

import pytest

from paper_pile.core.parser import render_html
from paper_pile.core.tables import (
    Table,
    apply_op,
    display_width,
    format_table,
    parse_table,
    split_row,
    table_extent,
)

SIMPLE = "| a | b |\n| --- | --- |\n| 1 | 2 |\n| 3 | 4 |"


def values(text: str) -> list[list[str]]:
    t = parse_table(text)
    assert t is not None
    return t.grid()


# ---- parsing ---------------------------------------------------------------------------------


def test_split_row_basics() -> None:
    assert split_row("| a | b | c |") == ["a", "b", "c"]
    assert split_row("a | b") == ["a", "b"]
    assert split_row("|a|b|") == ["a", "b"]
    assert split_row("| a | |") == ["a", ""]
    assert split_row("| a \\| b | c |") == ["a | b", "c"]  # escaped pipe stays inside the cell
    assert split_row("| a | b \\|") == ["a", "b |"]  # ... even at the end
    assert split_row("|  |  |") == ["", ""]


def test_parse_table_basic_and_alignments() -> None:
    t = parse_table("| L | C | R | N |\n|:--|:-:|--:|---|\n| 1 | 2 | 3 | 4 |")
    assert t is not None
    assert t.aligns == ["left", "center", "right", ""]
    assert t.header == ["L", "C", "R", "N"] and t.rows == [["1", "2", "3", "4"]]


def test_parse_ragged_rows_are_padded_and_cut() -> None:
    t = parse_table("| a | b |\n|---|---|\n| 1 |\n| 1 | 2 | 3 |")
    assert t is not None and t.rows == [["1", ""], ["1", "2"]]


def test_parse_inside_a_quote_and_indented() -> None:
    t = parse_table("> | a | b |\n> |---|---|\n> | 1 | 2 |")
    assert t is not None and t.prefix == "> " and t.rows == [["1", "2"]]
    assert format_table(t).splitlines()[0].startswith("> | a")
    t = parse_table("  | a |\n  |---|\n  | 1 |")
    assert t is not None and t.prefix == "  "


@pytest.mark.parametrize(
    "text",
    ["", "just text", "| a | b |", "| a | b |\n| x | y |", "| a |\n| --- | --- |", "a\n---"],
)
def test_parse_rejects_non_tables(text: str) -> None:
    assert parse_table(text) is None


# ---- formatting ------------------------------------------------------------------------------


def test_format_pads_columns() -> None:
    out = format_table(parse_table("|a|bbbb|\n|-|-|\n|long cell|x|") or Table([], []))
    assert out.splitlines() == [
        "| a         | bbbb |",
        "| --------- | ---- |",
        "| long cell | x    |",
    ]


def test_format_alignment_and_min_width() -> None:
    t = parse_table("| a | b | c |\n|:--|--:|:-:|\n| 1 | 22 | 333 |")
    assert t is not None
    assert format_table(t).splitlines() == [
        "| a   |   b |  c  |",
        "| :-- | --: | :-: |",
        "| 1   |  22 | 333 |",
    ]


def test_format_escapes_pipes_and_newlines() -> None:
    t = Table(["a|b", "c"], ["", ""], [["x\ny", "p|q"]])
    out = format_table(t)
    assert "a\\|b" in out and "x y" in out and "p\\|q" in out
    assert parse_table(out) is not None and values(out)[1] == ["x y", "p|q"]


def test_wide_characters_align() -> None:
    assert display_width("日本") == 4 and display_width("ab") == 2
    out = format_table(parse_table("| 日本 | b |\n|---|---|\n| ab | c |") or Table([], []))
    lines = out.splitlines()
    assert len({display_width(ln) for ln in lines}) == 1  # every line equally wide


def test_format_is_idempotent_and_valid() -> None:
    once = format_table(parse_table(SIMPLE) or Table([], []))
    assert format_table(parse_table(once) or Table([], [])) == once
    html = render_html(once)
    assert "<table>" in html and html.count("<tr>") == 3


# ---- operations ------------------------------------------------------------------------------


def run(text: str, **op: object) -> tuple[str, tuple[int, int]]:
    result = apply_op(text, dict(op))
    assert result is not None, op
    return result.text, result.focus


def test_set_cell_header_and_body() -> None:
    text, focus = run(SIMPLE, op="cell", row=1, col=1, value="two | 2")
    assert values(text) == [["a", "b"], ["1", "two | 2"], ["3", "4"]] and focus == (1, 1)
    text, _ = run(SIMPLE, op="cell", row=0, col=0, value="Name")
    assert values(text)[0] == ["Name", "b"]
    text, _ = run(SIMPLE, op="cell", row=2, col=0, value="  multi\nline ")
    assert values(text)[2][0] == "multi line"


def test_insert_and_delete_rows() -> None:
    text, focus = run(SIMPLE, op="insert_row", at=2)
    assert values(text) == [["a", "b"], ["1", "2"], ["", ""], ["3", "4"]] and focus == (2, 0)
    text, _ = run(SIMPLE, op="insert_row", at=3)  # append
    assert values(text)[-1] == ["", ""]
    text, focus = run(SIMPLE, op="delete_row", row=1)
    assert values(text) == [["a", "b"], ["3", "4"]] and focus == (1, 0)
    text, focus = run(SIMPLE, op="delete_row", row=2)
    assert values(text) == [["a", "b"], ["1", "2"]] and focus == (1, 0)


def test_move_row() -> None:
    text, focus = run(SIMPLE, op="move_row", row=2, to=1)
    assert values(text)[1:] == [["3", "4"], ["1", "2"]] and focus == (1, 0)


def test_insert_and_delete_columns() -> None:
    text, focus = run(SIMPLE, op="insert_col", at=1)
    assert values(text) == [["a", "", "b"], ["1", "", "2"], ["3", "", "4"]] and focus == (0, 1)
    text, _ = run(SIMPLE, op="insert_col", at=2)
    assert values(text)[0] == ["a", "b", ""]
    text, focus = run(SIMPLE, op="delete_col", col=0)
    assert values(text) == [["b"], ["2"], ["4"]] and focus == (0, 0)


def test_align_column() -> None:
    text, _ = run(SIMPLE, op="align", col=1, align="right")
    t = parse_table(text)
    assert t is not None and t.aligns == ["", "right"]
    text, _ = run(text, op="align", col=1, align="")
    assert (parse_table(text) or Table([], [])).aligns == ["", ""]


@pytest.mark.parametrize(
    "op",
    [
        {"op": "cell", "row": 9, "col": 0, "value": "x"},
        {"op": "cell", "row": 0, "col": 5, "value": "x"},
        {"op": "cell", "row": 0, "col": 0},  # no value
        {"op": "cell", "row": "0", "col": 0, "value": "x"},
        {"op": "cell", "row": True, "col": 0, "value": "x"},
        {"op": "insert_row", "at": 0},  # nothing goes above the header
        {"op": "insert_row", "at": 9},
        {"op": "delete_row", "row": 0},  # the header stays
        {"op": "delete_row", "row": 9},
        {"op": "move_row", "row": 0, "to": 1},
        {"op": "move_row", "row": 1, "to": 5},
        {"op": "insert_col", "at": -1},
        {"op": "delete_col", "col": 7},
        {"op": "align", "col": 0, "align": "diagonal"},
        {"op": "explode"},
        {},
    ],
)
def test_bad_operations_are_ignored(op: dict[str, object]) -> None:
    assert apply_op(SIMPLE, op) is None


def test_last_column_cannot_be_deleted() -> None:
    assert apply_op("| a |\n| --- |\n| 1 |", {"op": "delete_col", "col": 0}) is None


def test_not_a_table_is_ignored() -> None:
    assert apply_op("hello", {"op": "cell", "row": 0, "col": 0, "value": "x"}) is None


def test_prefix_survives_every_op() -> None:
    quoted = "> | a | b |\n> | --- | --- |\n> | 1 | 2 |"
    text, _ = run(quoted, op="insert_row", at=2)
    assert all(ln.startswith("> ") for ln in text.splitlines())
    text, _ = run(text, op="cell", row=2, col=1, value="x")
    assert all(ln.startswith("> ") for ln in text.splitlines())


def test_rendered_html_matches_the_values() -> None:
    text, _ = run(SIMPLE, op="cell", row=1, col=0, value="**bold** | pipe")
    html = render_html(text)
    assert "<strong>bold</strong> | pipe" in html and html.count("<td") == 4


def test_random_operations_keep_a_valid_table() -> None:
    rng = random.Random(7)
    text = SIMPLE
    for _ in range(300):
        t = parse_table(text)
        assert t is not None
        rows, cols = len(t.rows), t.columns
        op: dict[str, object] = rng.choice(
            [
                {
                    "op": "cell",
                    "row": rng.randint(0, rows),
                    "col": rng.randrange(cols),
                    "value": rng.choice(["x", "a|b", "日本", "", "`c`"]),
                },
                {"op": "insert_row", "at": rng.randint(1, rows + 1)},
                {"op": "delete_row", "row": rng.randint(1, max(1, rows))},
                {"op": "insert_col", "at": rng.randint(0, cols)},
                {"op": "delete_col", "col": rng.randrange(cols)},
                {
                    "op": "align",
                    "col": rng.randrange(cols),
                    "align": rng.choice(["", "left", "center", "right"]),
                },
                {
                    "op": "move_row",
                    "row": rng.randint(1, max(1, rows)),
                    "to": rng.randint(1, max(1, rows)),
                },
            ]
        )
        result = apply_op(text, op)
        if result is not None:
            text = result.text
        html = render_html(text)
        parsed = parse_table(text)
        assert parsed is not None and "<table>" in html
        assert html.count("<tr>") == 1 + len(parsed.rows)
        assert len(re.findall(r"<th[ >]", html)) == parsed.columns
        assert format_table(parsed) == text  # always already tidy


# ---- finding a table in the text ---------------------------------------------------------------


def test_table_extent() -> None:
    text = "intro\n\n| a | b |\n| - | - |\n| 1 | 2 |\n| 3 | 4 |\n\nafter\n"
    start = text.index("| a")
    end = table_extent(text, start)
    assert end is not None and text[start:end] == "| a | b |\n| - | - |\n| 1 | 2 |\n| 3 | 4 |"
    # a table that is the last thing, with and without a final newline
    assert table_extent("| a |\n| - |\n| 1 |", 0) == len("| a |\n| - |\n| 1 |")
    assert table_extent("| a |\n| - |\n| 1 |\n", 0) == len("| a |\n| - |\n| 1 |")
    # another block ends it
    both = "| a |\n| - |\n| 1 |\n# Heading\n"
    assert table_extent(both, 0) == len("| a |\n| - |\n| 1 |")


def test_table_extent_rejects_non_tables_and_bad_starts() -> None:
    assert table_extent("just text\nmore\n", 0) is None
    assert table_extent("| a |\n| - |\n| 1 |", 3) is None  # not a line start
    assert table_extent("| a |", 0) is None  # header only
    assert table_extent("x", 99) is None


def test_table_extent_follows_edits() -> None:
    """The browser's idea of the length goes stale after an edit; the start never does."""
    text = "x\n\n" + SIMPLE + "\n\ntail\n"
    start = 3
    first = apply_op(text[start : table_extent(text, start)], {"op": "insert_row", "at": 3})
    assert first is not None
    grown = text[:start] + first.text + text[table_extent(text, start) :]
    end = table_extent(grown, start)
    assert end is not None and grown[start:end] == first.text
    assert grown.endswith("\n\ntail\n")
