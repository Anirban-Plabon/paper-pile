"""Layout, routing, and startup."""

import logging
import os
from pathlib import Path

from nicegui import app, ui

from paper_pile.gui.security import TokenGate

log = logging.getLogger("paper_pile.app")

SERVE_HOST = "127.0.0.1"  # web mode never binds anything else


def _title(vault: Path) -> str:
    return f"paper-pile — {vault.name}"


def _build_pages(vault: Path) -> None:
    @ui.page("/")
    def index() -> None:
        ui.label(f"Vault: {vault}")  # placeholder until the 3-pane layout (P1.3)


def run_native(vault: Path) -> None:
    os.environ.setdefault("PYWEBVIEW_GUI", "qt")  # skip the noisy GTK probe
    _build_pages(vault)
    ui.run(native=True, reload=False, show=False, title=_title(vault), window_size=(1200, 800))


def run_serve(vault: Path, port: int, token: str) -> None:
    app.add_middleware(TokenGate, token=token)
    _build_pages(vault)
    ui.run(host=SERVE_HOST, port=port, reload=False, show=False, title=_title(vault))
