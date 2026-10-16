"""Bottom of the left pane: your avatar and name, the settings button and the theme switch."""

import logging
from collections.abc import Callable

from nicegui import events, ui

from paper_pile.core.config import Config
from paper_pile.core.profile import (
    AvatarError,
    avatar_path,
    initials,
    profile_dir,
    remove_avatar,
    save_avatar,
)

log = logging.getLogger("paper_pile.profile")


class ProfileBlock:
    def __init__(
        self,
        config: Config,
        open_settings: Callable[[], None],
        toggle_theme: Callable[[], None],
        on_changed: Callable[[], None] = lambda: None,
    ) -> None:
        self.config = config
        self._open_settings = open_settings
        self._toggle_theme = toggle_theme
        self._on_changed = on_changed
        self._avatar: ui.element
        self._name: ui.label
        self._theme_button: ui.button

    @property
    def name(self) -> str:
        return str(self.config.get("profile.name", "")).strip()

    def build(self) -> None:
        with ui.row().classes("pp-profile items-center no-wrap"):
            with ui.row().classes("pp-profile-who items-center no-wrap") as who:
                self._avatar = ui.element("div").classes("pp-avatar")
                self._name = ui.label("").classes("pp-profile-name")
            who.on("click", lambda _e: self._open_dialog())
            ui.space()
            self._theme_button = ui.button(icon="fa-regular fa-moon", on_click=self._toggle_theme)
            self._theme_button.props("flat round dense size=sm").classes("pp-profile-btn")
            self._theme_button.tooltip("Light / dark")
            settings = ui.button(icon="fa-solid fa-gear", on_click=self._open_settings)
            settings.props("flat round dense size=sm").classes("pp-profile-btn")
            settings.tooltip("Settings (Ctrl+,)")
        self.refresh()

    def refresh(self) -> None:
        """Show the current name and picture."""
        name = self.name
        self._name.set_text(name or "Set your name")
        self._name.classes(
            add="pp-muted" if not name else "", remove="" if not name else "pp-muted"
        )
        picture = avatar_path(str(self.config.get("profile.avatar", "")))
        self._avatar.clear()
        if picture is not None:
            stamp = int(picture.stat().st_mtime)
            url = f"/_pp/avatar?name={picture.name}&v={stamp}"
            self._avatar.style(f"background-image:url('{url}')")
        else:
            self._avatar.style("background-image:none")
            with self._avatar:
                ui.label(initials(name)).classes("pp-avatar-initials")

    def show_dark(self, dark: bool) -> None:
        icon = "fa-regular fa-sun" if dark else "fa-regular fa-moon"
        self._theme_button.props(f'icon="{icon}"')  # quoted: the name contains a space

    # ---- the profile dialog ----------------------------------------------------------------

    def _open_dialog(self) -> None:
        with ui.dialog() as dialog, ui.card().classes("pp-dialog pp-profile-dialog"):
            ui.label("Profile").classes("pp-dialog-title")
            ui.label("Stored only on this computer.").classes("pp-muted")
            name = (
                ui.input("Name", value=self.name)
                .props("outlined dense autofocus")
                .classes("w-full")
            )
            ui.label("Picture").classes("pp-set-label")
            ui.upload(
                on_upload=lambda e: self._uploaded(e, dialog),
                auto_upload=True,
                max_file_size=2 * 1024 * 1024,
                on_rejected=lambda: ui.notify("The picture must be at most 2 MB.", type="negative"),
            ).props("accept=image/png,image/jpeg,image/gif,image/webp flat bordered").classes(
                "w-full"
            )
            with ui.row().classes("justify-between w-full"):
                ui.button("Remove picture", on_click=lambda: self._remove(dialog)).props(
                    "flat no-caps size=sm"
                )
                with ui.row():
                    ui.button("Cancel", on_click=dialog.close).props("flat no-caps")
                    ui.button("Save", on_click=lambda: self._save_name(name.value, dialog)).props(
                        "no-caps"
                    )
        dialog.open()

    def _save_name(self, value: str, dialog: ui.dialog) -> None:
        clean = " ".join((value or "").split())[:60]
        self.config.set("profile.name", clean, "global")
        self.config.save("global")
        dialog.close()
        self.refresh()
        self._on_changed()

    async def _uploaded(self, e: events.UploadEventArguments, dialog: ui.dialog) -> None:
        try:
            name = save_avatar(await e.file.read())
        except AvatarError as exc:
            ui.notify(str(exc), type="negative")
            return
        self.config.set("profile.avatar", name, "global")
        self.config.save("global")
        self.refresh()
        self._on_changed()
        ui.notify("Picture updated", timeout=1500, position="bottom")

    def _remove(self, dialog: ui.dialog) -> None:
        remove_avatar(profile_dir())
        self.config.set("profile.avatar", "", "global")
        self.config.save("global")
        dialog.close()
        self.refresh()
        self._on_changed()
