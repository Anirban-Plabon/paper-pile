"""The Files header: new note (no prompt), new folder (dialog), search (recent notes)."""

from pathlib import Path

import pytest
from nicegui import ui
from nicegui.testing import User

from paper_pile.core.events import EventBus
from paper_pile.core.vault import Vault
from paper_pile.gui.components.tree import FileTree

pytest_plugins = ["nicegui.testing.user_plugin"]
pytestmark = pytest.mark.nicegui_main_file(str(Path(__file__).with_name("nicegui_main.py")))

STATE: dict[str, object] = {}


@pytest.fixture
def tree_page(tmp_path: Path) -> tuple[Vault, list[str]]:
    root = tmp_path / "vault"
    (root / "sub").mkdir(parents=True)
    (root / "a.md").write_text("a")
    vault, opened = Vault(root), []

    @ui.page("/")
    def page() -> None:
        bus = EventBus()
        bus.subscribe("tree.open", lambda path: opened.append(path))
        tree = FileTree(vault, bus, can_reveal=False)
        tree.build()
        STATE["tree"] = tree

    return vault, opened


async def test_new_note_is_created_without_asking(
    user: User, tree_page: tuple[Vault, list[str]]
) -> None:
    vault, opened = tree_page
    await user.open("/")
    tree: FileTree = STATE["tree"]  # type: ignore[assignment]
    await tree._new_note()
    await tree._new_note()
    assert opened == ["Untitled 1.md", "Untitled 2.md"]
    assert (vault.root / "Untitled 2.md").exists()


async def test_new_note_goes_into_the_selected_folder(
    user: User, tree_page: tuple[Vault, list[str]]
) -> None:
    vault, opened = tree_page
    await user.open("/")
    tree: FileTree = STATE["tree"]  # type: ignore[assignment]
    tree._select("sub")
    await tree._new_note()
    tree._select("a.md")
    await tree._new_note()
    assert opened == ["sub/Untitled 1.md", "Untitled 1.md"]


async def test_search_lists_recent_notes_and_a_click_opens_one(
    user: User, tree_page: tuple[Vault, list[str]]
) -> None:
    vault, opened = tree_page
    await user.open("/")
    tree: FileTree = STATE["tree"]  # type: ignore[assignment]
    tree.toggle_search()
    assert set(tree._rows) == {"a.md"}  # folders are not listed in search mode
    await tree._on_click({"path": "a.md", "isDir": False})
    assert opened == ["a.md"]
    tree.toggle_search()
    assert set(tree._rows) == {"sub", "a.md"}


async def test_new_folder_asks_for_name_and_location(
    user: User, tree_page: tuple[Vault, list[str]]
) -> None:
    import asyncio

    vault, _opened = tree_page
    await user.open("/")
    tree: FileTree = STATE["tree"]  # type: ignore[assignment]
    task = asyncio.create_task(tree._guard(tree._new_folder()))
    await user.should_see("Create")
    user.find(kind=ui.button, content="Create").click()  # no name yet: refused, dialog stays
    await asyncio.sleep(0.1)
    assert not task.done()
    user.find(kind=ui.input, content="Name").type("Ideas")
    user.find(kind=ui.button, content="Create").click()
    await task
    assert (vault.root / "Ideas").is_dir()  # location not chosen: the vault itself


async def test_search_box_lists_full_text_hits_and_a_click_finds_the_word(
    user: User, tmp_path: Path
) -> None:
    from paper_pile.core.index import SearchHit

    root = tmp_path / "v"
    root.mkdir()
    (root / "a.md").write_text("x")
    found: list[tuple[str, str]] = []

    async def open_found(path: str, term: str) -> None:
        found.append((path, term))

    @ui.page("/")
    def page() -> None:
        tree = FileTree(
            Vault(root),
            EventBus(),
            can_reveal=False,
            search=lambda q: [SearchHit("d/b.md", "b", "a \x02banana\x03 <i>pie</i>")],
            open_found=open_found,
        )
        tree.build()
        STATE["tree"] = tree

    await user.open("/")
    tree: FileTree = STATE["tree"]  # type: ignore[assignment]
    tree.toggle_search()
    tree._set_filter("bana")
    assert list(tree._rows) == ["d/b.md"]
    row = tree._rows["d/b.md"]
    assert row._props["data-find"] == "banana"
    snippet = next(e for e in row.descendants() if isinstance(e, ui.html))
    assert snippet.content == "a <mark>banana</mark> &lt;i&gt;pie&lt;/i&gt;"  # escaped, not markup
    await tree._on_click({"path": "d/b.md", "isDir": False, "find": "banana"})
    assert found == [("d/b.md", "banana")]
