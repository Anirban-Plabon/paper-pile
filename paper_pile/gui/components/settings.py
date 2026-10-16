"""The settings pane (PLAN §4.12): a wide tab of the right pane, generated from
:data:`paper_pile.core.settings.SECTIONS`.

Left: a search box and the section list. Right: one row per setting (name and help on the left,
the control on the right). Every change is checked by ``core.settings`` and, if valid, applied
and saved at once — to the global ``config.toml`` or, with "This vault", to the vault's own
``vault.toml`` (which then wins). An invalid value only shows its message.
"""

import logging
from collections.abc import Callable
from typing import Any

from nicegui import ui

from paper_pile.core.config import Config, Scope
from paper_pile.core.settings import (
    ACCENTS,
    ALL,
    FONT_FAMILIES,
    SECTIONS,
    Setting,
    parse_value,
    sanitized,
    search_settings,
)

log = logging.getLogger("paper_pile.settings")

SECTION_ICONS = {  # Font Awesome (outline where the free set has one)
    "Appearance": "fa-regular fa-sun",
    "Editor": "fa-regular fa-pen-to-square",
    "Vault": "fa-regular fa-folder-open",
    "AI": "fa-regular fa-lightbulb",
    "Paste": "fa-regular fa-paste",
}
THEME_ICONS = {
    "system": "fa-solid fa-desktop",
    "light": "fa-regular fa-sun",
    "dark": "fa-regular fa-moon",
}
_SEGMENTED = {"appearance.density", "editor.default_mode", "editor.tab_size", "appearance.theme"}
_SCOPES = (("global", "All vaults"), ("vault", "This vault"))


class SettingsPane:
    def __init__(
        self,
        config: Config,
        on_applied: Callable[[set[str]], None],
        models: Callable[[], list[str]] = lambda: [],
        on_close: Callable[[], None] = lambda: None,
    ) -> None:
        self.config = config
        self._on_applied = on_applied
        self._models = models
        self._close = on_close
        self.scope: Scope = "global"
        self.page = next(iter(SECTIONS))
        self.query = ""
        self._nav: ui.column
        self._title: ui.label
        self._content: ui.column
        self._errors: dict[str, ui.label] = {}

    # ---- building --------------------------------------------------------------------------

    def open(self, host: ui.element) -> None:
        """Build the pane inside ``host`` (fresh every time it is opened)."""
        self.scope = "global"
        self.page = next(iter(SECTIONS))
        self.query = ""
        with host, ui.row().classes("pp-set no-wrap"):
            with ui.column().classes("pp-set-nav"):
                search = (
                    ui.input(placeholder="Search settings", on_change=self._searched)
                    .props("dense outlined clearable")
                    .classes("pp-set-search")
                )
                with search.add_slot("prepend"):
                    ui.icon("fa-solid fa-magnifying-glass").classes("pp-set-search-icon")
                ui.label("Settings").classes("pp-set-caption")
                self._nav = ui.column().classes("pp-set-navlist")
                ui.space()
                ui.button("Restore defaults", on_click=self._restore).props("flat no-caps dense")
            with ui.column().classes("pp-set-main"):
                with ui.row().classes("pp-set-top items-center no-wrap"):
                    self._title = ui.label("").classes("pp-set-title")
                    ui.space()
                    ui.label("Apply to").classes("pp-muted")
                    self._segmented(
                        [(key, label, None) for key, label in _SCOPES],
                        self.scope,
                        lambda value: setattr(self, "scope", value),
                    )
                    close = ui.icon("fa-solid fa-xmark").classes("pp-set-close")
                    close.on("click", lambda _e: self._close())
                    close.tooltip("Close")
                self._content = ui.column().classes("pp-set-content")
        self._render_nav()
        self._render_content()

    def _render_nav(self) -> None:
        self._nav.clear()
        with self._nav:
            for name in SECTIONS:
                on = name == self.page and not self.query
                item = ui.row().classes("pp-set-navitem items-center no-wrap")
                if on:
                    item.classes("pp-set-navitem-on")
                with item:
                    ui.icon(SECTION_ICONS.get(name, "fa-regular fa-circle")).classes(
                        "pp-set-navicon"
                    )
                    ui.label(name)
                item.on("click", lambda _e, n=name: self._go(n))

    def _go(self, name: str) -> None:
        self.page = name
        self.query = ""
        self._render_nav()
        self._render_content()

    def _searched(self, e: Any) -> None:
        self.query = (e.value or "").strip()
        self._render_nav()
        self._render_content()

    def _render_content(self) -> None:
        self._content.clear()
        self._errors = {}
        values = sanitized(self.config.values)
        with self._content:
            if self.query:
                self._title.set_text("Search results")
                found = search_settings(self.query)
                if not found:
                    ui.label("No settings match.").classes("pp-muted pp-set-none")
                for setting in found:
                    self._row(setting, values[setting.key])
                return
            self._title.set_text(self.page)
            for setting in SECTIONS[self.page]:
                self._row(setting, values[setting.key])

    # ---- one row ---------------------------------------------------------------------------

    def _row(self, setting: Setting, current: Any) -> None:
        with ui.row().classes("pp-set-row no-wrap items-center"):
            with ui.column().classes("pp-set-text"):
                ui.label(setting.label).classes("pp-set-label")
                if setting.help:
                    ui.label(setting.help).classes("pp-set-help")
                error = ui.label("").classes("pp-set-error")
                error.set_visibility(False)
                self._errors[setting.key] = error
            with ui.row().classes("pp-set-control items-center no-wrap"):
                self._control(setting, current)

    def _control(self, setting: Setting, current: Any) -> None:
        def commit(value: Any, s: Setting = setting) -> None:
            self._commit(s, value)

        if setting.kind == "bool":
            ui.switch(value=bool(current), on_change=lambda e: commit(e.value))
        elif setting.key == "appearance.accent":
            self._swatches(setting, str(current))
        elif setting.key in _SEGMENTED:
            icons = THEME_ICONS if setting.key == "appearance.theme" else {}
            self._segmented(
                [(c, c if not icons else "", icons.get(c)) for c in setting.choices],
                str(current),
                commit,
            )
        elif setting.kind == "choice":
            ui.select(
                list(setting.choices), value=str(current), on_change=lambda e: commit(e.value)
            ).props("dense outlined options-dense").classes("pp-set-field")
        elif setting.key == "editor.font_family":
            options = [*FONT_FAMILIES] if current in FONT_FAMILIES else [current, *FONT_FAMILIES]
            ui.select(
                options,
                value=current,
                with_input=True,
                new_value_mode="add-unique",
                on_change=lambda e: commit(e.value),
            ).props("dense outlined options-dense").classes("pp-set-field")
        elif setting.key == "ai.model":
            names = self._models()
            options = names if current in names or not current else [current, *names]
            ui.select(
                options,
                value=current or None,
                with_input=True,
                new_value_mode="add-unique",
                on_change=lambda e: commit(e.value),
            ).props("dense outlined options-dense").classes("pp-set-field")
        else:
            field = (
                ui.input(value=str(current), placeholder=setting.placeholder)
                .props("dense outlined")
                .classes("pp-set-field")
            )
            field.on_value_change(lambda e: self._check(setting, e.value))
            field.on("blur", lambda _e: commit(field.value))
            field.on("keydown.enter", lambda _e: commit(field.value))

    def _segmented(
        self,
        options: list[tuple[str, str, str | None]],
        value: str,
        on_pick: Callable[[str], None],
    ) -> None:
        """A row of options in a soft track; the chosen one is a raised pill."""
        items: dict[str, ui.element] = {}

        def pick(key: str) -> None:
            for name, el in items.items():
                if name == key:
                    el.classes("pp-seg-on")
                else:
                    el.classes(remove="pp-seg-on")
            on_pick(key)

        with ui.row().classes("pp-seg no-wrap"):
            for key, label, icon in options:
                item = ui.row().classes("pp-seg-item items-center no-wrap")
                if key == value:
                    item.classes("pp-seg-on")
                with item:
                    if icon:
                        ui.icon(icon).classes("pp-seg-icon")
                    if label:
                        ui.label(label)
                if icon and not label:
                    item.tooltip(key)
                item.on("click", lambda _e, k=key: pick(k))
                items[key] = item

    def _swatches(self, setting: Setting, current: str) -> None:
        buttons: dict[str, ui.button] = {}

        def pick(name: str) -> None:
            for key, button in buttons.items():
                if key == name:
                    button.classes("pp-swatch-on")
                else:
                    button.classes(remove="pp-swatch-on")
            self._commit(setting, name)

        with ui.row().classes("pp-swatches"):
            for name, (light, _dark) in ACCENTS.items():
                button = ui.button(on_click=lambda _e, n=name: pick(n))
                button.props("round flat dense").classes("pp-swatch").style(f"background:{light}")
                button.tooltip(name)
                if name == current:
                    button.classes("pp-swatch-on")
                buttons[name] = button

    # ---- validation and saving -------------------------------------------------------------

    def _check(self, setting: Setting, value: Any) -> bool:
        """Show the problem with ``value`` (if any) under its row."""
        parsed = parse_value(setting, value)
        label = self._errors.get(setting.key)
        if label is not None:
            label.set_text(parsed.error)
            label.set_visibility(not parsed.ok)
        return parsed.ok

    def _commit(self, setting: Setting, value: Any) -> None:
        """Apply and save ``value`` if it is valid and different from what is in force."""
        if not self._check(setting, value):
            return
        parsed = parse_value(setting, value)
        if parsed.value == sanitized(self.config.values)[setting.key]:
            return
        self.config.set(setting.key, parsed.value, self.scope)
        try:
            self.config.save(self.scope)
        except OSError:
            log.exception("could not save the settings")
            ui.notify("Could not save the settings.", type="negative")
            return
        self._on_applied({setting.key})

    def _restore(self) -> None:
        """Forget every value in the chosen layer (they fall back to the layer below)."""
        for key in ALL:
            self.config.unset(key, self.scope)
        self.config.save(self.scope)
        self._on_applied(set(ALL))
        where = "this vault" if self.scope == "vault" else "all vaults"
        ui.notify(f"Defaults restored for {where}", timeout=2000, position="bottom")
        self._render_content()
