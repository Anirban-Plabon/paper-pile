"""Layout, routing, and startup."""

import asyncio
import logging
import os
from pathlib import Path

from nicegui import app, ui

from paper_pile.core.events import EventBus
from paper_pile.core.vault import Vault
from paper_pile.core.watcher import VaultWatcher
from paper_pile.gui.files import make_asset_router
from paper_pile.gui.layout import MainLayout
from paper_pile.gui.security import TokenGate
from paper_pile.gui.shortcuts import install_shortcuts

log = logging.getLogger("paper_pile.app")

SERVE_HOST = "127.0.0.1"  # web mode never binds anything else
STATIC_DIR = Path(__file__).parent / "static"
STATIC_URL = "/pp-static"


def _title(vault: Path) -> str:
    return f"paper-pile — {vault.name}"


def _build_pages(vault: Path, *, native: bool) -> None:
    app.add_static_files(STATIC_URL, STATIC_DIR)
    app.include_router(make_asset_router(Vault(vault)))  # images shown inside notes
    fs_bus = EventBus()  # one watcher per process; every open page subscribes to this bus

    async def start_watcher() -> None:
        loop = asyncio.get_running_loop()
        # watchdog calls us from its own thread; hop onto the event loop before touching the UI
        watcher = VaultWatcher(vault, fs_bus, dispatch=lambda fn: loop.call_soon_threadsafe(fn))
        watcher.start()
        app.on_shutdown(watcher.stop)

    app.on_startup(start_watcher)

    @ui.page("/")
    def index() -> None:
        ui.add_head_html(f'<link rel="stylesheet" href="{STATIC_URL}/vendor/katex/katex.min.css">')
        ui.add_head_html(f'<link rel="stylesheet" href="{STATIC_URL}/app.css">')
        ui.add_head_html(f'<script src="{STATIC_URL}/tree.js" defer></script>')
        ui.add_head_html(f'<script src="{STATIC_URL}/tabs.js" defer></script>')
        ui.add_head_html(f'<script src="{STATIC_URL}/chat.js" defer></script>')
        # "reveal" only makes sense on this machine
        layout = MainLayout(vault, can_reveal=native, fs_bus=fs_bus)
        layout.build()
        install_shortcuts(
            {
                "ctrl+e": layout.toggle_mode,
                "ctrl+b": lambda: layout.toggle("left"),
                "ctrl+l": lambda: layout.toggle("right"),
                # Ctrl+W / Ctrl+Tab work in the native window; web browsers reserve them, so
                # the Alt combos are the ones that work everywhere
                "ctrl+w": layout.close_tab,
                "alt+w": layout.close_tab,
                "ctrl+tab": lambda: layout.cycle_tabs(1),
                "ctrl+shift+tab": lambda: layout.cycle_tabs(-1),
                "alt+pagedown": lambda: layout.cycle_tabs(1),
                "alt+pageup": lambda: layout.cycle_tabs(-1),
            }
        )


def run_native(vault: Path) -> None:
    os.environ.setdefault("PYWEBVIEW_GUI", "qt")  # skip the noisy GTK probe
    _build_pages(vault, native=True)
    ui.run(native=True, reload=False, show=False, title=_title(vault), window_size=(1200, 800))


def run_serve(vault: Path, port: int, token: str) -> None:
    app.add_middleware(TokenGate, token=token)
    _build_pages(vault, native=False)
    ui.run(host=SERVE_HOST, port=port, reload=False, show=False, title=_title(vault))
