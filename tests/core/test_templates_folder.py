from pathlib import Path

import pytest

from paper_pile.core.templates import (
    import_template,
    list_templates,
    new_template,
    template_draft_messages,
)
from paper_pile.core.vault import ExistsError, Vault


def _vault(tmp_path: Path) -> Vault:
    (tmp_path / ".template" / "work").mkdir(parents=True)
    (tmp_path / ".template" / "Meeting.md").write_text("# {{title}}")
    (tmp_path / ".template" / "work" / "Standup.md").write_text("- yesterday")
    (tmp_path / "note.md").write_text("# Note")
    return Vault(tmp_path)


def test_list_templates(tmp_path: Path) -> None:
    vault = _vault(tmp_path)
    found = list_templates(vault, ".template")
    assert found == [".template/Meeting.md", ".template/work/Standup.md"]
    assert list_templates(vault, "") == [] and list_templates(vault, "missing") == []


def test_new_template(tmp_path: Path) -> None:
    vault = _vault(tmp_path)
    made = new_template(vault, ".template/", "Book review", "# {{title}}")
    assert made == ".template/Book review.md"
    with pytest.raises(ExistsError):
        new_template(vault, ".template", "Meeting", "again")
    with pytest.raises(ValueError):
        new_template(vault, "", "x", "")


def test_import_template_takes_a_free_name(tmp_path: Path) -> None:
    vault = _vault(tmp_path)
    assert import_template(vault, ".template", tmp_path / "note.md") == ".template/note.md"
    meeting = tmp_path.parent / f"{tmp_path.name}-out" / "Meeting.md"  # a file outside the vault
    meeting.parent.mkdir()
    meeting.write_text("another meeting")
    assert import_template(vault, ".template", meeting) == ".template/Meeting 1.md"
    assert vault.read_text(".template/Meeting 1.md") == "another meeting"
    assert vault.read_text(".template/Meeting.md") == "# {{title}}"  # never overwritten


def test_template_draft_messages() -> None:
    system, user = template_draft_messages(" a book review ", "Bengali")
    assert "{{title}}" in system.content and "Bengali" in system.content
    assert user.content == "A template for: a book review"
