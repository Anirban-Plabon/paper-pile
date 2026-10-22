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


async def test_keyboard_moves_extends_folds_and_selects_all(user: User, tree_page: Page) -> None:
    vault, events = tree_page
    (vault.root / "box" / "in.md").write_text("x")
    tree = await _tree(user)
    order = list(tree._rows)  # box, a.md, b.md, c.md, d.md
    assert order[:2] == ["box", "a.md"]
    await tree._on_key({"key": "ArrowDown"})  # no cursor yet: the first row
    assert _shown(tree) == {"box"}
    await tree._on_key({"key": "ArrowRight"})  # unfold
    assert "box" in tree._expanded and "box/in.md" in tree._rows
    await tree._on_key({"key": "ArrowRight"})  # step in
    assert _shown(tree) == {"box/in.md"}
    await tree._on_key({"key": "ArrowLeft"})  # out to the folder
    assert _shown(tree) == {"box"}
    await tree._on_key({"key": "ArrowLeft"})  # fold
    assert "box" not in tree._expanded
    await tree._on_key({"key": "ArrowDown"})
    await tree._on_key({"key": "ArrowDown", "shift": True})
    await tree._on_key({"key": "ArrowDown", "shift": True})
    assert _shown(tree) == {"a.md", "b.md", "c.md"}
    await tree._on_key({"key": "ArrowUp", "shift": True})
    assert _shown(tree) == {"a.md", "b.md"}
    await tree._on_key({"key": "Enter"})  # opens the cursor row
    assert events[-1] == ("open", "b.md")
    await tree._on_key({"key": "a", "ctrl": True})
    assert _shown(tree) == set(tree._rows)
    await tree._on_key({"key": "Escape"})
    assert _shown(tree) == set()
    await tree._on_key({"key": "End"})
    assert _shown(tree) == {"d.md"}


async def test_delete_key_trashes_the_selection(user: User, tree_page: Page) -> None:
    import asyncio

    vault, _events = tree_page
    tree = await _tree(user)
    await tree._on_band({"paths": ["a.md", "b.md"], "add": False})
    task = asyncio.create_task(tree._on_key({"key": "Delete"}))
    await user.should_see("Move 2 items to the trash?")
    user.find(kind=ui.button, content="Delete").click()
    await task
    assert not (vault.root / "a.md").exists() and not (vault.root / "b.md").exists()
