"""The settings pane (PLAN §4.12): a tab of the right pane, generated from
:data:`paper_pile.core.settings.SECTIONS`.

Values are checked by ``core.settings`` as they are typed; Save stays disabled while anything is
invalid. They are written to the global ``config.toml`` or, with "This vault", to the vault's own
``vault.toml`` (which then wins over the global value).
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
    validate,
)

log = logging.getLogger("paper_pile.settings")

SECTION_ICONS = {  # Font Awesome (outline where the free set has one)
    "Appearance": "fa-regular fa-sun",
    "Editor": "fa-regular fa-pen-to-square",
    "Vault": "fa-regular fa-folder-open",
    "AI": "fa-regular fa-lightbulb",
    "Paste": "fa-regular fa-paste",
}
_TOGGLES = {"appearance.theme", "appearance.density", "editor.default_mode"}


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
        self.raw: dict[str, Any] = {}
        self.errors: dict[str, str] = {}
        self.scope: Scope = "global"
        self._error_labels: dict[str, ui.label] = {}
        self._save: ui.button
        self._summary: ui.label
        self._accent_buttons: dict[str, ui.button] = {}

    # ---- open / build ----------------------------------------------------------------------

    def open(self, host: ui.element) -> None:
        """Build the form inside ``host`` (a fresh copy of the current values every time)."""
        self.raw = dict(sanitized(self.config.values))
        self.raw["editor.tab_size"] = str(self.raw["editor.tab_size"])
        self.errors = {}
        self._error_labels = {}
        self._accent_buttons = {}
        self.scope = "global"
        with host, ui.column().classes("pp-settings"):
            with ui.row().classes("pp-settings-head items-center w-full no-wrap"):
                ui.label("Save for").classes("pp-muted")
                ui.toggle(
                    {"global": "All vaults", "vault": "This vault"},
                    value="global",
                    on_change=lambda e: setattr(self, "scope", e.value),
                ).props("dense no-caps size=sm")
            with ui.column().classes("pp-settings-scroll"):
                for name, settings in SECTIONS.items():
                    with ui.row().classes("pp-set-section items-center no-wrap"):
                        ui.icon(SECTION_ICONS.get(name, "fa-regular fa-circle")).classes(
                            "pp-set-section-icon"
                        )
                        ui.label(name).classes("pp-set-section-title")
                    for setting in settings:
                        self._field(setting)
            with ui.row().classes("items-center w-full no-wrap pp-settings-foot"):
                ui.button("Restore defaults", on_click=self._restore).props("flat no-caps size=sm")
                self._summary = ui.label("").classes("pp-muted")
                ui.space()
                ui.button("Close", on_click=self._close).props("flat no-caps size=sm")
                self._save = ui.button("Save", on_click=self._do_save).props("no-caps size=sm")

    def _field(self, setting: Setting) -> None:
        with ui.column().classes("pp-set-row"):
            ui.label(setting.label).classes("pp-set-label")
            current = self.raw[setting.key]
            if setting.kind == "bool":
                ui.switch(
                    value=bool(current), on_change=lambda e, s=setting: self._changed(s, e.value)
                )
            elif setting.key == "appearance.accent":
                self._accent_row(setting)
            elif setting.key in _TOGGLES:
                ui.toggle(
                    list(setting.choices),
                    value=str(current),
                    on_change=lambda e, s=setting: self._changed(s, e.value),
                ).props("dense no-caps size=sm")
            elif setting.kind == "choice":
                ui.select(
                    list(setting.choices),
                    value=str(current),
                    on_change=lambda e, s=setting: self._changed(s, e.value),
                ).props("dense outlined options-dense")
            elif setting.key == "editor.font_family":
                options = (
                    [*FONT_FAMILIES] if current in FONT_FAMILIES else [current, *FONT_FAMILIES]
                )
                ui.select(
                    options,
                    value=current,
                    with_input=True,
                    new_value_mode="add-unique",
                    on_change=lambda e, s=setting: self._changed(s, e.value),
                ).props("dense outlined options-dense").classes("w-full")
            elif setting.key == "ai.model":
                names = self._models()
                options = names if current in names or not current else [current, *names]
                ui.select(
                    options,
                    value=current or None,
                    with_input=True,
                    new_value_mode="add-unique",
                    on_change=lambda e, s=setting: self._changed(s, e.value),
                ).props("dense outlined options-dense").classes("w-full")
            else:
                ui.input(
                    value=str(current),
                    placeholder=setting.placeholder,
                    on_change=lambda e, s=setting: self._changed(s, e.value),
                ).props("dense outlined").classes("w-full")
            if setting.help:
                ui.label(setting.help).classes("pp-muted")
            error = ui.label("").classes("pp-set-error")
            error.set_visibility(False)
            self._error_labels[setting.key] = error

    def _accent_row(self, setting: Setting) -> None:
        with ui.row().classes("pp-swatches"):
            for name, (light, _dark) in ACCENTS.items():
                button = ui.button(on_click=lambda _e, n=name, s=setting: self._pick_accent(s, n))
                button.props("round flat dense").classes("pp-swatch").style(f"background:{light}")
                button.tooltip(name)
                self._accent_buttons[name] = button
        self._mark_accent()

    def _pick_accent(self, setting: Setting, name: str) -> None:
        self._changed(setting, name)
        self._mark_accent()

    def _mark_accent(self) -> None:
        for name, button in self._accent_buttons.items():
            if name == self.raw["appearance.accent"]:
                button.classes("pp-swatch-on")
            else:
                button.classes(remove="pp-swatch-on")

    # ---- validation and saving -------------------------------------------------------------

    def _changed(self, setting: Setting, value: Any) -> None:
        self.raw[setting.key] = value
        parsed = parse_value(setting, value)
        label = self._error_labels.get(setting.key)
        if parsed.ok:
            self.errors.pop(setting.key, None)
        else:
            self.errors[setting.key] = parsed.error
        if label is not None:
            label.set_text(parsed.error)
            label.set_visibility(not parsed.ok)
        self._save.set_enabled(not self.errors)
        self._summary.set_text(f"{len(self.errors)} to fix" if self.errors else "")

    def _do_save(self) -> None:
        clean, errors = validate(self.raw)
        if errors:
            return
        effective = sanitized(self.config.values)
        changed = {key for key, value in clean.items() if value != effective[key]}
        for key in changed:
            self.config.set(key, clean[key], self.scope)
        if changed:
            try:
                self.config.save(self.scope)
            except OSError:
                log.exception("could not save the settings")
                ui.notify("Could not save the settings.", type="negative")
                return
            self._on_applied(changed)
        ui.notify(
            "Settings saved" if changed else "Nothing changed", timeout=1500, position="bottom"
        )

    def _restore(self) -> None:
        """Forget every value in the chosen layer (they fall back to the layer below)."""
        for key in ALL:
            self.config.unset(key, self.scope)
        self.config.save(self.scope)
        self._on_applied(set(ALL))
        where = "this vault" if self.scope == "vault" else "all vaults"
        ui.notify(f"Defaults restored for {where}", timeout=2000, position="bottom")
        self._close()
