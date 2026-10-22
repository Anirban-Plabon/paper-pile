"""The ⋯ note menu: every item reaches its action; Export downloads one file in web mode."""

import base64
from pathlib import Path
from typing import Any

import pytest
from nicegui import ui
from nicegui.testing import User

from paper_pile.core.vault import Vault
from paper_pile.gui.components import note_actions
from paper_pile.gui.components.note_menu import NoteActions, NoteMenu

pytest_plugins = ["nicegui.testing.user_plugin"]
pytestmark = pytest.mark.nicegui_main_file(str(Path(__file__).with_name("nicegui_main.py")))

LABELS = {
    "find": "Find…",
    "replace": "Replace…",
    "tidy": "Tidy note",
    "toggle_split": "Split right",
    "toggle_page_view": "Page view",
    "move": "Move to…",
    "merge": "Merge into…",
    "add_to_chat": "Add to chat",
    "summarize": "Summarize",
    "rewrite": "Rewrite",
    "write": "Write…",
    "copy_path": "Copy path",
    "copy_full_path": "Copy full path",
    "export_markdown": "Export as Markdown",
    "export_html": "Export as HTML",
    "export_pdf": "Export as PDF",
}


async def test_every_item_runs_its_action(user: User) -> None:
    called: list[str] = []
    menus: list[NoteMenu] = []

    @ui.page("/")
    def page() -> None:
        actions = NoteActions(**{k: (lambda k=k: called.append(k)) for k in LABELS})
        menu = NoteMenu(actions)
        menu.build()
        menu.update(has_note=True, split_open=False, page_view=False)
        menus.append(menu)

    await user.open("/")
    for key, label in LABELS.items():
        user.find(marker=label).click()
        assert called[-1] == key
    before = len(called)
    user.find(marker="Open in default app").click()  # shown, not implemented
    assert len(called) == before
    menus[0].update(has_note=True, split_open=True, page_view=False)
    await user.should_see("Close split")
    assert not menus[0]._page_view_check.visible
    menus[0].set_page_view(True)  # the check mark follows the setting
    assert menus[0]._page_view_check.visible


class StubPane:
    """What the export action needs from the editor pane."""

    def __init__(self, vault: Vault) -> None:
        self.vault = vault
        self.native = False
        self.host: Any = None
        self.config = None
        self.toasts: list[str] = []

    async def save_now(self) -> bool:
        return True

    def note_text(self, path: str) -> str:
        return self.vault.read_text(path)

    def toast(self, message: str, *, error: bool = False) -> None:
        self.toasts.append(message)


async def test_export_markdown_downloads_one_self_contained_file(
    user: User, tmp_path: Path
) -> None:
    png = b"\x89PNG\r\n\x1a\n" + b"\0" * 24
    (tmp_path / ".n.assets").mkdir()
    (tmp_path / ".n.assets" / "p.png").write_bytes(png)
    (tmp_path / "n.md").write_text("# N\n\n![p](.n.assets/p.png)\n")
    pane = StubPane(Vault(tmp_path))

    @ui.page("/")
    def page() -> None:
        pane.host = ui.element("div")

    await user.open("/")
    await note_actions._export(pane, "n.md", "md")  # type: ignore[arg-type]
    response = await user.download.next()
    text = response.text
    assert text.startswith("# N\n")
    assert "data:image/png;base64," + base64.b64encode(png).decode() in text
    assert pane.toasts == []


async def test_export_pdf_in_web_mode_prints_the_notes_print_page(
    user: User, tmp_path: Path
) -> None:
    from paper_pile.gui import printing

    (tmp_path / "n.md").write_text("---\ntitle: secret\n---\n# N\n\ntext\n")
    pane = StubPane(Vault(tmp_path))

    @ui.page("/")
    def page() -> None:
        pane.host = ui.element("div")

    await user.open("/")
    before = set(printing._PAGES)
    await note_actions._export_pdf(pane, "n.md")  # type: ignore[arg-type]
    new = [printing._PAGES[k] for k in printing._PAGES if k not in before]
    assert len(new) == 1
    assert '<h1 data-line="4">N</h1>' in new[0]
    assert "secret" not in new[0]  # front matter is not printed
    assert pane.toasts == ["Choose “Save as PDF” in the print dialog"]
