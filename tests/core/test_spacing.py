from paper_pile.core.spacing import spaced_block


def put(template: str, body: str, *, blank_lines: bool = True) -> str:
    """``template`` has a ``|`` where the block goes."""
    at = template.index("|")
    text = template.replace("|", "")
    insert, _offset = spaced_block(text, at, at, body, blank_lines=blank_lines)
    return text[:at] + insert + text[at:]


def test_empty_lines_above_and_below() -> None:
    assert put("above\n|\nbelow", "![i](p.png)") == "above\n\n![i](p.png)\n\nbelow"
    assert put("above\n\n|\n\nbelow", "![i](p.png)") == "above\n\n![i](p.png)\n\nbelow"


def test_mid_line_text_moves_to_its_own_lines() -> None:
    assert put("before |after", "BLOCK") == "before \n\nBLOCK\n\nafter"
    assert put("before |after", "BLOCK", blank_lines=False) == "before \nBLOCK\nafter"


def test_top_and_end_of_note() -> None:
    assert put("|", "BLOCK") == "BLOCK\n"  # a line left below to go to
    assert put("|", "BLOCK", blank_lines=False) == "BLOCK\n"
    assert put("|\nnext", "BLOCK") == "BLOCK\n\nnext"


def test_quote_next_to_a_quote_continues_it() -> None:
    assert put("> one\n|\n> three", "> two") == "> one\n> two\n> three"


def test_offset_points_at_the_body() -> None:
    insert, offset = spaced_block("x ", 2, 2, "BODY")
    assert insert[offset:].startswith("BODY")


TABLE = "| a | b |\n| --- | --- |\n| 1 | 2 |"


def test_a_table_never_takes_the_next_text_line_as_a_row() -> None:
    # without the empty line "below" / "after" would be one more table row
    assert put("|\nbelow", TABLE, blank_lines=False) == f"{TABLE}\n\nbelow"
    assert put("before |after", TABLE, blank_lines=False) == f"before \n{TABLE}\n\nafter"
    assert put("|\nbelow", f"text\n\n{TABLE}", blank_lines=False) == f"text\n\n{TABLE}\n\nbelow"
