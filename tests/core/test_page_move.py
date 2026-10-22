from paper_pile.core.page_move import move_page_break

NOTE = "# Title\n\nOne\n\nTwo\n\n---/\n\nThree\n\nFour\n"


def lines(text: str) -> list[str]:
    return text.split("\n")


def test_move_break_down() -> None:
    new = move_page_break(NOTE, 7, 11)  # above "Four"
    assert new == "# Title\n\nOne\n\nTwo\n\nThree\n\n---/\n\nFour\n"


def test_move_break_up() -> None:
    new = move_page_break(NOTE, 7, 3)  # above "One"
    assert new == "# Title\n\n---/\n\nOne\n\nTwo\n\nThree\n\nFour\n"


def test_move_to_where_it_is_does_nothing() -> None:
    assert move_page_break(NOTE, 7, 7) is None
    assert move_page_break(NOTE, 7, 9) is None  # the page already starts at "Three"


def test_add_break_splits_paragraph_with_blank_lines() -> None:
    new = move_page_break("a\nb\nc\n", None, 2)
    assert new == "a\n\n---/\n\nb\nc\n"


def test_keeps_how_the_break_was_written() -> None:
    div = '<div style="page-break-after: always;"></div>'
    note = f"One\n\n{div}\n\nTwo\n\nThree"
    assert move_page_break(note, 3, 7) == f"One\n\nTwo\n\n{div}\n\nThree"


def test_not_a_break_line_or_inside_code() -> None:
    assert move_page_break(NOTE, 3, 11) is None
    code = "One\n\n```\nx\ny\n```\n\nTwo"
    assert move_page_break(code, None, 5) is None
