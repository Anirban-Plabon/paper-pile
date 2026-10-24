"""Layout, routing, and startup."""

import logging
import os
from pathlib import Path

from nicegui import app, background_tasks, ui

from paper_pile.gui import native_boot
from paper_pile.gui.files import make_asset_router
from paper_pile.gui.icons import icons_config_script, make_icon_router
from paper_pile.gui.layout import MainLayout
from paper_pile.gui.printing import make_print_router
from paper_pile.gui.security import TokenGate
from paper_pile.gui.shortcuts import install_shortcuts
from paper_pile.gui.static_files import STATIC_DIR, STATIC_URL, static_url
from paper_pile.gui.vault_host import VaultHost, window_title

log = logging.getLogger("paper_pile.app")

SERVE_HOST = "127.0.0.1"  # web mode never binds anything else


def _build_pages(host: VaultHost, *, native: bool) -> None:
    app.add_static_files(STATIC_URL, STATIC_DIR)
    app.include_router(make_asset_router(host.current))  # images shown inside notes
    app.include_router(make_icon_router())  # the line icons (one style app-wide)
    app.include_router(make_print_router())  # notes laid out on paper (page view, PDF)
    app.on_startup(host.start_watcher)
    app.on_shutdown(host.stop_watcher)

    @ui.page("/")
    def index() -> None:
        ui.add_head_html(f'<link rel="stylesheet" href="{STATIC_URL}/vendor/katex/katex.min.css">')
        ui.add_head_html(f'<link rel="stylesheet" href="{static_url("app.css")}">')
        ui.add_head_html(icons_config_script())
        ui.add_head_html(f'<script src="{static_url("icons.js")}"></script>')
        ui.add_head_html(f'<script src="{static_url("tips.js")}" defer></script>')
        ui.add_head_html(f'<script src="{static_url("menus.js")}" defer></script>')
        ui.add_head_html(f'<script src="{static_url("tree.js")}" defer></script>')
        ui.add_head_html(f'<script src="{static_url("tabs.js")}" defer></script>')
        ui.add_head_html(f'<script src="{static_url("split.js")}" defer></script>')
        ui.add_head_html(f'<script src="{static_url("notedrop.js")}" defer></script>')
        ui.add_head_html(f'<script src="{static_url("panes.js")}" defer></script>')
        ui.add_head_html(f'<script src="{static_url("chat.js")}" defer></script>')
        ui.add_head_html(f'<script src="{static_url("marks.js")}" defer></script>')
        if native:  # drag / resize of the frameless window
            ui.add_head_html(f'<script src="{static_url("window.js")}" defer></script>')
        # "reveal" only makes sense on this machine
        layout = MainLayout(host.vault, can_reveal=native, fs_bus=host.fs_bus, host=host)
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
                "ctrl+,": layout.open_settings,
                "ctrl+n": lambda: background_tasks.create(layout.new_note()),
                "ctrl+o": layout.open_note,
                "ctrl+p": layout.open_palette,
                "ctrl+shift+f": layout.search_vault,
                "ctrl+shift+o": layout.toggle_outline,
                "alt+shift+f": lambda: background_tasks.create(layout.tidy_note()),
            }
        )


def run_native(vault: Path) -> None:
    os.environ.setdefault("PYWEBVIEW_GUI", "qt")  # skip the noisy GTK probe
    _build_pages(VaultHost(vault), native=True)
    app.native.window_args["easy_drag"] = False  # we drag only from the top rows (window.js)
    app.native.start_args["func"] = native_boot.install  # compositor-driven move/resize
    ui.run(
        native=True,
        frameless=True,
        reload=False,
        show=False,
        title=window_title(vault),
        window_size=(1200, 800),
    )


def run_serve(vault: Path, port: int, token: str) -> None:
    app.add_middleware(TokenGate, token=token)
    _build_pages(VaultHost(vault), native=False)
    ui.run(host=SERVE_HOST, port=port, reload=False, show=False, title=window_title(vault))
