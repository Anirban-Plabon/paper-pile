"""The app's writer for edits across notes (P30.31): through the editor pane — version kept,
the open tab updated, never over a changed note."""

from pathlib import Path

from paper_pile.core.vault import Vault
from paper_pile.gui.vault_writer import EditorWriter


class Pane:
    def __init__(self, vault: Vault) -> None:
        self.vault = vault
        self.index = None
        self.texts = {"a.md": "old\n"}
        self.versions: list[tuple[str, str, str]] = []

    def note_text(self, path: str) -> str:
        return self.texts[path]

    def keep_version(self, path: str, text: str, reason: str) -> None:
        self.versions.append((path, text, reason))

    def replace_note(self, path: str, text: str) -> None:
        self.texts[path] = text


def test_editor_writer(tmp_path: Path) -> None:
    pane = Pane(Vault(tmp_path))
    writer = EditorWriter(pane)  # type: ignore[arg-type]
    assert writer.read("a.md") == "old\n"
    assert writer.write("a.md", "old\n", "new\n", "why")
    assert pane.texts["a.md"] == "new\n" and pane.versions == [("a.md", "old\n", "why")]
    assert not writer.write("a.md", "old\n", "again\n", "why")  # changed since: not written
    assert pane.texts["a.md"] == "new\n"
    assert writer.create("Notes/Overview.md", "# O\n") == "Notes/Overview.md"
    assert writer.create("Notes/Overview.md", "# O2\n") == "Notes/Overview 1.md"
