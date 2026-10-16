"""Light / dark / system themes, accent colour, density and the editor font (PLAN §4.12).

The look is CSS variables (``static/app.css``) switched by ``static/theme.js``; this module turns
the configuration into what that script needs and reacts when it reports whether the result is
dark, so the editor and its diagrams can follow.
"""

import json
import logging
from collections.abc import Callable
from typing import Any

from nicegui import Client, ui

from paper_pile.core.config import Config
from paper_pile.core.settings import accent_colors, hex_to_rgb, sanitized

log = logging.getLogger("paper_pile.theme")


def theme_payload(config: Config | None) -> dict[str, Any]:
    """The settings the page needs to look right (every value validated; defaults otherwise)."""
    v = sanitized(config.values if config is not None else {})
    light, dark = accent_colors(str(v["appearance.accent"]))
    return {
        "theme": v["appearance.theme"],
        "accentLight": light,
        "accentDark": dark,
        "accentLightRgb": hex_to_rgb(light),
        "accentDarkRgb": hex_to_rgb(dark),
        "density": v["appearance.density"],
        "fontFamily": v["editor.font_family"],
        "fontSize": v["editor.font_size"],
        "lineHeight": v["editor.line_height"],
    }


def editor_options(config: Config | None) -> dict[str, Any]:
    """Word wrap, tab size and spell check for the editor."""
    v = sanitized(config.values if config is not None else {})
    return {
        "wordWrap": v["editor.word_wrap"],
        "tabSize": v["editor.tab_size"],
        "spellCheck": v["editor.spell_check"],
    }


class ThemeController:
    def __init__(self, config: Config, on_dark: Callable[[bool], None]) -> None:
        self.config = config
        self._on_dark = on_dark
        self.dark = False
        self._client: Client

    def install(self) -> None:
        """Call inside the page: the first look is in the page itself (no flash), the rest
        arrives as events."""
        self._client = ui.context.client
        initial = json.dumps(theme_payload(self.config))
        ui.add_head_html(f"<script>window.__pp_theme = {initial};</script>")
        ui.add_head_html('<script src="/pp-static/theme.js"></script>')
        ui.on("pp_theme_resolved", lambda e: self._resolved(bool(e.args.get("dark"))))

    def _resolved(self, dark: bool) -> None:
        self.dark = dark
        self._on_dark(dark)

    def apply(self) -> None:
        """The configuration changed: show it."""
        payload = json.dumps(theme_payload(self.config))
        self._client.run_javascript(f"window.ppTheme && window.ppTheme.apply({payload})")

    def toggle(self) -> None:
        """Quick light <-> dark switch (from what is on screen now); saved globally."""
        self.config.set("appearance.theme", "light" if self.dark else "dark", "global")
        self.config.save("global")
        self.apply()
