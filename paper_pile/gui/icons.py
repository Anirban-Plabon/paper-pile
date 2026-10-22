"""One icon style for the whole app: Lucide line icons (ISC licence), vendored, no CDN.

Every icon is drawn the same way: a 24×24 outline in the current text colour with one stroke
width (set in ``app.css`` on ``.q-icon > use``). Sizes come from three classes only:
``pp-i-s`` (14 px: chevrons, close crosses), ``pp-i-m`` (16 px: rows, menus, tabs) and
``pp-i-l`` (18 px: toolbar buttons).

Icons are Quasar ``svguse:`` names pointing at ``/_pp/icon/<name>.svg``, served from
``static/vendor/lucide/icons.json`` (built by ``tools/editor_src/build_icons.mjs``). So the same
string works in ``ui.icon(...)``, in a button's ``icon=`` and in the editor's JS.
"""

import json
from collections.abc import Callable
from functools import cache
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from nicegui import ui

from paper_pile.gui.tips import tip

ICONS_FILE = Path(__file__).parent / "static" / "vendor" / "lucide" / "icons.json"
ICON_ROUTE = "/_pp/icon"
Size = Literal["s", "m", "l"]


@cache
def _data() -> tuple[str, dict[str, str]]:
    raw = json.loads(ICONS_FILE.read_text(encoding="utf-8"))
    return str(raw["version"]), dict(raw["icons"])


def has_icon(name: str) -> bool:
    return name in _data()[1]


def icon_url(name: str) -> str:
    """The URL of one icon's sprite (``#i`` is its symbol); unknown names fail loudly."""
    version, icons = _data()
    if name not in icons:
        raise KeyError(f"unknown icon: {name!r}")
    return f"{ICON_ROUTE}/{name}.svg?v={version}"


def ico(name: str) -> str:
    """The Quasar icon name for a Lucide icon (for ``ui.icon`` and ``icon=`` props)."""
    return f"svguse:{icon_url(name)}#i"


def line_icon(name: str, size: Size = "m") -> ui.icon:
    return ui.icon(ico(name)).classes(f"pp-i pp-i-{size}")


def set_icon(element: ui.element, name: str, *, prop: str = "icon") -> None:
    """Swap the icon of a button (``icon``) or of a ``ui.icon`` (``prop="name"``)."""
    element.props(f'{prop}="{ico(name)}"')


def icon_button(
    name: str, on_click: Callable[[], object], tooltip: str, size: Size = "l"
) -> ui.button:
    """A flat icon button with a hover name (color=None: our CSS sets the colour)."""
    button = ui.button(icon=ico(name), on_click=on_click, color=None)
    button.props("flat dense").classes(f"pp-icon-btn pp-i-{size}")  # rounded rectangle, not round
    return tip(button, tooltip)


def icons_config_script() -> str:
    """Tells ``static/icons.js`` where the icons are (it builds the same URLs as ``icon_url``)."""
    config = json.dumps({"base": ICON_ROUTE, "v": _data()[0]})
    return f"<script>window.__pp_icons = {config};</script>"


def make_icon_router() -> APIRouter:
    router = APIRouter()

    @router.get(ICON_ROUTE + "/{name}.svg")
    def icon(name: str) -> Response:
        markup = _data()[1].get(name)
        if markup is None:
            raise HTTPException(status_code=404, detail="no such icon")
        body = (
            '<svg xmlns="http://www.w3.org/2000/svg">'
            f'<symbol id="i" viewBox="0 0 24 24">{markup}</symbol></svg>'
        )
        headers = {"Cache-Control": "public, max-age=31536000, immutable"}
        return Response(body, media_type="image/svg+xml", headers=headers)

    return router
