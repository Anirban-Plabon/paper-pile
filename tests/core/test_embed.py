from pathlib import Path

import pytest

from paper_pile.core.embed import MAX_CHARS, embed, section
from paper_pile.core.vault import Vault

NOTE = "# Top\n\nintro\n\n## Part A\n\nA text\n\n### Deep\n\ndeep text\n\n## Part B\n\nB text\n"


@pytest.fixture
def vault(tmp_path: Path) -> Vault:
    v = Vault(tmp_path)
    v.create_note("src.md", "x")
    v.create_note(
        "Other.md", "---\ntitle: T\n---\n# Other\n\nhello **bold** <script>alert(1)</script>\n"
    )
    v.create_note("big.md", NOTE)
    v.create_folder("sub")
    v.create_note("sub/Pics.md", "![a](.Pics.assets/x.png) ![r](https://e.org/t.png)\n")
    return v


def test_section_cuts_from_a_heading_to_the_next_of_the_same_level() -> None:
    assert section(NOTE, "Part A") == "## Part A\n\nA text\n\n### Deep\n\ndeep text\n"
    assert section(NOTE, "part b") == "## Part B\n\nB text\n"
    assert section(NOTE, "Deep") == "### Deep\n\ndeep text\n"
    assert section(NOTE, "Top") == NOTE  # a top-level heading runs to the end
    assert section(NOTE, "Nope") is None


def test_embed_renders_the_note_safely(vault: Vault) -> None:
    e = embed(vault, "src.md", "Other")
    assert e.path == "Other.md" and e.title == "Other" and not e.message
    assert "<strong>bold</strong>" in e.html
    assert "<script>" not in e.html and "&lt;script&gt;" in e.html  # raw HTML is escaped
    assert "title: T" not in e.html  # front matter is not shown


def test_embed_of_a_heading_shows_only_that_section(vault: Vault) -> None:
    e = embed(vault, "src.md", "big", "Part B")
    assert e.title == "big › Part B" and "B text" in e.html and "A text" not in e.html


def test_missing_note_or_heading_say_so(vault: Vault) -> None:
    e = embed(vault, "src.md", "Ghost")
    assert e.path is None and "No note named" in e.message and e.html == ""
    e = embed(vault, "src.md", "big", "Ghost")
    assert e.path == "big.md" and "No heading" in e.message


def test_images_come_from_the_embedded_notes_folder_and_remote_ones_are_dropped(
    vault: Vault,
) -> None:
    e = embed(vault, "src.md", "Pics")
    assert "/_pp/asset?note=sub%2FPics.md&amp;path=.Pics.assets%2Fx.png" in e.html
    assert "https://e.org" not in e.html and "pp-image-chip" in e.html


def test_long_notes_are_cut(vault: Vault) -> None:
    vault.write_text("big.md", "word " * (MAX_CHARS // 3))
    e = embed(vault, "src.md", "big")
    assert "…" in e.html and len(e.html) < MAX_CHARS * 2
