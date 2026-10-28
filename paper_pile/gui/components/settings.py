"""The settings pane (PLAN §4.12): a wide tab of the right pane, generated from
:data:`paper_pile.core.settings.SECTIONS`.

Left: a search box and the section list. Right: one row per setting (name and help on the left,
the control on the right). Every change is checked by ``core.settings`` and, if valid, applied
and saved at once — to the global ``config.toml`` or, with "This vault", to the vault's own
``vault.toml`` (which then wins). An invalid value only shows its message.

What is listed follows the feature switches and *Minimal settings* (``core.settings.is_shown``,
PLAN §4.18): minimal shows only the essential rows and none of the hand-made panels.

The AI page has three hand-made parts: the system instruction (typed in a large box with an
drag handle at its corner and *Write with AI*, or read from a ``.md`` file), the memories browser
(:mod:`memories`) under the Memories settings, and the Advanced settings folded at the end.
"""

import contextlib
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from pathlib import Path
from typing import Any

from nicegui import ui

from paper_pile import __version__
from paper_pile.core.ai.install import ai_available, ai_unavailable
from paper_pile.core.ai.instructions import MAX_TEXT_CHARS
from paper_pile.core.colors import parse_color
from paper_pile.core.config import Config, Scope
from paper_pile.core.settings import (
    ACCENTS,
    ALL,
    CODE_FONTS,
    FONTS,
    ICON_COLORS,
    LANGUAGES,
    MOTION_LABELS,
    PAGE_VIEWS,
    SECTIONS,
    SELECTION_TO_CHAT,
    Setting,
    accent_colors,
    is_shown,
    parse_value,
    sanitized,
    search_settings,
    shown_sections,
    stepped,
)
from paper_pile.core.templates import import_template, list_templates, new_template
from paper_pile.core.vault import ExistsError, Vault, VaultError
from paper_pile.core.vault_folders import (
    BY_KEY,
    can_clear,
    clear_folder,
    daily_templates_folder,
    files_in,
    folder_path,
)
from paper_pile.gui.components.ai_access import AccessPanel
from paper_pile.gui.components.memories import MemoriesPanel
from paper_pile.gui.dialog import Dialog
from paper_pile.gui.icons import close_button, ico, line_icon
from paper_pile.gui.tips import tip

log = logging.getLogger("paper_pile.settings")

SECTION_ICONS = {
    "General": "compass",  # Font Awesome (outline where the free set has one)
    "Appearance": "sun",
    "Editor": "square-pen",
    "Vault": "folder-open",
    "AI": "lightbulb",
    "Paste": "clipboard-paste",
}
_RELAYOUT = {"features.ai", "features.calendar", "settings.minimal"}  # change what is listed
THEME_ICONS = {
    "system": "monitor",
    "light": "sun",
    "dark": "moon",
}
_SEGMENTED = {
    "appearance.density",
    "appearance.motion",
    "appearance.icons",
    "editor.default_mode",
    "editor.tab_size",
    "appearance.theme",
    "print.paper",
    "editor.page_view",
    "ai.selection_to_chat",
}
_SCOPES = (("global", "All vaults"), ("vault", "This vault"))
_FOLDED = {("AI", "Advanced")}  # (section, group) shown in a closed expansion
_DRAWN_ELSEWHERE = {  # settings drawn inside another one's control
    "ai.instructions_from": "ai.instructions",
    "ai.instructions_file": "ai.instructions",
}
_INSTRUCTION_FROM = (("text", "Write", "square-pen"), ("file", "From a file", "file-text"))


class SettingsPane:
    def __init__(
        self,
        config: Config,
        on_applied: Callable[[set[str]], None],
        models: Callable[[], list[str]] = lambda: [],
        on_close: Callable[[], None] = lambda: None,
        vault_root: Path | None = None,
        folders: Callable[[], list[str]] = lambda: [],
        notes: Callable[[], list[str]] = lambda: [],
        memories: MemoriesPanel | None = None,
        access: AccessPanel | None = None,
        draft: Callable[[str, str], AsyncIterator[str]] | None = None,  # (kind, brief)
        native: bool = False,
        gallery: Callable[[], None] | None = None,
        on_cleared: Callable[[str], None] = lambda key: None,
        open_vault: Callable[[], Any] | None = None,
        rebuild_index: Callable[[], Awaitable[int]] | None = None,
    ) -> None:
        self._rebuild_index = rebuild_index  # General → Advanced
        self.config = config
        self._on_applied = on_applied
        self._models = models
        self._close = on_close
        self._vault_root = vault_root
        self._open_vault = open_vault  # the Vault row's Change… button
        self._folders = folders
        self._notes = notes
        self._memories = memories
        self._access = access
        self._draft = draft
        self._gallery = gallery
        self._on_cleared = on_cleared
        self._native = native
        self._open_groups: set[str] = set()  # folded groups the user opened
        self._tpl_mode = "text"  # General → Templates: "text" (write) or "file" (add one)
        self._tpl_current: str | None = None  # the template being edited (None: a new one)
        self.scope: Scope = "global"
        self.page = next(iter(SECTIONS))
        self.query = ""
        self._nav: ui.column
        self._title: ui.label
        self._content: ui.column
        self._mode: ui.element
        self._errors: dict[str, ui.label] = {}

    # ---- building --------------------------------------------------------------------------

    def open(self, host: ui.element, page: str | None = None) -> None:
        """Build the pane inside ``host`` (fresh every time it is opened), on ``page`` if given."""
        self.scope = "global"
        self.page = page if page in SECTIONS else next(iter(SECTIONS))
        self.query = ""
        self._keep_page_shown()
        with host, ui.row().classes("pp-set no-wrap"):
            with ui.column().classes("pp-set-nav"):
                search = (
                    ui.input(placeholder="Search settings", on_change=self._searched)
                    .props("dense outlined clearable")
                    .classes("pp-set-search")
                )
                with search.add_slot("prepend"):
                    line_icon("search").classes("pp-set-search-icon")
                ui.label("Settings").classes("pp-set-caption")
                self._nav = ui.column().classes("pp-set-navlist")
                ui.space()
                self._mode = ui.element("div").classes("pp-set-mode")
                self._render_mode()
                ui.button(
                    "Restore defaults", icon=ico("rotate-ccw"), on_click=self._restore, color=None
                ).props("flat no-caps dense align=left").classes("pp-set-restore")
            with ui.column().classes("pp-set-main"):
                with ui.row().classes("pp-set-top items-center no-wrap"):
                    self._title = ui.label("").classes("pp-set-title")
                    ui.space()
                    with ui.row().classes("pp-set-scope items-center no-wrap"):
                        ui.label("Apply to").classes("pp-muted")
                        self._segmented(
                            [(key, label, None) for key, label in _SCOPES],
                            self.scope,
                            lambda value: setattr(self, "scope", value),
                        )
                    close_button(self._close).classes("pp-set-close")
                self._content = ui.column().classes("pp-set-content")
        self._render_nav()
        self._render_content()

    def _is_open(self) -> bool:
        content = getattr(self, "_content", None)
        return content is not None and not content.is_deleted

    def refresh(self) -> None:
        """A setting changed elsewhere (the ⋯ menu's Page view): show the new values, if open."""
        if self._is_open():
            self._render_nav()
            self._render_content()

    def _values(self) -> dict[str, Any]:
        return sanitized(self.config.values)

    def _minimal(self) -> bool:
        return bool(self._values()["settings.minimal"])

    def _ai_on(self) -> bool:
        return bool(self._values()["features.ai"])

    def _keep_page_shown(self) -> None:
        """A switch can take the shown page away (AI off): fall back to the first page."""
        if self.page not in shown_sections(self._values()):
            self.page = next(iter(SECTIONS))

    def _render_nav(self) -> None:
        self._nav.clear()
        with self._nav:
            for name in shown_sections(self._values()):
                on = name == self.page and not self.query
                item = ui.row().classes("pp-set-navitem items-center no-wrap")
                if on:
                    item.classes("pp-set-navitem-on")
                with item:
                    line_icon(SECTION_ICONS.get(name, "circle")).classes("pp-set-navicon")
                    ui.label(name).classes("pp-set-navlabel")
                item.on("click", lambda _e, n=name: self._go(n))

    def _render_mode(self) -> None:
        """Light / Dark / System above Restore defaults (a row; a column when the list is folded,
        by CSS)."""
        self._mode.clear()
        current = str(sanitized(self.config.values)["appearance.theme"])
        with self._mode:
            self._segmented(
                [(key, "", icon) for key, icon in THEME_ICONS.items()],
                current,
                lambda value: self._commit(ALL["appearance.theme"], value),
            )

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
                found = self._drawable(search_settings(self.query, values))
                if not found:
                    ui.label("No settings match.").classes("pp-muted pp-set-none")
                    return
                with self._box():
                    for setting in found:
                        self._row(setting, values[setting.key])
                return
            self._title.set_text(self.page)
            if self.page == "General":
                self._about()  # the version and the vault come first
            listed = [s for s in SECTIONS[self.page] if is_shown(self.page, s, values)]
            group: str | None = None
            box: ui.element | None = None
            for setting in self._drawable(listed):
                if box is None or setting.group != group:
                    if box is not None:
                        with box:
                            self._after_group(group)
                    group = setting.group
                    box = self._open_box(group)
                with box:
                    self._row(setting, values[setting.key])
            if box is not None:
                with box:
                    self._after_group(group)
            if self.page == "General" and not self._minimal():
                self._advanced()

    def _drawable(self, settings: list[Setting]) -> list[Setting]:
        """``settings`` with the ones drawn inside another control replaced by that one (each
        key once; on the AI page the memories panel draws the memories folder)."""
        out: list[Setting] = []
        for s in settings:
            if s.key == "ai.chats_folder" and self.page == "AI" and not self.query:
                continue
            owner = _DRAWN_ELSEWHERE.get(s.key)
            pick = s if owner is None else ALL[owner]
            if all(o.key != pick.key for o in out):
                out.append(pick)
        return out

    def _after_group(self, group: str | None) -> None:
        if self.page == "AI" and group == "Model" and self._access is not None:
            self._access.build(self._open_box)  # what the AI may read: also in minimal settings
        if self._minimal():
            return  # the hand-made panels are for the full settings
        if self.page == "AI" and group == "Memories" and self._memories is not None:
            self._memories.build()  # the folder and the saved chats, under their settings
        if self.page == "General" and group == "Templates":
            self._templates()  # write / edit a template, or add one from a file

    def _open_box(self, group: str | None) -> ui.element:
        """A group: its title above a box whose rows are split by thin lines (a folded group's
        box sits inside its expansion)."""
        with self._content:
            if group and (self.page, group) in _FOLDED:
                fold = ui.expansion(group, value=group in self._open_groups)
                fold.classes("pp-set-fold").props("dense switch-toggle-side")
                fold.on_value_change(
                    lambda e: (self._open_groups.add if e.value else self._open_groups.discard)(
                        group
                    )
                )
                with fold:
                    return self._box()
            if group:
                self._group(group)
            return self._box()

    def _box(self) -> ui.element:
        return ui.column().classes("pp-set-box")

    def _group(self, title: str) -> None:
        ui.label(title).classes("pp-set-group")

    def _about(self) -> None:
        """General's first groups: the version, and the vault (with Change… to open another)."""
        with self._open_box("Version"):
            self._info("paper-pile", f"Version {__version__}")
        if self._vault_root is not None:
            with self._open_box("Vault"):
                self._vault_row(self._vault_root)

    def _advanced(self) -> None:
        """General → Advanced: maintenance actions (full settings only)."""
        if self._rebuild_index is None:
            return
        rebuild = self._rebuild_index

        async def run() -> None:
            button.props("loading")
            try:
                count = await rebuild()
            except Exception:
                log.exception("index rebuild failed")
                ui.notify("Could not rebuild the index; see the log.", type="negative")
                return
            finally:
                button.props(remove="loading")
            ui.notify(f"Index rebuilt: {count} notes", timeout=2000, position="bottom")

        with self._open_box("Advanced"), ui.row().classes("pp-set-row items-center"):
            with ui.column().classes("pp-set-text"):
                ui.label("Rebuild search index").classes("pp-set-label")
                ui.label("If search, backlinks or tags look out of date").classes("pp-set-help")
            with ui.row().classes("pp-set-control items-center no-wrap"):
                button = ui.button("Rebuild", icon=ico("refresh-cw"), on_click=run, color=None)
                button.props("flat dense no-caps").classes("pp-instr-btn")

    def _vault_row(self, root: Path) -> None:
        """The vault's name and folder, with Change… (a normal row: the button drops under the
        text when the pane is narrow, and shows only its icon when even that is too narrow)."""
        path = str(root)
        with ui.row().classes("pp-set-row items-center"):
            with ui.column().classes("pp-set-text pp-set-vault"):
                ui.label(root.name or "Vault").classes("pp-set-label")
                tip(ui.label(path).classes("pp-set-help pp-set-path"), path)
            if self._open_vault is not None:
                with ui.row().classes("pp-set-control items-center no-wrap"):
                    ui.button(
                        "Change…", icon=ico("folder-open"), on_click=self._open_vault, color=None
                    ).props("flat dense no-caps").classes("pp-instr-btn pp-set-vault-change")

    def _info(self, label: str, value: str) -> None:
        """A read-only row (the version)."""
        with ui.row().classes("pp-set-row pp-set-row-inline items-center no-wrap"):
            with ui.column().classes("pp-set-text"):
                ui.label(label).classes("pp-set-label")
            tip(ui.label(value).classes("pp-set-info"), value)

    # ---- one row ---------------------------------------------------------------------------

    def _row(self, setting: Setting, current: Any) -> None:
        if setting.key == "ai.instructions":
            self._instruction(setting)
            return
        inline = " pp-set-row-inline" if setting.kind == "bool" else ""  # a switch never drops
        with ui.row().classes("pp-set-row items-center" + inline):
            missing = setting.key == "features.ai" and not ai_available()
            with ui.column().classes("pp-set-text"):
                ui.label(setting.label).classes("pp-set-label")
                if setting.help or missing:
                    ui.label(ai_unavailable() if missing else setting.help).classes("pp-set-help")
                error = ui.label("").classes("pp-set-error")
                error.set_visibility(False)
                self._errors[setting.key] = error
            with ui.row().classes("pp-set-control items-center no-wrap"):
                self._control(setting, current)

    def _control(self, setting: Setting, current: Any) -> None:
        def commit(value: Any, s: Setting = setting) -> None:
            self._commit(s, value)

        if setting.kind == "bool":
            switch = ui.switch(value=bool(current), on_change=lambda e: commit(e.value))
            if setting.key == "features.ai" and not ai_available():
                switch.disable()
        elif setting.key == "appearance.accent":
            self._accent_picker(setting, str(current))
        elif setting.key in _SEGMENTED:
            icons = THEME_ICONS if setting.key == "appearance.theme" else {}
            labels = {
                "editor.page_view": PAGE_VIEWS,
                "appearance.motion": MOTION_LABELS,
                "appearance.icons": ICON_COLORS,
                "ai.selection_to_chat": SELECTION_TO_CHAT,
            }.get(setting.key, {})
            self._segmented(
                [(c, labels.get(c, c) if not icons else "", icons.get(c)) for c in setting.choices],
                str(current),
                commit,
            )
        elif setting.key == "general.language":
            ui.select(LANGUAGES, value=str(current), on_change=lambda e: commit(e.value)).props(
                "dense outlined options-dense popup-content-class=pp-set-popup"
            ).classes("pp-set-field")
        elif setting.kind == "choice":
            ui.select(
                list(setting.choices), value=str(current), on_change=lambda e: commit(e.value)
            ).props("dense outlined options-dense popup-content-class=pp-set-popup").classes(
                "pp-set-field"
            )
        elif setting.key == "editor.font_family":
            self._font_picker(setting, str(current), FONTS)
        elif setting.key == "editor.code_font_family":
            self._font_picker(setting, str(current), CODE_FONTS)
        elif setting.step is not None:
            self._stepper(setting, current)
        elif setting.key == "vault.daily_notes_template":
            self._daily_template(setting, str(current), commit)
        elif setting.key.endswith("_folder"):
            if setting.key == "vault.images_folder" and self._gallery is not None:
                ui.button("Gallery", icon=ico("images"), on_click=self._gallery, color=None).props(
                    "flat dense no-caps"
                ).classes("pp-instr-btn")
            folders = self._folders()
            options = folders if not current or current in folders else [current, *folders]
            ui.select(
                options,
                value=current or None,
                with_input=True,
                new_value_mode="add-unique",
                clearable=True,
                on_change=lambda e: commit(e.value or ""),
            ).props(
                "dense outlined options-dense hide-dropdown-icon popup-content-class=pp-set-popup"
                f' placeholder="{setting.placeholder or "None"}"'
            ).classes("pp-set-field")
            if setting.key in BY_KEY:
                self._folder_buttons(setting)
        elif setting.key == "ai.model":
            names = self._models()
            options = names if current in names or not current else [current, *names]
            ui.select(
                options,
                value=current or None,
                with_input=True,
                new_value_mode="add-unique",
                on_change=lambda e: commit(e.value),
            ).props("dense outlined options-dense popup-content-class=pp-set-popup").classes(
                "pp-set-field"
            )
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
                        line_icon(icon).classes("pp-seg-icon")
                    if label:
                        ui.label(label)
                if icon and not label:
                    tip(item, key.capitalize())
                item.on("click", lambda _e, k=key: pick(k))
                items[key] = item

    def _accent_picker(self, setting: Setting, current: str) -> None:
        """The accent as a colour dot; its popup is a grid of presets plus a colour-code field
        with a picker (any #hex, rgb() or hsl() colour)."""
        tiles: dict[str, ui.element] = {}

        def choose(value: str, menu: ui.menu | None) -> None:
            if not self._check(setting, value):
                return
            self._commit(setting, value)
            chosen = str(parse_value(setting, value).value)
            light = accent_colors(chosen)[0]
            dot.style(f"background:{light}")
            for key, tile in tiles.items():
                tile.classes(
                    add="pp-swatch-on" if key == chosen else "",
                    remove="" if key == chosen else "pp-swatch-on",
                )
            if menu is not None:
                code.set_value(light)
                menu.close()

        light = accent_colors(current)[0]
        with ui.button().props("flat dense").classes("pp-pick pp-pick-accent") as btn:
            dot = ui.element("span").classes("pp-swatch-dot").style(f"background:{light}")
            line_icon("chevron-down", "s").classes("pp-pick-chev")
            menu = ui.menu().props('anchor="bottom right" self="top right"')
            menu.classes("pp-set-popup pp-accent-popup")
            with menu:
                with ui.element("div").classes("pp-swatchgrid"):
                    for key, (color, _dark) in ACCENTS.items():
                        tile = ui.element("div").classes("pp-swatch").style(f"background:{color}")
                        if key == current:
                            tile.classes("pp-swatch-on")
                        tile.on("click", lambda _e, k=key: choose(k, menu))
                        tiles[key] = tile
                code = ui.color_input(value=light, preview=True).props("dense outlined")
                code.classes("pp-accent-code")
                code.button.props(f'icon="{ico("pipette")}"')
                code.on_value_change(
                    lambda e: (
                        choose(str(e.value), None) if parse_color(str(e.value or "")) else None
                    )
                )
        del btn

    def _stepper(self, setting: Setting, current: Any) -> None:
        """A number between − and + buttons (one ``setting.step`` each, within the limits); the
        number itself can still be typed."""

        def show(value: Any) -> None:
            field.set_value(str(value))
            minus.set_enabled(setting.minimum is None or float(value) > setting.minimum)
            plus.set_enabled(setting.maximum is None or float(value) < setting.maximum)

        def step(direction: int) -> None:
            value = stepped(setting, field.value, direction)
            show(value)
            self._commit(setting, value)

        def typed() -> None:
            if self._check(setting, field.value):
                self._commit(setting, field.value)
                show(parse_value(setting, field.value).value)

        with ui.row().classes("pp-stepper items-center no-wrap"):
            minus = ui.button(icon=ico("minus"), on_click=lambda: step(-1), color=None)
            minus.props("flat dense").classes("pp-step-btn")
            field = ui.input(value=str(current)).props("dense borderless").classes("pp-step-value")
            plus = ui.button(icon=ico("plus"), on_click=lambda: step(1), color=None)
            plus.props("flat dense").classes("pp-step-btn")
        tip(minus, "Smaller")
        tip(plus, "Larger")
        field.on_value_change(lambda e: self._check(setting, e.value))
        field.on("blur", lambda _e: typed())
        field.on("keydown.enter", lambda _e: typed())
        field.on("keydown.up", lambda _e: step(1))
        field.on("keydown.down", lambda _e: step(-1))
        show(current)

    def _font_picker(
        self, setting: Setting, current: str, fonts: tuple[tuple[str, str], ...]
    ) -> None:
        """The font as one button (its name, drawn in that font); the popup lists the fonts, each
        in its own face, and a "Custom" line for any other CSS font list."""
        known = {css: label for label, css in fonts}
        shown = known.get(current, "Custom")
        with ui.button().props("flat no-caps dense").classes("pp-pick pp-pick-font") as btn:
            label = ui.label(shown).style(f"font-family:{current}")
            line_icon("chevron-down", "s").classes("pp-pick-chev")
            with (
                ui.menu()
                .props('anchor="bottom right" self="top right"')
                .classes("pp-set-popup pp-fontmenu") as menu
            ):
                for name, css in fonts:
                    with ui.menu_item(
                        on_click=lambda _e=None, c=css, n=name: self._font_chosen(
                            setting, c, n, label
                        )
                    ).classes("pp-fontitem"):
                        ui.label(name).style(f"font-family:{css}").classes("pp-fontname")
                        ui.label("Aa 123").style(f"font-family:{css}").classes("pp-fontsample")
                        if css == current:
                            line_icon("check", "s").classes("pp-menu-check pp-check")
                ui.separator()
                custom = (
                    ui.input(
                        value="" if current in known else current,
                        placeholder="Custom CSS font list, then Enter",
                    )
                    .props("dense borderless")
                    .classes("pp-fontcustom")
                )

                def apply_custom() -> None:
                    value = (custom.value or "").strip()
                    if value and self._check(setting, value):
                        self._font_chosen(setting, value, "Custom", label)
                        menu.close()

                custom.on("keydown.enter", lambda _e: apply_custom())
        del btn

    def _font_chosen(self, setting: Setting, css: str, name: str, label: ui.label) -> None:
        label.set_text(name)
        label.style(f"font-family:{css}")
        self._commit(setting, css)

    # ---- the daily-note template (General → Daily notes) ------------------------------------

    def _daily_template(
        self, setting: Setting, current: str, commit: Callable[[Any], None]
    ) -> None:
        """A note path, typed or picked: the notes of the daily-note templates folder
        (``<templates>/daily``) come first; *Browse* in the native window."""
        daily = daily_templates_folder(str(sanitized(self.config.values)["vault.templates_folder"]))
        notes = self._notes()
        first = [n for n in notes if daily and n.startswith(daily + "/")]
        options = first + [n for n in notes if n not in first]
        if current and current not in options:
            options = [current, *options]
        pick = (
            ui.select(
                options,
                value=current or None,
                with_input=True,
                new_value_mode="add-unique",
                clearable=True,
                on_change=lambda e: commit(e.value or ""),
            )
            .props(
                "dense outlined options-dense hide-dropdown-icon popup-content-class=pp-set-popup"
                f' placeholder="{setting.placeholder}"'
            )
            .classes("pp-set-field")
        )
        if not self._native:
            return

        async def browse() -> None:
            value = await self._pick_file()
            if not value:
                return
            if value.startswith(("/", "~")):
                ui.notify("Pick a note inside this vault.", type="warning")
                return
            pick.set_options([value, *options], value=value)

        ui.button("Browse", on_click=browse, color=None).props("flat dense no-caps").classes(
            "pp-instr-btn"
        )

    # ---- the app's folders (General → Folders) ---------------------------------------------

    def _folder_buttons(self, setting: Setting) -> None:
        """*Clear* after a folder setting's field."""
        clear = ui.button(
            "Clear", on_click=lambda s=setting: self._clear_folder(s), color=None
        ).props("flat dense no-caps")
        clear.classes("pp-mem-del")
        if self._vault_root is None:
            clear.set_enabled(False)

    async def _clear_folder(self, setting: Setting) -> None:
        """Move a folder's contents to the trash, after a warning naming it and the count."""
        if self._vault_root is None:
            return
        value = str(sanitized(self.config.values)[setting.key])
        folder = folder_path(self._vault_root, setting.key, value)
        name = value or "the vault"
        if not can_clear(self._vault_root, folder):
            ui.notify(f"{name} cannot be cleared.", type="warning")
            return
        count = files_in(folder)
        if count == 0:
            ui.notify(f"{name} is already empty.", timeout=1500, position="bottom")
            return
        what = {
            "ai.chats_folder": "All saved chats are removed from the memories list.",
            "vault.images_folder": "Notes that show these pictures will show broken images.",
            "vault.daily_notes_folder": "Your daily notes disappear from the calendar.",
            "vault.templates_folder": "/template will have nothing to offer.",
        }.get(setting.key, "")
        with self._content, Dialog() as dialog, ui.card().classes("pp-dialog"):
            ui.label(f"Clear {name}?").classes("pp-dialog-title")
            ui.label(
                f"{count} file{'s' * (count != 1)} in {folder} move to the vault's trash "
                f"(.trash), where you can restore them. {what}"
            ).classes("pp-muted pp-dialog-text")
            with ui.row().classes("justify-end w-full"):
                ui.button("Cancel", on_click=lambda: dialog.submit(False)).props("flat no-caps")
                ui.button("Move to trash", on_click=lambda: dialog.submit(True)).props(
                    "no-caps color=negative"
                )
        confirmed = await dialog
        dialog.delete()
        if not confirmed:
            return
        try:
            moved = clear_folder(Vault(self._vault_root), folder)
        except (OSError, ValueError):
            log.exception("could not clear %s", folder)
            ui.notify(f"Could not clear {name}.", type="negative")
            return
        self._on_cleared(setting.key)
        ui.notify(f"{moved} files moved to the trash", timeout=2000, position="bottom")

    # ---- templates (General → Templates) ----------------------------------------------------

    def _templates(self) -> None:
        """Under the Templates settings: write or edit a template, or add one from a file."""
        with ui.column().classes("pp-set-row pp-set-block"):
            with ui.row().classes("pp-set-blockhead w-full no-wrap items-center"):
                with ui.column().classes("pp-set-text"):
                    ui.label("Your templates").classes("pp-set-label")
                    ui.label("Used by /template").classes("pp-set-help")
                self._segmented(
                    [(k, label, icon) for k, label, icon in _INSTRUCTION_FROM],
                    self._tpl_mode,
                    self._tpl_mode_changed,
                )
            self._templates_body()

    def _tpl_mode_changed(self, value: str) -> None:
        self._tpl_mode = value
        self._templates_body.refresh()

    @ui.refreshable_method
    def _templates_body(self) -> None:
        folder = str(sanitized(self.config.values)["vault.templates_folder"])
        if self._vault_root is None or not folder:
            ui.label("Choose a templates folder first.").classes("pp-muted pp-set-help")
            return
        vault = Vault(self._vault_root)
        if self._tpl_mode == "file":
            self._template_from_file(vault, folder)
            return
        paths = list_templates(vault, folder)
        current = self._tpl_current if self._tpl_current in paths else None
        options = {"": "New template", **{p: p[len(folder) + 1 : -3] for p in paths}}
        with ui.row().classes("w-full no-wrap items-center pp-tpl-head"):
            ui.select(
                options,
                value=current or "",
                on_change=lambda e: self._tpl_choose(str(e.value or "")),
            ).props("dense outlined options-dense popup-content-class=pp-set-popup").classes(
                "pp-tpl-pick"
            )
            name = ui.input(placeholder="Name").props("dense outlined")
            name.classes("pp-grow pp-tpl-name")
            name.set_visibility(current is None)
        text = vault.read_text(current) if current else ""

        def fill(draft: str) -> bool:  # Write with AI: into the box; Save keeps it
            box.set_value(draft)
            return True

        box = ui.textarea(value=text, placeholder="# {{title}}\n\n{{date}}\n\n## Notes\n- ")
        box.props("outlined").classes("pp-instr-box pp-tpl-box")  # drag the corner to resize
        with ui.row().classes("pp-instr-bar w-full items-center no-wrap"):
            ui.label("{{title}}, {{date}} and {{time}} are filled in").classes(
                "pp-muted pp-instr-count"
            )
            ui.space()
            if self._draft is not None and self._ai_on():
                ui.button(
                    "Write with AI",
                    icon=ico("sparkles"),
                    on_click=lambda: self._write_with_ai("template", fill),
                    color=None,
                ).props("flat dense no-caps").classes("pp-instr-btn")
            if current:
                ui.button(
                    "Delete", on_click=lambda: self._tpl_delete(vault, current), color=None
                ).props("flat dense no-caps").classes("pp-mem-del")
            ui.button(
                "Save",
                on_click=lambda: self._tpl_save(vault, folder, current, name.value, box.value),
            ).props("dense no-caps unelevated").classes("pp-tpl-save")

    def _tpl_choose(self, path: str) -> None:
        self._tpl_current = path or None
        self._templates_body.refresh()

    def _tpl_save(
        self, vault: Vault, folder: str, current: str | None, name: str | None, text: str | None
    ) -> None:
        body = text or ""
        try:
            if current:
                vault.write_text(current, body)
                saved = current
            else:
                if not (name or "").strip():
                    ui.notify("Give the template a name.", type="warning")
                    return
                saved = new_template(vault, folder, (name or "").strip(), body)
        except ExistsError:
            ui.notify("A template with that name already exists.", type="warning")
            return
        except (VaultError, ValueError, OSError) as exc:
            ui.notify(f"Could not save the template: {exc}", type="negative")
            return
        self._tpl_current = saved
        self._templates_body.refresh()
        ui.notify("Template saved", timeout=1500, position="bottom")

    async def _tpl_delete(self, vault: Vault, path: str) -> None:
        name = Path(path).stem
        with self._content, Dialog() as dialog, ui.card().classes("pp-dialog"):
            ui.label(f"Delete the template “{name}”?").classes("pp-dialog-title")
            ui.label("It moves to the vault's trash, where you can restore it.").classes(
                "pp-muted pp-dialog-text"
            )
            with ui.row().classes("justify-end w-full"):
                ui.button("Cancel", on_click=lambda: dialog.submit(False)).props("flat no-caps")
                ui.button("Move to trash", on_click=lambda: dialog.submit(True)).props(
                    "no-caps color=negative"
                )
        ok = await dialog
        dialog.delete()
        if not ok:
            return
        try:
            vault.delete(path)
        except (VaultError, OSError):
            log.exception("could not delete template %s", path)
            ui.notify("Could not delete the template.", type="negative")
            return
        self._tpl_current = None
        self._templates_body.refresh()

    def _template_from_file(self, vault: Vault, folder: str) -> None:
        notes = [n for n in self._notes() if not n.startswith(folder.strip("/") + "/")]
        with ui.row().classes("w-full no-wrap items-center pp-instr-file"):
            pick = ui.select(
                notes, with_input=True, new_value_mode="add-unique", clearable=True
            ).props(
                "dense outlined options-dense hide-dropdown-icon popup-content-class=pp-set-popup"
                ' placeholder="A note of this vault, or a path to a .md file"'
            )
            pick.classes("pp-grow")
            if self._native:

                async def browse() -> None:
                    value = await self._pick_file()
                    if value:
                        pick.set_options([value, *notes], value=value)

                ui.button("Browse", on_click=browse, color=None).props(
                    "flat dense no-caps"
                ).classes("pp-instr-btn")
            ui.button(
                "Add as template", on_click=lambda: self._tpl_import(vault, folder, pick.value)
            ).props("dense no-caps unelevated").classes("pp-tpl-save")

    def _tpl_import(self, vault: Vault, folder: str, value: object) -> None:
        chosen = str(value or "").strip()
        if not chosen:
            ui.notify("Choose a note or a .md file first.", type="warning")
            return
        try:
            source = Path(chosen).expanduser()
            if not source.is_absolute():
                source = vault.resolve(chosen)
            if source.suffix.lower() not in {".md", ".txt"} or not source.is_file():
                raise ValueError("not a .md or .txt file")
            saved = import_template(vault, folder, source)
        except (VaultError, ValueError, OSError) as exc:
            ui.notify(f"Could not add it: {exc}", type="negative")
            return
        self._tpl_current, self._tpl_mode = saved, "text"
        ui.notify(f"Added as the template “{Path(saved).stem}”", timeout=2000, position="bottom")
        self._render_content()

    # ---- the system instruction ------------------------------------------------------------

    def _instruction(self, setting: Setting) -> None:
        """Typed (a large box the user can stretch, Write with AI) or read from a .md / .txt
        file."""
        with ui.column().classes("pp-set-row pp-set-block"):
            with ui.row().classes("pp-set-blockhead w-full no-wrap items-center"):
                with ui.column().classes("pp-set-text"):
                    ui.label(setting.label).classes("pp-set-label")
                    ui.label(setting.help).classes("pp-set-help")
                    error = ui.label("").classes("pp-set-error")
                    error.set_visibility(False)
                    self._errors[setting.key] = error
                self._segmented(
                    [(k, label, icon) for k, label, icon in _INSTRUCTION_FROM],
                    str(sanitized(self.config.values)["ai.instructions_from"]),
                    self._instruction_from,
                )
            self._instruction_body()

    def _instruction_from(self, value: str) -> None:
        self._commit(ALL["ai.instructions_from"], value)
        self._instruction_body.refresh()

    @ui.refreshable_method
    def _instruction_body(self) -> None:
        values = sanitized(self.config.values)
        if values["ai.instructions_from"] == "file":
            self._instruction_file(str(values["ai.instructions_file"]))
            return
        setting = ALL["ai.instructions"]
        box = ui.textarea(value=str(values["ai.instructions"]), placeholder=setting.placeholder)
        box.props(f"outlined maxlength={MAX_TEXT_CHARS}").classes("pp-instr-box")  # drag to resize
        box.on("blur", lambda _e: self._commit(setting, box.value or ""))
        with ui.row().classes("pp-instr-bar w-full items-center no-wrap"):
            count = ui.label("").classes("pp-muted pp-instr-count")
            ui.space()
            if self._draft is not None:
                ui.button(
                    "Write with AI",
                    icon=ico("sparkles"),
                    on_click=lambda: self._write_with_ai("instruction", lambda t: keep(t)),
                    color=None,
                ).props("flat dense no-caps").classes("pp-instr-btn")

        def keep(text: str) -> bool:
            if not self._commit(setting, text):
                return False
            box.set_value(text)
            return True

        def counted() -> None:
            count.set_text(f"{len(box.value or '')} / {MAX_TEXT_CHARS}")

        box.on_value_change(lambda _e: counted())
        counted()

    def _instruction_file(self, current: str) -> None:
        setting = ALL["ai.instructions_file"]
        notes = self._notes()
        options = notes if not current or current in notes else [current, *notes]
        with ui.row().classes("w-full no-wrap items-center pp-instr-file"):
            pick = ui.select(
                options,
                value=current or None,
                with_input=True,
                new_value_mode="add-unique",
                clearable=True,
                on_change=lambda e: self._commit(setting, e.value or ""),
            ).props(
                "dense outlined options-dense hide-dropdown-icon popup-content-class=pp-set-popup"
                ' placeholder="A note of this vault, or a path to a .md file"'
            )
            pick.classes("pp-grow")
            if self._native:
                ui.button("Browse", on_click=lambda: self._browse_instruction(), color=None).props(
                    "flat dense no-caps"
                ).classes("pp-instr-btn")
        error = ui.label("").classes("pp-set-error")
        error.set_visibility(False)
        self._errors[setting.key] = error

    async def _pick_file(self) -> str | None:
        """The system's file picker (native window): a .md / .txt file, vault-relative when it is
        inside the vault."""
        import webview  # native window only
        from nicegui import app

        chosen = await app.native.main_window.create_file_dialog(  # type: ignore[union-attr]
            dialog_type=webview.FileDialog.OPEN,
            directory=str(self._vault_root or ""),
            file_types=("Markdown (*.md;*.txt)",),
        )
        picked = chosen if isinstance(chosen, str) else (chosen[0] if chosen else None)
        if not picked:
            return None
        path = Path(picked)
        value = str(path)
        if self._vault_root is not None:
            with contextlib.suppress(ValueError):  # inside the vault: kept vault-relative
                value = path.resolve().relative_to(self._vault_root.resolve()).as_posix()
        return value

    async def _browse_instruction(self) -> None:
        value = await self._pick_file()
        if value and self._commit(ALL["ai.instructions_file"], value):
            self._instruction_body.refresh()

    def _write_with_ai(self, kind: str, use: Callable[[str], bool]) -> None:
        """Describe it in a few words; the model drafts a system instruction or a template
        (``kind``), which ``use`` takes when the user keeps it (False keeps the dialog open)."""
        draft = self._draft
        assert draft is not None
        ask = {
            "instruction": "What should the assistant be like?",
            "template": "What is the template for? e.g. a meeting, a book review",
        }[kind]
        with self._content, Dialog() as dialog, ui.card().classes("pp-dialog pp-instr-dialog"):
            ui.label("Write with AI").classes("pp-dialog-title")
            brief = ui.input(placeholder=ask).props("outlined dense autofocus")
            brief.classes("w-full")
            out = ui.textarea(placeholder="The draft appears here; edit it as you like").props(
                f"outlined maxlength={MAX_TEXT_CHARS}"
            )
            out.classes("pp-instr-big pp-instr-draft")
            with ui.row().classes("items-center w-full no-wrap"):
                status = ui.label("").classes("pp-muted pp-instr-count")
                ui.space()
                ui.button("Cancel", on_click=dialog.close).props("flat no-caps")
                go = ui.button("Write", on_click=lambda: run()).props("flat no-caps")
                keep_btn = ui.button("Use this", on_click=lambda: keep())
                keep_btn.props("no-caps unelevated")
                keep_btn.set_enabled(False)

        async def run() -> None:
            text = (brief.value or "").strip()
            if not text:
                return
            out.set_value("")
            go.set_enabled(False)
            keep_btn.set_enabled(False)
            status.set_text("Writing…")
            try:
                async for piece in draft(kind, text):
                    out.set_value((out.value or "") + piece)
                status.set_text("")
            except Exception as exc:  # the provider's message is fit for the user
                log.warning("drafting a %s failed: %s", kind, exc)
                status.set_text(str(exc) or "The AI could not answer.")
            finally:
                go.set_enabled(True)
                go.set_text("Write again")
                keep_btn.set_enabled(bool((out.value or "").strip()))

        def keep() -> None:
            if use((out.value or "").strip()):
                dialog.close()

        brief.on("keydown.enter", lambda _e: run())
        dialog.on("hide", lambda _e: dialog.delete())
        dialog.open()

    # ---- validation and saving -------------------------------------------------------------

    def _check(self, setting: Setting, value: Any) -> bool:
        """Show the problem with ``value`` (if any) under its row."""
        parsed = parse_value(setting, value)
        label = self._errors.get(setting.key)
        if label is not None:
            label.set_text(parsed.error)
            label.set_visibility(not parsed.ok)
        return parsed.ok

    def set_value(self, key: str, value: Any) -> bool:
        """Save one setting from outside a row (the memories folder); False if refused."""
        return self._commit(ALL[key], value)

    def _commit(self, setting: Setting, value: Any) -> bool:
        """Apply and save ``value`` if it is valid and different from what is in force."""
        parsed = parse_value(setting, value)
        if setting.key in self._errors and not self._check(setting, value):
            return False
        if not parsed.ok:
            ui.notify(parsed.error, type="warning")
            return False
        if parsed.value == sanitized(self.config.values)[setting.key]:
            return True
        self.config.set(setting.key, parsed.value, self.scope)
        try:
            self.config.save(self.scope)
        except OSError:
            log.exception("could not save the settings")
            ui.notify("Could not save the settings.", type="negative")
            return False
        self._on_applied({setting.key})
        if setting.key in _RELAYOUT and self._is_open():
            self._keep_page_shown()
            self._render_nav()
            self._render_content()
        if setting.key == "appearance.theme" and self._is_open():  # sidebar and row agree
            self._render_mode()
            if self.page == "Appearance" and not self.query:
                self._render_content()
        return True

    def _restore(self) -> None:
        """Forget every value in the chosen layer (they fall back to the layer below)."""
        for key in ALL:
            self.config.unset(key, self.scope)
        self.config.save(self.scope)
        self._on_applied(set(ALL))
        self._keep_page_shown()
        self._render_nav()
        self._render_mode()
        where = "this vault" if self.scope == "vault" else "all vaults"
        ui.notify(f"Defaults restored for {where}", timeout=2000, position="bottom")
        self._render_content()
