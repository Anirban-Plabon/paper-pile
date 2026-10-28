"""The 3-pane frame: [file tree | tabs + editor | AI chat] over a status bar.

Pane widths (px) and open/closed state are remembered per vault in ``session.json``.
A pane keeps its last width while collapsed, so re-opening restores it.
"""

import asyncio
import logging
from collections.abc import AsyncIterator
from datetime import date, datetime
from pathlib import Path
from typing import Any

from nicegui import background_tasks, run, ui

from paper_pile.core.ai.chats import chats_folder
from paper_pile.core.ai.engine import AiEngine
from paper_pile.core.ai.instructions import draft_messages
from paper_pile.core.ai.provider import Health
from paper_pile.core.commands import push_recent
from paper_pile.core.config import Config
from paper_pile.core.daily import DEFAULT_FORMAT, daily_relpath, new_daily_text, untouched_daily
from paper_pile.core.events import EventBus
from paper_pile.core.history import History
from paper_pile.core.index import Index
from paper_pile.core.picker import switcher_notes
from paper_pile.core.session import (
    MAX_RECENT_NOTES,
    SessionState,
    load_session,
    renamed,
    save_session,
)
from paper_pile.core.settings import feature_on, sanitized
from paper_pile.core.templates import template_draft_messages
from paper_pile.core.vault import Vault, VaultError
from paper_pile.core.vault_folders import ensure_folders, move_old_chats
from paper_pile.core.watcher import TOPIC as FS_CHANGED
from paper_pile.core.watcher import FsEvent
from paper_pile.gui.commands_palette import palette_commands, palette_items, run_command
from paper_pile.gui.components.ai_access import AccessPanel
from paper_pile.gui.components.calendar import CalendarPane
from paper_pile.gui.components.chat import ChatPane
from paper_pile.gui.components.editor_pane import EditorPane
from paper_pile.gui.components.gallery import Gallery
from paper_pile.gui.components.history_dialog import HistoryDialog
from paper_pile.gui.components.memories import MemoriesPanel
from paper_pile.gui.components.outline import OutlinePane
from paper_pile.gui.components.picker_popup import PickerPopup, PickItem
from paper_pile.gui.components.profile import ProfileBlock
from paper_pile.gui.components.right_pane import RightPane
from paper_pile.gui.components.settings import SettingsPane
from paper_pile.gui.components.statusbar import StatusBar, status_bar
from paper_pile.gui.components.tag_pane import TagPane
from paper_pile.gui.components.trash_dialog import TrashDialog
from paper_pile.gui.components.tree import FileTree
from paper_pile.gui.components.vault_dialog import ask_vault
from paper_pile.gui.icons import icon_button, line_icon, set_icon
from paper_pile.gui.theme import EDITOR_OPTION_KEYS, ThemeController, editor_options
from paper_pile.gui.tips import tip
from paper_pile.gui.vault_host import VaultHost
from paper_pile.gui.window import WindowChrome

log = logging.getLogger("paper_pile.layout")

# (min, max) pane width in px while open. Dragging stops at the limits.
WIDTH_LIMITS = {"left": (180, 480), "right": (280, 640)}
SETTINGS_LIMITS = (460, 960)  # the right pane while it shows Settings (its nav folds below 560)
SETTINGS_OPEN_MIN = 640  # Settings always opens unfolded; dragging narrower folds it
SAVE_DELAY_S = 0.4


class PaneSplitter(ui.splitter):
    """A px-sized splitter whose limits can change (collapsed panes are pinned to 0)."""

    def set_limits(self, low: int, high: int) -> None:
        self._props["limits"] = [low, high]
        self._props["data-min"] = low  # static/panes.js: dragged past this, the pane folds away
        self.update()


def clamp_width(pane: str, width: int) -> int:
    low, high = SETTINGS_LIMITS if pane == "settings" else WIDTH_LIMITS[pane]
    return max(low, min(high, width))


class MainLayout:
    def __init__(
        self,
        vault: Path,
        *,
        can_reveal: bool = False,
        fs_bus: EventBus | None = None,
        host: VaultHost | None = None,
    ) -> None:
        self.vault = vault
        self.host = host  # switches the vault ("Open vault"); None in tests
        self.bus = EventBus()  # tabs/editor subscribe to tree events here (P2)
        self.can_reveal = can_reveal
        self._plain = False  # is the active note a .txt?
        self.tree: FileTree | None = None
        self.editor_pane: EditorPane | None = None
        self._fs_bus = fs_bus
        self.config = Config(vault=vault)
        ensure_folders(vault, self.config)  # .memory, .image, .daily-notes, .template
        move_old_chats(vault, self.config)
        self.index = Index(Vault(vault))
        self.history = History(vault)  # earlier versions of notes (.paper-pile/history.db)
        self.chat: ChatPane | None = None
        self.profile: ProfileBlock | None = None
        self.ai = AiEngine(  # all AI logic; the chat pane and AI commands only draw
            Vault(vault),
            self.config,
            self.index,
            user_name=lambda: self.profile.name if self.profile else "",
        )
        self.state: SessionState = load_session(vault)
        if not (vault / ".paper-pile" / "session.json").exists():  # a vault opened the first time
            mode = self.config.get("editor.default_mode", "live")
            self.state.mode = "source" if mode == "source" else "live"
        self.theme = ThemeController(self.config, self._on_dark)
        self.right: RightPane | None = None
        self.calendar: CalendarPane | None = None
        self.tags: TagPane | None = None
        self.outline: OutlinePane | None = None
        self._caret_line = 1
        self._settings_wide = (
            False  # the right pane shows Settings (own width: pane_widths["settings"])
        )
        self.settings = SettingsPane(
            self.config,
            self._settings_applied,
            models=self._known_models,
            on_close=self._close_settings,
            vault_root=self.vault,
            open_vault=self.open_vault,
            folders=Vault(self.vault).folders,
            notes=lambda: sorted(Vault(self.vault).walk_notes(), key=str.lower),
            memories=MemoriesPanel(
                Vault(self.vault),
                folder=self._chats_dir,
                set_folder=lambda value: self.settings.set_value("ai.chats_folder", value),
                native=self.can_reveal,
                open_chat=lambda chat_id: self.chat.open_chat(chat_id) if self.chat else False,
                chats_deleted=lambda ids: self.chat.chats_deleted(ids) if self.chat else None,
                open_note=self._open_new_note,
                user_name=lambda: self.profile.name if self.profile else "",
            ),
            access=AccessPanel(self.ai),
            draft=self._draft_instruction,
            native=self.can_reveal,
            on_cleared=self._folder_cleared,
            gallery=self._open_gallery,
            rebuild_index=self._rebuild_index,
        )
        for pane in (*WIDTH_LIMITS, "settings"):
            self.state.pane_widths[pane] = clamp_width(pane, self.state.pane_widths[pane])
        self._splitters: dict[str, PaneSplitter] = {}
        self._status: StatusBar | None = None
        self._ribbon: ui.element
        self._ribbon_bottom: ui.element
        self._save_handle: asyncio.TimerHandle | None = None
        self._picker: PickerPopup
        self._popups: ui.element

    # ---- building ------------------------------------------------------------------------

    def build(self) -> None:
        self.theme.install()
        if self.can_reveal:  # the native window has no OS title bar: draw our own controls
            ui.query("body").classes("pp-native")
            WindowChrome().build()
        self._popups = ui.element("div").classes("pp-host")  # popups opened from menus
        self._picker = PickerPopup(self._popups)
        with ui.element("div").classes("pp-root"):
            self._ribbon_column()
            outer = self._make_splitter("left", reverse=False)
            with outer.before:
                self._left_pane()
            with outer.after, ui.column().classes("pp-main"):
                inner = self._make_splitter("right", reverse=True)
                inner.classes("pp-grow")
                with inner.before:
                    self._center_pane()
                with inner.after:
                    self._right_pane()
        if self.right is not None and not self.right.has_tabs():
            self.state.panes_open["right"] = False  # AI and Calendar are off: nothing to show
        for pane in WIDTH_LIMITS:
            self._apply(pane)
        ui.on("pp_pane_collapse", lambda e: self._dragged_shut(str(e.args.get("pane"))))
        ui.on("pp_pane_toggle", lambda e: self._edge_double_clicked(str(e.args.get("pane"))))
        self.bus.subscribe("vault.created", lambda path: self._on_created())
        self.bus.subscribe("tree.add_to_chat", lambda path: self._chat_add_note(path))
        self.bus.subscribe("vault.renamed", lambda old, new: self._recent_renamed(old, new))
        self.bus.subscribe("note.reveal", lambda path: self._reveal_in_tree(path))
        for event in ("vault.created", "vault.renamed", "vault.deleted"):
            self.bus.subscribe(event, lambda **_: self.ai.notes_changed())
        self._follow_external_changes()
        ui.context.client.on_disconnect(self._flush_save)  # a debounced save still pending
        if self.editor_pane is not None:  # reopen last session's tabs (after the status bar exists)
            reopen = bool(self._setting("general.restore_tabs"))
            tabs = list(self.state.tabs) if reopen else []
            self.editor_pane.start(tabs, self.state.active if reopen else None)

    def _follow_external_changes(self) -> None:
        """Re-list the tree when files change outside the app (watcher, P1.5)."""
        if self._fs_bus is None:
            return
        unsubscribe = self._fs_bus.subscribe(FS_CHANGED, lambda events: self._on_external(events))
        ui.context.client.on_disconnect(unsubscribe)  # a closed page must stop listening

    def _on_created(self) -> None:
        if self.tree is not None:
            self.tree.refresh()
        self._refresh_calendar()

    def _on_external(self, events: list[FsEvent]) -> None:
        self.ai.notes_changed()
        if self.tree is not None:
            self.tree.refresh()
        self._refresh_calendar()
        if self.editor_pane is not None:
            self.editor_pane.on_external(events)

    def _make_splitter(self, pane: str, *, reverse: bool) -> PaneSplitter:
        splitter = PaneSplitter(reverse=reverse, value=self.state.pane_widths[pane])
        splitter.props("unit=px").classes(f"pp-fill pp-panesplit pp-panesplit-{pane}")
        splitter.on_value_change(lambda e, p=pane: self._on_resize(p, e.value))
        self._splitters[pane] = splitter
        return splitter

    def _ribbon_column(self) -> None:
        """A slim icon column at the left edge while the file tree is folded away."""
        self._ribbon = ui.column().classes("pp-ribbon items-center")
        with self._ribbon:
            with ui.row().classes("pp-ribbon-top pp-dragzone items-center justify-center"):
                icon_button(
                    "panel-left-open", lambda: self.toggle("left"), "Show file tree (Ctrl+B)"
                )
            with ui.element("div").classes("pp-seg pp-tools pp-tools-column"):  # as in the pane
                icon_button(
                    "search", self.search_vault, "Search in all notes (Ctrl+Shift+F)", size="m"
                )
                icon_button("folder-plus", self.new_folder, "New folder", size="m")
                icon_button("file-plus", self.new_note, "New note", size="m")
            ui.space()
            self._ribbon_bottom = ui.column().classes("pp-ribbon-bottom items-center")

    def open_note(self) -> None:
        """The quick switcher (Ctrl+O): pick a note by name."""
        background_tasks.create(self._switcher())

    async def _switcher(self) -> None:
        notes = list(Vault(self.vault).walk_notes())  # once per popup, not per keystroke

        def search(query: str) -> list[PickItem]:
            paths = switcher_notes(query, notes, self.state.recent_notes)
            items = [
                PickItem(p, p.rsplit("/", 1)[-1].removesuffix(".md"), p.rpartition("/")[0])
                for p in paths
            ]
            name = query.strip()
            if name and all(i.title.lower() != name.lower() for i in items):
                items.append(PickItem("", f"Create “{name}”", icon="file-plus"))
            return items

        picked = await self._picker.pick("Open a note by name…", search)
        if picked is None or self.editor_pane is None:
            return
        item, aside = picked
        if not item.key:  # Create "name"
            name = item.title.removeprefix("Create “").removesuffix("”")
            if self.tree is not None:
                try:
                    self.tree.create_note(name)
                except VaultError as exc:
                    ui.notify(str(exc), type="negative")
        elif aside:
            await self.editor_pane.open_in_split(item.key)
        else:
            self.bus.publish("tree.open", path=item.key)

    def open_palette(self) -> None:
        """The command palette (Ctrl+P)."""
        background_tasks.create(self._palette())

    async def _palette(self) -> None:
        commands = palette_commands(self)
        picked = await self._picker.pick(
            "Type a command…", lambda query: palette_items(commands, query)
        )
        if picked is not None:
            run_command(commands, picked[0].key)

    def search_vault(self) -> None:
        """Ctrl+Shift+F: the file tree's search box, over the text of every note."""
        if not self.state.panes_open["left"]:
            self.toggle("left")
        if self.tree is not None:
            self.tree.show_search()

    async def _open_found(self, path: str, term: str) -> None:
        if self.editor_pane is not None:
            await self.editor_pane.open_found(path, term)

    def _reveal_in_tree(self, path: str) -> None:
        """A tab's "Show in file tree": unfold the tree (and its folders) and select the note."""
        if self.tree is None:
            return
        if not self.state.panes_open["left"]:
            self.toggle("left")
        self.tree.reveal(path)

    async def open_history(self, path: str | None = None) -> None:
        """Version history of ``path`` (default: the note on screen)."""
        pane = self.editor_pane
        path = path or (pane.active_note() if pane else None)
        if pane is None or path is None:
            return
        current = await pane.live_text(path)
        if current is None:
            return
        await HistoryDialog(
            self.history, self._popups, path, current, lambda t: pane.restore_version(path, t)
        ).open()

    async def open_trash(self) -> None:
        """The Trash popup: what was deleted, each with Restore."""
        await TrashDialog(Vault(self.vault), self._popups, self._restored).open()

    def _restored(self, path: str) -> None:
        self.bus.publish("vault.created", path=path)
        if self.tree is not None:
            self.tree.reveal(path)

    def show_calendar(self) -> None:
        if self.right is None or "calendar" not in self.right.tabs():
            return
        if not self.state.panes_open["right"]:
            self.toggle("right")
        self.right.show("calendar")

    def _recent_renamed(self, old: str, new: str) -> None:
        self.state.recent_notes = renamed(self.state.recent_notes, old, new)
        if self.editor_pane is not None:
            self.editor_pane.history_renamed(old, new)  # versions follow the note

    async def new_folder(self) -> None:
        if self.tree is not None:
            await self.tree.new_folder()

    async def new_note(self) -> None:
        if self.tree is not None:
            await self.tree.new_note()

    async def open_vault(self) -> None:
        """Pick another folder and open it as the vault (this window switches over)."""
        if self.host is None:
            return
        folder = await ask_vault(self.vault, native=self.can_reveal)
        if folder is None:
            return
        if self.editor_pane is not None and not await self.editor_pane.save_now():
            ui.notify("Some notes could not be saved; the vault was not switched.", type="negative")
            return
        self._save_now()  # this vault's tabs and layout, for when it is opened again
        try:
            self.host.switch(folder)
        except VaultError as exc:
            ui.notify(str(exc), type="negative")

    async def tidy_note(self) -> None:
        if self.editor_pane is not None:
            await self.editor_pane.tidy_active()

    def ask_ai(self) -> None:
        if not self.ai_on():
            return
        self._open_chat()
        if self.chat is not None:
            self.chat.focus_input()

    def _start_actions(self) -> None:
        """The buttons in the middle of the editor area while no note is open."""
        actions = (
            ("square-pen", "New note", "Ctrl + N", self.new_note),
            ("folder-plus", "New folder", "", self.new_folder),
            ("search", "Open note", "Ctrl + O", self.open_note),
            ("folder-open", "Open vault", "", self.open_vault),
            ("sparkles", "Ask AI", "", self.ask_ai),
        )
        if not self.ai_on():
            actions = actions[:-1]
        for icon, label, keys, action in actions:
            with (
                ui.button(on_click=action, color=None).props("flat no-caps").classes("pp-start-btn")
            ):
                line_icon(icon)
                ui.label(label)
                if keys:
                    ui.label(keys).classes("pp-start-keys")

    def _left_pane(self) -> None:
        with ui.column().classes("pp-pane pp-left"):
            with ui.row().classes("pp-left-top pp-dragzone items-center no-wrap"):
                icon_button(
                    "panel-left-close", lambda: self.toggle("left"), "Hide file tree (Ctrl+B)"
                )
                ui.label(f"paper-pile — {self.vault.name}").classes("pp-win-title")
            with ui.column().classes("pp-pane-body pp-left-body"):
                self.tree = FileTree(
                    Vault(self.vault),
                    self.bus,
                    can_reveal=self.can_reveal,
                    hidden=self._tree_hidden,
                    ai_on=self.ai_on,
                    search=self.index.search,
                    open_found=self._open_found,
                    open_trash=self.open_trash,
                    confirm_delete=lambda: bool(self._setting("general.confirm_delete")),
                    pinned=lambda: self.state.pinned,
                )
                self.tree.build()
                self.outline = OutlinePane(self._jump_to_line, self.toggle_outline)
                self.outline.build(
                    is_open=self.state.outline_open, height=self.state.outline_height
                )
            ui.on("pp_vsplit", lambda e: self._outline_resized(e.args))
            self.profile = ProfileBlock(
                self.config,
                open_settings=self.open_settings,
                on_changed=self._profile_changed,
                vault_name=self.vault.name,
                open_vault=self.open_vault,
                open_palette=self.open_palette,
            )
            self.profile.build()
        with self._ribbon_bottom:  # outline, settings + avatar stay reachable while folded
            icon_button("list-tree", self.toggle_outline, "Outline (Ctrl+Shift+O)")
            self.profile.build_mini()

    def _profile_changed(self) -> None:
        """The name or picture changed (the chat shows the name)."""
        if self.chat is not None:
            self.chat.refresh_names()

    # ---- settings, theme, profile -----------------------------------------------------------

    def ai_on(self) -> bool:
        return feature_on(self.config.values, "features.ai")

    def _right_features(self) -> set[str]:
        """The right pane's feature tabs that are switched on."""
        on = {"chat": self.ai_on(), "calendar": feature_on(self.config.values, "features.calendar")}
        return {name for name, is_on in on.items() if is_on}

    def _features_changed(self) -> None:
        """AI or Calendar was switched on or off: show or hide everything that belongs to it."""
        ai = self.ai_on()
        if self.right is not None:
            self.right.refresh()  # folds the pane if nothing is left to show (_right_emptied)
        if self._status is not None:
            self._status.show_ollama(ai)
        if self.editor_pane is not None:
            self.editor_pane.set_ai(ai)
            self.editor_pane.empty_host.clear()
            with self.editor_pane.empty_host:
                self._start_actions()
        if self.chat is not None and ai:
            self.chat.reload_provider()  # checks Ollama again
        if self.tree is not None:
            self.tree.refresh()
        self._sync_toggles()

    def _right_emptied(self) -> None:
        """The right pane's last tab closed (Settings, with AI and Calendar off): fold it. Runs
        in the splitter's context: the click that got here came from a tab that is gone now."""
        with self._splitters["right"]:
            if self.state.panes_open["right"]:
                self.toggle("right")
            else:
                self._sync_toggles()

    def _known_models(self) -> list[str]:
        return list(self.chat.models) if self.chat else []

    def open_settings(self, page: str | None = None) -> None:
        """Settings is a tab of the right pane: open the pane if it is folded away, then the tab
        (on section ``page`` if given)."""
        if not self.state.panes_open["right"]:
            self.toggle("right")
        if self.right is not None:
            self.right.open_settings(page)

    def _settings_wide_mode(self, wide: bool) -> None:
        """Settings has two columns: widen the right pane while it shows, then put it back."""
        splitter = self._splitters.get("right")
        if splitter is None or wide == self._settings_wide:
            return
        self._settings_wide = wide
        if wide:
            widths = self.state.pane_widths
            widths["settings"] = max(widths["settings"], SETTINGS_OPEN_MIN)
        if self.state.panes_open["right"]:
            self._apply("right")

    def _refresh_calendar(self) -> None:
        if self.calendar is not None:
            self.calendar.refresh()

    def _open_daily(self, day: date) -> None:
        """A click on a calendar day: open that day's note, creating it from the template."""
        vault = Vault(self.vault)
        folder = str(self.config.get("vault.daily_notes_folder", ""))
        fmt = str(self.config.get("vault.daily_notes_format", DEFAULT_FORMAT))
        path = daily_relpath(day, folder, fmt)
        template = str(self.config.get("vault.daily_notes_template", ""))
        now = datetime.now()
        if not vault.exists(path):
            text = new_daily_text(vault, template, day, now, fmt)
            try:
                vault.create_note(path, text)
            except VaultError as exc:
                ui.notify(str(exc), type="negative")
                return
            self.bus.publish("vault.created", path=path)
        else:
            self._remake_daily(vault, path, template, day, now, fmt)
        self.bus.publish("tree.open", path=path)

    def _remake_daily(
        self, vault: Vault, path: str, template: str, day: date, now: datetime, fmt: str
    ) -> None:
        """A day's note the user never wrote in (only the app's heading or an older template,
        maybe with an auto-added title) is made again from the current template. Not while it
        is open in a tab; the old text goes to the trash first."""
        if not template.strip() or (self.editor_pane and self.editor_pane.tabs.find(path)):
            return
        try:
            text = vault.read_text(path)
            fresh = new_daily_text(vault, template, day, now, fmt)
            if text == fresh or not untouched_daily(text, vault, template, day, now, fmt):
                return
            vault.stash_text(path, text, "before template")
            vault.write_text(path, fresh)
        except VaultError:
            log.exception("could not apply the daily template to %s", path)

    def _tree_hidden(self) -> set[str]:
        """Folders the file tree leaves out: images and memories always, daily notes and
        templates unless their switch is on (Settings → General → Folders)."""
        values = sanitized(self.config.values)
        hidden = {".image", ".memory", str(values["vault.images_folder"]).strip("/")}
        for key, switch in (
            ("vault.daily_notes_folder", "vault.show_daily_notes"),
            ("vault.templates_folder", "vault.show_templates"),
        ):
            if not values[switch]:
                hidden.add(str(values[key]).strip("/"))
        return hidden - {""}

    async def _open_gallery(self) -> None:
        """Settings → General → Folders → Images → Gallery."""
        gallery = Gallery(
            Vault(self.vault),
            self.config,
            open_note=lambda path: self.bus.publish("tree.open", path=path),
            insert_text=self._insert_text,
            active_note=self._active_path,
        )
        await gallery.open()

    def _insert_text(self, text: str) -> None:
        if self.editor_pane is not None:
            self.editor_pane.insert_text(text)

    def _folder_cleared(self, key: str) -> None:
        if key == "ai.chats_folder" and self.chat is not None:
            self.chat.chats_deleted({self.chat.chat_id})
        if self.tree is not None:
            self.tree.refresh()
        self._refresh_calendar()

    def _chats_dir(self) -> Path:
        return chats_folder(self.vault, str(self.config.get("ai.chats_folder", "") or ""))

    async def _draft_instruction(self, kind: str, brief: str) -> AsyncIterator[str]:
        """Settings → Write with AI: the model drafts a system instruction or a template."""
        ask = template_draft_messages if kind == "template" else draft_messages
        async for piece in self.ai.stream(ask(brief, self.ai.language())):
            yield piece

    def _open_new_note(self, path: str) -> None:
        """A note was written outside the editor (a memory saved as a note): show and open it."""
        self.bus.publish("vault.created", path=path)
        self.bus.publish("tree.open", path=path)

    def _close_settings(self) -> None:
        if self.right is not None:
            self.right.close_settings()

    def _on_dark(self, dark: bool) -> None:
        """The page reports whether it is dark now: the editor (and its diagrams) follow."""
        if self.editor_pane is not None:
            self.editor_pane.set_theme("dark" if dark else "light")

    def _remember_page_style(self) -> None:
        """The ⋯ menu turns page view on in the style used last."""
        style = sanitized(self.config.values)["editor.page_view"]
        if style != "off" and self.config.get("editor.page_view_last") != style:
            self.config.set("editor.page_view_last", style)
            try:
                self.config.save()
            except OSError:
                log.exception("could not save the settings")

    def _settings_changed_elsewhere(self, changed: set[str]) -> None:
        """A setting changed outside the settings pane (the ⋯ menu): apply it, and let the
        pane show it if it is open."""
        self._settings_applied(changed)
        self.settings.refresh()

    def _settings_applied(self, changed: set[str]) -> None:
        """Settings were saved: show what can be shown right away."""
        if "editor.page_view" in changed:
            self._remember_page_style()
        look = ("appearance.", "editor.font_", "editor.code_font", "editor.line_height")
        if any(k.startswith(look) for k in changed):
            self.theme.apply()
        if self.editor_pane is not None and EDITOR_OPTION_KEYS & changed:
            self.editor_pane.set_options(editor_options(self.config))
        if self._status is not None and "editor.word_count" in changed:
            self._status.stats_label.set_visibility(bool(self._setting("editor.word_count")))
        if self.editor_pane is not None and "editor.tidy_button" in changed:
            self.editor_pane.show_tidy_buttons()
        if self.editor_pane is not None and "editor.last_edited" in changed:
            self.editor_pane.show_edited()
        if changed & {"features.ai", "features.calendar"}:
            self._features_changed()
        elif self.chat is not None and any(k.startswith("ai.") for k in changed):
            self.ai.access_changed()  # the memories folder is never read
            self.chat.reload_provider()
        if self.profile is not None:
            self.profile.refresh()
        if any(k.startswith("vault.daily_notes") for k in changed):
            self._refresh_calendar()
        tree_keys = {"vault.show_daily_notes", "vault.show_templates", "vault.images_folder"}
        if self.tree is not None and changed & (tree_keys | {"vault.daily_notes_folder"}):
            self.tree.refresh()

    def _right_pane(self) -> None:
        self.right = RightPane(
            self.settings.open,
            self._settings_wide_mode,
            self._refresh_calendar,
            features=self._right_features,
            on_empty=self._right_emptied,
        )
        self.right.build()
        with self.right.chat_host:
            self._chat_pane()
        self.calendar = CalendarPane(
            Vault(self.vault),
            self.config,
            self._open_daily,
            active_path=self._active_path,
            open_settings=self.open_settings,
        )
        with self.right.calendar_host:
            self.calendar.build()
        assert self.editor_pane is not None
        self.tags = TagPane(self.index, self.editor_pane.open, self.editor_pane.open_in_split)
        with self.right.tag_host:
            self.tags.build()

    def _chat_pane(self) -> None:
        assert self.editor_pane is not None
        self.chat = ChatPane(
            self.ai,
            snapshot=self.editor_pane.ai_snapshot,
            insert_text=self.editor_pane.insert_text,
            on_health=self._on_ollama_health,
            user_name=lambda: self.profile.name if self.profile else "",
            open_paths=lambda: self.editor_pane.open_paths() if self.editor_pane else [],
            active_path=self._active_path,
            open_settings=lambda: self.open_settings("AI"),
            enabled=self.ai_on,
            apply_to_note=self._apply_to_note,
        )
        self.chat.build()

    async def _apply_to_note(self, path: str, old: str, new: str) -> None:
        """A chat answer replaces the text it was asked about: shown as a diff in that note."""
        if self.editor_pane is not None:
            await self.editor_pane.propose_in_note(path, old, new)

    def _on_ollama_health(self, health: Health) -> None:
        if self._status is not None:
            tip = "Ollama is running" if health.ok and not health.message else health.message
            self._status.set_ollama(health.ok, tip or "Ollama")

    def _center_pane(self) -> None:
        self.editor_pane = EditorPane(
            Vault(self.vault),
            self.bus,
            self._set_save_state,
            self._on_tabs_changed,
            mode=self.state.mode,
            on_mode_changed=self._on_mode_changed,
            native=self.can_reveal,  # native window = this machine
            on_plain_changed=self._on_plain_changed,
            index=self.index,
            history=self.history,
            config=self.config,
            get_recents=lambda: self.state.recent_commands,
            on_settings_changed=self._settings_changed_elsewhere,
            ai=self.ai,
            on_command_used=self._on_command_used,
            selection_changed=self._chat_selection,
            add_note_to_chat=self._chat_add_note,
            ask_chat=self._chat_ask,
            ask_selection=self._chat_ask_selection,
            open_tag=self.open_tag,
            on_stats=self._set_stats,
            block_to_chat=self._chat_block,
            on_toggle_pane=self.toggle,
            on_outline=self.toggle_outline,
            on_history=self.open_history,
            pinned=self.state.pinned,
            on_pins_changed=self._pins_changed,
        )
        self.editor_pane.build()
        with self.editor_pane.empty_host:
            self._start_actions()
        with self.editor_pane.status_host:  # the footer under the editor, beside Backlinks
            self._status = status_bar(self.toggle_mode, self.state.mode)
            self._status.show_ollama(self.ai_on())
        self.editor_pane.set_ai(self.ai_on())

    def _pins_changed(self, paths: list[str]) -> None:
        self.state.pinned = paths
        self._save_soon(immediately=True)
        if self.tree is not None:
            self.tree.refresh()

    def _chat_selection(self, text: str, path: str) -> None:
        """A selection settled: attached by itself unless Settings says "With Ask"."""
        if self.config.get("ai.selection_to_chat", "auto") == "button":
            return
        if self.chat is not None and self.ai_on():
            self.chat.set_selection(text, path)

    def _chat_ask_selection(self, text: str, path: str) -> None:
        """The selection bar's Ask: attach it and put the caret in the chat box."""
        if self.chat is None or not self.ai_on() or not text.strip():
            return
        self.chat.set_selection(text, path)
        self._open_chat()
        self.chat.focus_input()

    def _chat_block(self, kind: str, lang: str, text: str, path: str) -> None:
        if self.chat is not None and self.ai_on():
            self.chat.set_block(kind, lang, text, path)

    def _active_path(self) -> str | None:
        tab = self.editor_pane.tabs.active_tab if self.editor_pane else None
        return tab.path if tab else None

    def _chat_add_note(self, path: str) -> None:
        if self.chat is not None and self.ai_on():
            self.chat.add_notes([path])
            self._open_chat()
            self.chat.focus_input()  # ready for the question about it

    def _chat_ask(self, path: str, prompt: str, send: bool) -> None:
        if self.chat is not None and self.ai_on():
            self._open_chat()
            self.chat.ask(path, prompt, send=send)

    def open_tag(self, tag: str) -> None:
        """A tag chip was clicked: list its notes in the right pane."""
        if not tag or self.right is None or self.tags is None:
            return
        if not self.state.panes_open["right"]:
            self.toggle("right")
        self.tags.show(tag)
        self.right.open_tag(tag.lstrip("#"))  # the tab's icon is already a #

    def _open_chat(self) -> None:
        if not self.state.panes_open["right"]:
            self.toggle("right")
        if self.right is not None:
            self.right.show("chat")

    def _on_command_used(self, command_id: str) -> None:
        self.state.recent_commands = push_recent(self.state.recent_commands, command_id)
        self._save_soon()

    def _on_tabs_changed(self, paths: list[str], active: str | None) -> None:
        self.state.tabs = paths
        self.state.active = active
        self._update_outline()
        if active is not None:
            self.state.recent_notes = push_recent(self.state.recent_notes, active, MAX_RECENT_NOTES)
        self._save_soon()  # debounced: a tab switch must not wait for a file write + fsync
        self._refresh_calendar()

    def _on_mode_changed(self, mode: str) -> None:
        self.state.mode = mode  # type: ignore[assignment]
        self._save_soon(immediately=True)
        if self._status is not None:
            self._status.set_mode(mode, self._plain)

    def _on_plain_changed(self, plain: bool) -> None:
        self._plain = plain
        if self._status is not None:
            self._status.set_mode(self.state.mode, plain)

    def toggle_mode(self) -> None:
        if self.editor_pane is not None:
            self.editor_pane.toggle_mode()

    def open_today(self) -> None:
        """The palette's Open today's daily note (created from the template if needed)."""
        self._open_daily(date.today())

    def new_chat(self) -> None:
        """The palette's New chat: an empty chat, shown."""
        if self.chat is None:
            return
        self.chat.new_chat()
        self.ask_ai()

    async def rebuild_index_now(self) -> None:
        """The palette's Rebuild search index, with a message when done."""
        count = await self._rebuild_index()
        ui.notify(f"Index rebuilt: {count} notes", timeout=2000, position="bottom")

    async def _rebuild_index(self) -> int:
        """Settings → Advanced: index the whole vault again (a cache; the files are the truth)."""
        result = await run.io_bound(self.index.rebuild)
        return result.added

    def _setting(self, key: str) -> Any:
        """One validated setting value (its default when unset or invalid)."""
        return sanitized(self.config.values)[key]

    def _set_stats(self, words: int | None, line: int, col: int, shown: int) -> None:
        """``line``: the real line (outline); ``shown``: counted after the properties block."""
        if self._status is not None:
            self._status.stats_label.set_visibility(bool(self._setting("editor.word_count")))
            self._status.set_stats(words, shown, col)
        self._caret_line = line
        self._update_outline()

    def toggle_outline(self) -> None:
        """Ctrl+Shift+O / ⋯ / its header: open the Outline section under the file tree (unfolding
        the tree if it is folded away), or fold the section if it is open."""
        if not self.state.panes_open["left"]:
            self.toggle("left")
            if self.state.outline_open:
                return  # it was open behind the folded pane: showing it is enough
        self.state.outline_open = not self.state.outline_open
        if self.outline is not None:
            self.outline.set_open(self.state.outline_open, self.state.outline_height)
        self._save_soon(immediately=True)
        self._update_outline()

    def _outline_resized(self, args: dict[str, object]) -> None:
        height = args.get("height")
        if args.get("name") == "outline" and isinstance(height, int | float) and height > 0:
            self.state.outline_height = int(height)
            if self.outline is not None:
                self.outline.set_open(self.state.outline_open, self.state.outline_height)
            self._save_soon()

    def _jump_to_line(self, line: int) -> None:
        if self.editor_pane is not None:
            self.editor_pane.goto_line(line)

    def _update_outline(self) -> None:
        if self.outline is None or not self.state.outline_open:
            return
        text = self.editor_pane.active_text() if self.editor_pane else None
        self.outline.show(text, self._caret_line)

    def _set_save_state(self, text: str, error: bool, hint: str = "") -> None:
        if self._status is not None:
            self._status.set_save_state(text, error=error, hint=hint)
        if self.tags is not None and self.tags.tag:
            self.tags.refresh()  # a save may have added or removed the tag (redraws only on change)

    # ---- behaviour -----------------------------------------------------------------------

    def toggle(self, pane: str) -> None:
        if pane == "left" and self._settings_wide and self.state.panes_open["right"]:
            background_tasks.create(self._toggle_left_keeping_settings())
            return
        opening = not self.state.panes_open[pane]
        if pane == "right" and opening and self.right is not None and not self.right.has_tabs():
            return  # AI and Calendar are off and nothing else is open there
        self.state.panes_open[pane] = opening
        self._apply(pane)
        self._save_soon(immediately=True)

    async def _toggle_left_keeping_settings(self) -> None:
        """Fold / unfold the file tree while Settings is open without Settings changing width:
        the width it really has on screen (narrower than wanted in a small window) is kept,
        and the editor takes or gives the room. Without this it grows on folding and shrinks
        on unfolding, and its layout flickers between its wide and narrow forms."""
        splitter = self._splitters["right"]
        try:
            shown = await splitter.client.run_javascript(
                "document.querySelector('.pp-panesplit-right > .q-splitter__after')"
                "?.getBoundingClientRect().width || 0"
            )
        except TimeoutError:
            shown = 0
        width = round(float(shown or 0))
        if width > 0 and width < self.state.pane_widths["settings"]:
            self.state.pane_widths["settings"] = clamp_width("settings", width)
            self._apply("right")
        self.state.panes_open["left"] = not self.state.panes_open["left"]
        self._apply("left")
        self._save_soon(immediately=True)

    def close_tab(self) -> None:
        if self.editor_pane is not None:
            self.editor_pane.close_active()

    def cycle_tabs(self, step: int) -> None:
        if self.editor_pane is not None:
            self.editor_pane.cycle(step)

    def _apply(self, pane: str) -> None:
        splitter = self._splitters[pane]
        if pane == "right":  # window buttons reserve room at the right-most tab row
            ui.query("body").classes(
                add="pp-right-open" if self.state.panes_open[pane] else "",
                remove="" if self.state.panes_open[pane] else "pp-right-open",
            )
        if self.state.panes_open[pane]:
            key = "settings" if pane == "right" and self._settings_wide else pane
            splitter.set_limits(*(SETTINGS_LIMITS if key == "settings" else WIDTH_LIMITS[pane]))
            splitter.value = self.state.pane_widths[key]
            splitter.props(remove="disable")
        else:
            splitter.set_limits(0, 0)
            splitter.value = 0
            splitter.props("disable")
        self._sync_toggles()

    def _sync_toggles(self) -> None:
        self._ribbon.set_visibility(not self.state.panes_open["left"])
        if self.editor_pane is None:
            return
        tabs = self.right.tabs() if self.right is not None else ["chat"]
        name = {"chat": "AI chat", "calendar": "calendar"}.get(tabs[0] if tabs else "", "side pane")
        for pane, button in self.editor_pane.pane_toggles.items():
            # the icon shows what a click does: close an open pane, open a closed one
            is_open = self.state.panes_open[pane]
            set_icon(button, f"panel-{pane}-{'close' if is_open else 'open'}")
            tip(button, f"{'Hide' if is_open else 'Show'} {name} (Ctrl+L)")
            button.set_visibility(is_open or bool(tabs))

    def _dragged_shut(self, pane: str) -> None:
        """The pane's edge was dragged on past its narrowest width (``static/panes.js``). Not
        while the right pane shows Settings: there the drag only resizes."""
        if pane == "right" and self._settings_wide:
            return
        if pane in self.state.panes_open and self.state.panes_open[pane]:
            self.toggle(pane)

    def _edge_double_clicked(self, pane: str) -> None:
        """A double-click on a pane's edge folds the pane, or unfolds it (``static/panes.js``)."""
        if pane in self.state.panes_open:
            self.toggle(pane)

    def _on_resize(self, pane: str, value: float | None) -> None:
        # Programmatic changes (collapse/restore) also land here; only an open pane's width counts.
        if value is None or not self.state.panes_open[pane] or value <= 0:
            return
        key = "settings" if pane == "right" and self._settings_wide else pane  # remembered apart
        width = clamp_width(key, round(value))
        if width != self.state.pane_widths[key]:
            self.state.pane_widths[key] = width
            self._save_soon()

    def _save_soon(self, *, immediately: bool = False) -> None:
        if self._save_handle is not None:
            self._save_handle.cancel()
            self._save_handle = None
        if immediately:
            self._save_now()
            return
        self._save_handle = asyncio.get_running_loop().call_later(SAVE_DELAY_S, self._save_now)

    def _save_now(self) -> None:
        self._save_handle = None
        save_session(self.vault, self.state)

    def _flush_save(self) -> None:
        if self._save_handle is not None:
            self._save_handle.cancel()
            self._save_now()
