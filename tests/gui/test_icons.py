"""One icon set: every icon the app names must exist in the vendored Lucide set."""

import re
from pathlib import Path

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

from paper_pile.core.commands import REGISTRY
from paper_pile.gui.components import right_pane, settings
from paper_pile.gui.icons import has_icon, ico, make_icon_router

GUI = Path(__file__).parents[2] / "paper_pile" / "gui"
CALL = re.compile(  # calls whose first argument is the icon name
    r'(?:line_icon|ico|icon_button|_ref_chip)\(\s*"([a-z0-9-]+)"|set_icon\([^,]+,\s*"([a-z0-9-]+)"'
)
ITEM_LABEL = re.compile(r'_item\(\s*"[^"]*",\s*"([a-z0-9-]+)"')


def _names_in_source() -> set[str]:
    names: set[str] = set()
    for path in GUI.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        for m in CALL.finditer(text):
            names.add(m.group(1) or m.group(2))
        names.update(ITEM_LABEL.findall(text))
    return names


def test_every_icon_named_in_the_gui_exists() -> None:
    names = _names_in_source()
    names |= set(settings.SECTION_ICONS.values()) | set(settings.THEME_ICONS.values())
    names |= {right_pane.CHAT_ICON, right_pane.CALENDAR_ICON, right_pane.SETTINGS_ICON}
    assert len(names) > 20  # the scan really found the call sites
    assert sorted(n for n in names if not has_icon(n)) == []


def test_every_slash_command_icon_exists() -> None:
    import paper_pile.core.commands_builtin  # noqa: F401  (registers the commands)

    icons = {c.icon for c in REGISTRY.all() if c.icon}
    assert icons and sorted(i for i in icons if not has_icon(i)) == []


def test_unknown_icons_fail_loudly() -> None:
    with pytest.raises(KeyError):
        ico("no-such-icon")


def test_icon_route_serves_a_symbol_and_404s_unknown_names() -> None:
    app = FastAPI()
    app.include_router(make_icon_router())
    client = TestClient(app)
    ok = client.get("/_pp/icon/search.svg")
    assert ok.status_code == 200 and ok.headers["content-type"].startswith("image/svg+xml")
    assert '<symbol id="i" viewBox="0 0 24 24">' in ok.text and "<circle" in ok.text
    assert client.get("/_pp/icon/nope.svg").status_code == 404
