import pytest

from paper_pile.core.parser import front_matter
from paper_pile.core.titles import format_title, note_name, retitle_edit, with_title


def apply(text: str, edit) -> str:
    return text[: edit.start] + edit.insert + text[edit.end :]


def test_note_name() -> None:
    assert note_name("a/b/My note.md") == "My note"


def test_empty_note_gets_front_matter() -> None:
    assert with_title("", "Idea") == "---\ntitle: Idea\n---\n\n"


def test_note_without_front_matter_keeps_its_text() -> None:
    assert with_title("# Hi\nbody\n", "Idea") == "---\ntitle: Idea\n---\n# Hi\nbody\n"


def test_front_matter_without_title_gets_one() -> None:
    out = with_title("---\ntags: [a]\n---\nbody", "Idea")
    assert out == "---\ntitle: Idea\ntags: [a]\n---\nbody"
    fm = front_matter(out or "")
    assert fm and fm.data == {"title": "Idea", "tags": ["a"]}


@pytest.mark.parametrize(
    "text", ["---\ntitle: Mine\n---\nx", "---\ntitle:\n---\nx", "---\n: [\n---\nx"]
)
def test_existing_title_or_broken_front_matter_untouched(text: str) -> None:
    assert with_title(text, "Idea") is None


def test_crlf_is_kept() -> None:
    assert with_title("x\r\ny", "N") == "---\r\ntitle: N\r\n---\r\nx\r\ny"


@pytest.mark.parametrize(
    "name", ["Plan: v2", "#1", "yes", "123", 'say "hi"', "a'b", "- x", " pad", "ünï"]
)
def test_titles_round_trip_through_yaml(name: str) -> None:
    out = with_title("", name) or ""
    fm = front_matter(out)
    assert fm and fm.data["title"] == name


def test_format_plain_is_not_quoted() -> None:
    assert format_title("Meeting notes (2026)") == "Meeting notes (2026)"


def test_retitle_follows_rename_only_if_unchanged() -> None:
    text = "---\ntitle: Old\ntags: x\n---\nbody"
    edit = retitle_edit(text, "Old", "New name")
    assert edit and apply(text, edit) == "---\ntitle: New name\ntags: x\n---\nbody"
    assert retitle_edit("---\ntitle: Mine\n---\n", "Old", "New") is None
    assert retitle_edit("no front matter", "Old", "New") is None


def test_retitle_handles_quoted_value() -> None:
    text = '---\ntitle: "Plan: v2"\n---\n'
    edit = retitle_edit(text, "Plan: v2", "Plan v3")
    assert edit and apply(text, edit) == "---\ntitle: Plan v3\n---\n"
