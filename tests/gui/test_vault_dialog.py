"""The "Open vault" dialog: recent vaults, browsing folders, cancel."""

from pathlib import Path

import pytest
from nicegui import ui
from nicegui.testing import User

from paper_pile.gui.components import vault_dialog

pytest_plugins = ["nicegui.testing.user_plugin"]
pytestmark = pytest.mark.nicegui_main_file(str(Path(__file__).with_name("nicegui_main.py")))


@pytest.fixture
def folders(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Path]:
    made = {n: tmp_path / n for n in ("current", "other", "plain")}
    for p in made.values():
        p.mkdir()
    (made["other"] / ".paper-pile").mkdir()  # opened as a vault before
    (made["plain"] / "inner").mkdir()
    monkeypatch.setattr(
        vault_dialog, "load_recent_vaults", lambda: [made["current"], made["other"]]
    )
    return made


async def open_dialog(user: User, current: Path) -> list[Path | None]:
    results: list[Path | None] = []

    async def ask() -> None:
        results.append(await vault_dialog.ask_vault(current, native=False))

    @ui.page("/")
    def page() -> None:
        ui.button("go", on_click=ask)

    await user.open("/")
    user.find("go").click()
    await user.should_see("Folders")
    await user.should_not_see("Browse")  # the system picker only exists in the native window
    return results


async def test_recent_vault_is_picked(user: User, folders: dict[str, Path]) -> None:
    results = await open_dialog(user, folders["current"])
    # the open vault is not offered again: the only recent one is "other"
    await user.should_see(marker="recent-0")
    await user.should_not_see(marker="recent-1")
    user.find(marker="recent-0").click()
    await user.should_not_see("Folders")
    assert results == [folders["other"]]


async def test_browse_into_a_folder_and_open_it(user: User, folders: dict[str, Path]) -> None:
    results = await open_dialog(user, folders["current"])
    await user.should_see("vault")  # badge on "other"
    user.find(marker="folder-2").click()  # current, other, plain
    await user.should_see('Open "plain"')
    await user.should_see("inner")
    user.find('Open "plain"').click()
    await user.should_not_see("Folders")
    assert results == [folders["plain"]]


async def test_typed_path_and_cancel(user: User, folders: dict[str, Path]) -> None:
    results = await open_dialog(user, folders["current"])
    user.find(marker="path").clear().type(str(folders["plain"] / "inner")).trigger("keydown.enter")
    await user.should_see('Open "inner"')
    await user.should_see("No folders inside")
    user.find(marker="path").clear().type(str(folders["plain"] / "missing")).trigger(
        "keydown.enter"
    )
    await user.should_see('Open "inner"')  # a missing folder is refused, the listing stays
    user.find("Cancel").click()
    await user.should_not_see("Folders")
    assert results == [None]
