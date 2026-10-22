"""Tree multi-select: Ctrl+click, Shift+click, the selection box, group move / delete."""

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
Page = tuple[Vault, list[tuple[str, object]]]


@pytest.fixture
def tree_page(tmp_path: Path) -> Page:
    root = tmp_path / "vault"
    (root / "box").mkdir(parents=True)
    for name in ("a", "b", "c", "d"):
        (root / f"{name}.md").write_text(name)
    vault: Vault = Vault(root)
    events: list[tuple[str, object]] = []

    @ui.page("/")
    def page() -> None:
        bus = EventBus()
        bus.subscribe("tree.open", lambda path: events.append(("open", path)))
        bus.subscribe("vault.renamed", lambda old, new: events.append(("renamed", (old, new))))
        bus.subscribe("vault.deleted", lambda path, trashed: events.append(("deleted", path)))
        tree = FileTree(vault, bus, can_reveal=False)
        tree.build()
        STATE["tree"] = tree

    return vault, events


async def _tree(user: User) -> FileTree:
    await user.open("/")
    return STATE["tree"]  # type: ignore[return-value]


def _shown(tree: FileTree) -> set[str]:
    return {p for p, row in tree._rows.items() if "pp-tree-selected" in row.classes}


async def test_ctrl_click_toggles_and_does_not_open(user: User, tree_page: Page) -> None:
    _vault, events = tree_page
    tree = await _tree(user)
    await tree._on_click({"path": "a.md", "isDir": False})
    await tree._on_click({"path": "c.md", "isDir": False, "toggle": True})
    await tree._on_click({"path": "box", "isDir": True, "toggle": True})
    assert _shown(tree) == {"a.md", "c.md", "box"}
    assert "box" not in tree._expanded
    await tree._on_click({"path": "a.md", "isDir": False, "toggle": True})
    assert _shown(tree) == {"c.md", "box"}
    assert events == [("open", "a.md")]
    await tree._on_click({"path": "d.md", "isDir": False})  # plain click: just this one
    assert _shown(tree) == {"d.md"}


async def test_shift_click_picks_a_range(user: User, tree_page: Page) -> None:
    tree = await _tree(user)
    await tree._on_click({"path": "a.md", "isDir": False})
    await tree._on_click({"path": "c.md", "isDir": False, "range": True})
    assert _shown(tree) == {"a.md", "b.md", "c.md"}
    await tree._on_click({"path": "box", "isDir": True, "range": True})  # anchor stays a.md
    assert _shown(tree) == {"box", "a.md"}


async def test_selection_box_selects_adds_and_clears(user: User, tree_page: Page) -> None:
    tree = await _tree(user)
    await tree._on_band({"paths": ["b.md", "c.md"], "add": False})
    assert _shown(tree) == {"b.md", "c.md"}
    await tree._on_band({"paths": ["a.md"], "add": True})
    assert _shown(tree) == {"a.md", "b.md", "c.md"}
    await tree._on_band({"paths": [], "add": False})  # click on blank space
    assert _shown(tree) == set()
    assert tree._target_folder() == ""


async def test_dragging_the_selection_moves_all_of_it(user: User, tree_page: Page) -> None:
    vault, events = tree_page
    tree = await _tree(user)
    await tree._on_band({"paths": ["a.md", "b.md", "box"], "add": False})
    await tree._on_move({"src": "a.md", "srcs": ["box", "a.md", "b.md"], "dst": "box"})
    assert (vault.root / "box" / "a.md").exists() and (vault.root / "box" / "b.md").exists()
    assert ("renamed", ("a.md", "box/a.md")) in events
    assert _shown(tree) == {"box", "box/a.md", "box/b.md"}


async def test_deleting_the_selection_trashes_each_item_once(user: User, tree_page: Page) -> None:
    import asyncio

    vault, events = tree_page
    tree = await _tree(user)
    tree._expanded.add("box")
    (vault.root / "box" / "in.md").write_text("x")
    tree.refresh()
    await tree._on_band({"paths": ["box", "box/in.md", "c.md"], "add": False})
    paths = tree._selection()
    assert paths == ["box", "c.md"]  # the note inside the selected folder goes with it
    task = asyncio.create_task(tree._delete(*paths))
    await user.should_see("Move 2 items to the trash?")
    user.find(kind=ui.button, content="Delete").click()
    await task
    assert not (vault.root / "box").exists() and not (vault.root / "c.md").exists()
    assert [e for e in events if e[0] == "deleted"] == [("deleted", "box"), ("deleted", "c.md")]
    assert _shown(tree) == set()
