"""Bottom of the left pane: your avatar and name, and a box of three buttons (like the
Light / Dark switch): open vault, command palette, settings."""

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
from paper_pile.gui.icons import ico, icon_button
from paper_pile.gui.tips import tip

log = logging.getLogger("paper_pile.profile")


class ProfileBlock:
    def __init__(
        self,
        config: Config,
        open_settings: Callable[[], None],
        on_changed: Callable[[], None] = lambda: None,
        vault_name: str = "",
        open_vault: Callable[[], object] = lambda: None,
        open_palette: Callable[[], None] = lambda: None,
    ) -> None:
        self._vault_name = vault_name
        self._open_vault = open_vault
        self._open_palette = open_palette
        self.config = config
        self._open_settings = open_settings
        self._on_changed = on_changed
        self._avatars: list[ui.element] = []  # the block's, and the folded pane's
        self._name: ui.label

    @property
    def name(self) -> str:
        return str(self.config.get("profile.name", "")).strip()

    def build(self) -> None:
        with ui.row().classes("pp-profile items-center no-wrap"):
            with ui.row().classes("pp-profile-who items-center no-wrap") as who:
                self._avatars.append(ui.element("div").classes("pp-avatar"))
                self._name = ui.label("").classes("pp-profile-name")
            who.on("click", lambda _e: self._open_dialog())
            ui.space()
            self._tools("row")
        self.refresh()

    def _tools(self, direction: str) -> None:
        """Open vault, command palette, settings, in one box (a row, or a column on the rail)."""
        with ui.element("div").classes(f"pp-seg pp-tools pp-tools-{direction}"):
            icon_button("folder-open", self._open_vault, "Open vault", size="m")
            icon_button("command", self._open_palette, "Command palette (Ctrl+P)", size="m")
            icon_button("settings", self._open_settings, "Settings (Ctrl+,)", size="m")

    def build_mini(self) -> None:
        """The folded-pane version: the same box, standing, above the avatar."""
        self._tools("column")
        with ui.element("div").classes("pp-ribbon-foot"):  # level with the footer and profile row
            avatar = ui.element("div").classes("pp-avatar pp-avatar-mini")
        avatar.on("click", lambda _e: self._open_dialog())
        tip(avatar, "Profile")
        self._avatars.append(avatar)
        self.refresh()

    def refresh(self) -> None:
        """Show the current name and picture."""
        name = self.name
        self._name.set_text(name or self._vault_name or "Set your name")
        self._name.classes(
            add="pp-muted" if not name else "", remove="" if not name else "pp-muted"
        )
        picture = avatar_path(str(self.config.get("profile.avatar", "")))
        for avatar in self._avatars:
            avatar.clear()
            if picture is not None:
                stamp = int(picture.stat().st_mtime)
                url = f"/_pp/avatar?name={picture.name}&v={stamp}"
                avatar.style(f"background-image:url('{url}')")
            else:
                avatar.style("background-image:none")
                with avatar:
                    ui.label(initials(name)).classes("pp-avatar-initials")

    # ---- the profile dialog ----------------------------------------------------------------

    def _open_dialog(self) -> None:
        """Name and picture. The picture is chosen with a plain button (the uploader itself is
        hidden: Quasar's upload box does not follow the theme)."""
        with ui.dialog() as dialog, ui.card().classes("pp-dialog pp-profile-dialog"):
            ui.label("Profile").classes("pp-dialog-title")
            ui.label("Stored only on this computer.").classes("pp-muted")
            name = (
                ui.input("Name", value=self.name)
                .props("outlined dense autofocus")
                .classes("w-full")
            )
            with ui.row().classes("pp-profile-pic items-center no-wrap"):
                preview = ui.element("div").classes("pp-avatar pp-avatar-big")
                with ui.column().classes("pp-profile-pic-side"):
                    ui.label("Picture").classes("pp-set-label")
                    with ui.row().classes("items-center no-wrap pp-profile-pic-buttons"):
                        ui.button(
                            "Choose…",
                            icon=ico("image-up"),
                            on_click=lambda: upload.run_method("pickFiles"),
                            color=None,
                        ).props("flat no-caps dense").classes("pp-btn-outline")
                        ui.button(
                            "Remove", icon=ico("trash-2"), on_click=self._remove, color=None
                        ).props("flat no-caps dense").classes("pp-btn-quiet")
                    ui.label("PNG, JPEG, GIF or WebP, up to 2 MB").classes("pp-muted")
            upload = ui.upload(
                on_upload=self._uploaded,
                auto_upload=True,
                max_file_size=2 * 1024 * 1024,
                on_rejected=lambda: ui.notify("The picture must be at most 2 MB.", type="negative"),
            ).props("accept=image/png,image/jpeg,image/gif,image/webp")
            upload.classes("hidden")
            with ui.row().classes("justify-end w-full"):
                ui.button("Cancel", on_click=dialog.close).props("flat no-caps")
                ui.button("Save", on_click=lambda: self._save_name(name.value, dialog)).props(
                    "no-caps unelevated"
                )
        self._avatars.append(preview)  # the preview follows changes like the other avatars
        self.refresh()
        dialog.on(
            "hide", lambda _e: self._avatars.remove(preview) if preview in self._avatars else None
        )
        dialog.open()

    def _save_name(self, value: str, dialog: ui.dialog) -> None:
        clean = " ".join((value or "").split())[:60]
        self.config.set("profile.name", clean, "global")
        self.config.save("global")
        dialog.close()
        self.refresh()
        self._on_changed()

    async def _uploaded(self, e: events.UploadEventArguments) -> None:
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

    def _remove(self) -> None:
        remove_avatar(profile_dir())
        self.config.set("profile.avatar", "", "global")
        self.config.save("global")
        self.refresh()
        self._on_changed()
