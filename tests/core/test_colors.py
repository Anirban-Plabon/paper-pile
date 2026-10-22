import pytest

from paper_pile.core.colors import lighten, parse_color


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("#F97316", "#f97316"),
        ("f97316", "#f97316"),
        ("#f73", "#ff7733"),
        ("#f97316cc", "#f97316"),
        ("rgb(249, 115, 22)", "#f97316"),
        ("rgb(249 115 22 / 50%)", "#f97316"),
        ("rgba(100%, 0%, 0%, .5)", "#ff0000"),
        ("hsl(0, 100%, 50%)", "#ff0000"),
        ("hsl(120deg 100% 25%)", "#008000"),
        ("  #ABC  ", "#aabbcc"),
    ],
)
def test_colour_codes_become_hex(text: str, expected: str) -> None:
    assert parse_color(text) == expected


@pytest.mark.parametrize(
    "text", ["", "orange-ish", "#12", "#ggg", "rgb(300, 0, 0)", "rgb(1, 2)", "hsl(0, 50, 50)"]
)
def test_non_colours_are_refused(text: str) -> None:
    assert parse_color(text) is None


def test_lighten_moves_towards_white() -> None:
    assert lighten("#000000", 0.5) == "#808080"
    assert lighten("#ffffff") == "#ffffff"
