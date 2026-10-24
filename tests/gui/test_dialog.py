"""Dialog: a deleted dialog leaves nothing behind (NiceGUI's canary element, P20)."""

import gc
import weakref
from pathlib import Path

import pytest
from nicegui import ui
from nicegui.testing import User

from paper_pile.gui.dialog import Dialog

pytest_plugins = ["nicegui.testing.user_plugin"]
pytestmark = pytest.mark.nicegui_main_file(str(Path(__file__).with_name("nicegui_main.py")))


async def test_deleted_dialogs_leave_no_element_and_are_freed(user: User) -> None:
    host: list[ui.element] = []
    gone: list[weakref.ref[Dialog]] = []

    async def ask() -> None:
        with host[0], Dialog() as dialog, ui.card():
            ui.label("Question?")
            ui.button("Answer", on_click=lambda: dialog.submit("yes"))
        gone.append(weakref.ref(dialog))
        await dialog
        dialog.delete()

    @ui.page("/")
    def page() -> None:
        host.append(ui.element("div"))
        ui.button("go", on_click=ask)

    await user.open("/")
    for _ in range(3):
        user.find("go").click()
        await user.should_see("Question?")
        user.find("Answer").click()
        await user.should_not_see("Question?")
    assert list(host[0]) == []  # no hidden canary per dialog
    gc.collect()
    assert [ref() for ref in gone] == [None, None, None]  # nothing keeps them alive
