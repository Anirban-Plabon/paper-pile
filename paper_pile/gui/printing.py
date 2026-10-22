"""Print pages (PLAN §4.17): a note rendered for paper, served at ``/_pp/print/<key>``.

The editor's page view loads one in a hidden frame after each pause in typing; PDF export prints
one (the native window through Qt, web mode through the browser's print dialog). Pages are kept
in memory, the newest few only, under random keys; in ``--serve`` mode the route sits behind the
token gate like everything else.
"""

import secrets
from collections import OrderedDict
from collections.abc import Callable

from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse

from paper_pile.core import embed
from paper_pile.core.config import Config
from paper_pile.core.printdoc import EmbedHtml, PrintAssets, PrintStyle, print_page
from paper_pile.core.settings import accent_colors, hex_to_rgb, sanitized
from paper_pile.core.vault import Vault
from paper_pile.gui.static_files import STATIC_URL, static_url

KEEP = 24  # page view asks again on every pause in typing: old pages are never needed long
_PAGES: OrderedDict[str, str] = OrderedDict()


def store(html: str) -> str:
    """Keep a print page; returns the URL it is served at."""
    key = secrets.token_urlsafe(12)
    _PAGES[key] = html
    while len(_PAGES) > KEEP:
        _PAGES.popitem(last=False)
    return f"/_pp/print/{key}"


def make_print_router() -> APIRouter:
    router = APIRouter()

    @router.get("/_pp/print/{key}")
    def page(key: str) -> HTMLResponse:
        html = _PAGES.get(key)
        if html is None:
            raise HTTPException(status_code=404, detail="not found")
        return HTMLResponse(html, headers={"Cache-Control": "no-store"})

    return router


def print_style(config: Config | None) -> PrintStyle:
    """The editor's fonts and the light accent, from the settings."""
    v = sanitized(config.values if config is not None else {})
    light, _dark = accent_colors(str(v["appearance.accent"]))
    r, g, b = (int(c) for c in hex_to_rgb(light).split(","))
    return PrintStyle(
        font_family=str(v["editor.font_family"]),
        code_font=str(v["editor.code_font_family"]),
        font_size=int(v["editor.font_size"]),
        line_height=float(v["editor.line_height"]),
        accent_rgb=(r, g, b),
    )


def paper_name(config: Config | None) -> str:
    return str(sanitized(config.values if config is not None else {})["print.paper"])


def _embedder(vault: Vault, note: str) -> Callable[[str, str], EmbedHtml]:
    def show(target: str, heading: str) -> EmbedHtml:
        shown = embed.embed(vault, note, target, heading)
        return EmbedHtml(shown.title, shown.html, shown.message)

    return show


def build_print_page(vault: Vault, config: Config | None, note: str, text: str, title: str) -> str:
    """The print page of ``note`` holding ``text`` (the live text, not necessarily saved)."""
    assets = PrintAssets(
        katex_css=f"{STATIC_URL}/vendor/katex/katex.min.css",
        print_css=static_url("print.css"),
        script=static_url("vendor/pp-editor/print.js"),
    )
    return print_page(
        text,
        note,
        title=title,
        paper_name=paper_name(config),
        style=print_style(config),
        assets=assets,
        embedder=_embedder(vault, note),
    )
