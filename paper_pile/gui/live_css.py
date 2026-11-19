"""Live CSS (user 2026-11-19, a development aid): with ``paper-pile --live-css`` an edit to one of
our stylesheets shows in the open window within half a second, without a restart or a reload.

Each page checks the files' mtimes (a ``stat`` each, no reading) twice a second and, when one
changed, swaps that ``<link>`` for one with the new ``?v=`` (the new sheet loads before the old
one goes, so nothing flashes unstyled). Off unless asked for: ``PAPER_PILE_LIVE_CSS=1``.
"""

import json
import logging
import os

from nicegui import ui

from paper_pile.gui.static_files import STATIC_DIR, static_url

log = logging.getLogger("paper_pile.live_css")

WATCHED = ("app.css", "print.css")
POLL_S = 0.5

_SWAP_JS = """
(() => {
  const name = %s, url = %s;
  document.querySelectorAll('link[rel="stylesheet"]').forEach((old) => {
    const path = new URL(old.href, location.href).pathname;
    if (!path.endsWith('/' + name)) return;
    const next = old.cloneNode();
    next.href = url;
    next.onload = () => old.remove();
    old.after(next);
  });
})();
"""


def enabled() -> bool:
    return os.environ.get("PAPER_PILE_LIVE_CSS") == "1"


def _mtimes() -> dict[str, float]:
    found: dict[str, float] = {}
    for name in WATCHED:
        try:
            found[name] = (STATIC_DIR / name).stat().st_mtime
        except OSError:
            continue
    return found


def install() -> None:
    """Call inside a page: re-load our stylesheets in this page when they change on disk."""
    seen = _mtimes()

    def check() -> None:
        for name, mtime in _mtimes().items():
            if seen.get(name) == mtime:
                continue
            seen[name] = mtime
            log.info("live CSS: %s changed, reloading it", name)
            ui.run_javascript(_SWAP_JS % (json.dumps(name), json.dumps(static_url(name))))

    ui.timer(POLL_S, check)
