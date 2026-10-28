"""Light / dark / system themes, accent colour, density and the editor and code fonts (PLAN §4.12).

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
from paper_pile.core.printdoc import MARGIN_MM, paper, text_width_mm
from paper_pile.core.settings import (
    MOTION_FACTORS,
    accent_colors,
    get_nested,
    hex_to_rgb,
    sanitized,
)
from paper_pile.gui.static_files import static_url

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
        "icons": v["appearance.icons"],
        "motion": MOTION_FACTORS[str(v["appearance.motion"])],
        # untouched: the OS "reduce motion" wish counts as Off (PLAN §4.19)
        "motionSet": config is not None and _is_set(config, "appearance.motion"),
        "fontFamily": v["editor.font_family"],
        "codeFont": v["editor.code_font_family"],
        "fontSize": v["editor.font_size"],
        "lineHeight": v["editor.line_height"],
    }


def _is_set(config: Config, key: str) -> bool:
    return any(get_nested(config.layer(scope), key) is not None for scope in ("global", "vault"))


# settings that change the editor options below
EDITOR_OPTION_KEYS = frozenset(
    {
        "editor.word_wrap",
        "editor.line_numbers",
        "editor.readable_width",
        "editor.highlight_line",
        "editor.tab_size",
        "editor.spell_check",
        "general.language",
        "editor.page_view",
        "print.paper",
        "features.ai",  # the selection bar
    }
)


def editor_options(config: Config | None) -> dict[str, Any]:
    """Word wrap, line numbers, tab size, spell check and page view (PLAN §4.17) for the editor."""
    v = sanitized(config.values if config is not None else {})
    return {
        "wordWrap": v["editor.word_wrap"],
        "lineNumbers": v["editor.line_numbers"],
        "readableWidth": v["editor.readable_width"],
        "highlightLine": v["editor.highlight_line"],
        "tabSize": v["editor.tab_size"],
        "spellCheck": v["editor.spell_check"],
        "lang": v["general.language"],
        "pageView": v["editor.page_view"] != "off",
        "pageStyle": v["editor.page_view"],
        "paper": v["print.paper"],
        "textWidthMm": text_width_mm(str(v["print.paper"])),
        "paperHeightMm": paper(str(v["print.paper"])).height_mm,
        "marginMm": MARGIN_MM,
        "aiBar": v["features.ai"],  # Ask / Edit over a selection (PLAN §4.26)
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
        ui.add_head_html(f'<script src="{static_url("theme.js")}"></script>')
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
