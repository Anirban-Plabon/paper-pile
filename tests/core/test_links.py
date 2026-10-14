import pytest

from paper_pile.core.links import external_url


@pytest.mark.parametrize(
    ("href", "expected"),
    [
        ("https://example.org/a?b=1#c", "https://example.org/a?b=1#c"),
        ("http://example.org", "http://example.org"),
        ("HTTPS://Example.org", "HTTPS://Example.org"),
        ("mailto:ada@example.org", "mailto:ada@example.org"),
        ("www.example.org/x", "https://www.example.org/x"),
        ("  https://example.org  ", "https://example.org"),
    ],
)
def test_openable(href: str, expected: str) -> None:
    assert external_url(href) == expected


@pytest.mark.parametrize(
    "href",
    [
        "",
        "   ",
        "javascript:alert(1)",
        "JaVaScRiPt:alert(1)",
        "data:text/html,<script>alert(1)</script>",
        "file:///etc/passwd",
        "vbscript:x",
        "other-note.md",
        "../notes/a.md#heading",
        "/absolute/path",
        "#heading",
        "https://",
        "http:///nohost",
        "https://exa mple.org",
        "https://example.org/\nsecond-line",
        "ftp://example.org",
        "tel:+123",
    ],
)
def test_refused(href: str) -> None:
    assert external_url(href) is None
