"""The image gallery (PLAN §6 P13.7): every image of the vault in a popup, grouped by day.

A toolbar filters (a note's name; all / used / unused), sorts (newest / oldest day first) and
sizes the thumbnails (S / M / L). Clicking a picture shows it large beside the grid (that
column can be widened) with its
name, size, dimensions, date and the notes that show it (a click opens one), plus *Copy
markdown*, *Insert into note* and *Move to trash* (warns when notes still show it). The data
comes from :mod:`paper_pile.core.gallery`.
"""

import html
import json
import logging
from collections.abc import Callable
from urllib.parse import quote

from nicegui import run, ui

from paper_pile.core.assets import encode_ref, image_markdown
from paper_pile.core.config import Config
from paper_pile.core.gallery import ImageInfo, group_by_day, list_images, trash_image
from paper_pile.core.settings import sanitized
from paper_pile.core.vault import Vault, VaultError
from paper_pile.gui.icons import icon_button, line_icon
from paper_pile.gui.tips import tip

log = logging.getLogger("paper_pile.gallery")

SIZES = {"S": 96, "M": 148, "L": 220}  # thumbnail edge in px
FILTERS = ("All", "Used", "Unused")
SORTS = ("Newest", "Oldest")


def image_url(path: str) -> str:
    """The app's URL of a vault image (``/_pp/asset`` reads it as seen from the vault root)."""
    return f"/_pp/asset?note=_.md&path={quote(path, safe='')}"


def _relative_ref(image: str, note: str | None) -> str:
    """How ``note`` (or the vault root) refers to ``image``: a relative, encoded path."""
    import posixpath

    folder = posixpath.dirname(note) if note else ""
    rel = posixpath.relpath(image, folder or ".")
    head, _, name = rel.rpartition("/")
    return encode_ref(head, name) if head else quote(name)


def _bytes(n: int) -> str:
    for unit in ("B", "KB", "MB"):
        if n < 1024 or unit == "MB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024  # type: ignore[assignment]
    return f"{n} B"


class Gallery:
    def __init__(
        self,
        vault: Vault,
        config: Config,
        open_note: Callable[[str], None],
        insert_text: Callable[[str], None],
        active_note: Callable[[], str | None],
    ) -> None:
        self.vault = vault
        self.config = config
        self._open_note = open_note
        self._insert = insert_text
        self._active = active_note
        # the toolbar's choices are kept while the app runs
        self.size, self.filter, self.sort, self.query = "M", "All", "Newest", ""
        self._images: list[ImageInfo] = []
        self._picked: ImageInfo | None = None
        self._wide = False  # the details column takes most of the popup
        self._dialog: ui.dialog
        self._grid: ui.column
        self._side: ui.column
        self._count: ui.label

    # ---- building --------------------------------------------------------------------------

    async def open(self) -> None:
        with ui.dialog() as self._dialog, ui.card().classes("pp-dialog pp-gallery"):
            with ui.row().classes("pp-gal-bar items-center no-wrap w-full"):
                ui.label("Images").classes("pp-dialog-title")
                self._count = ui.label("").classes("pp-muted pp-gal-count")
                ui.space()
                search = ui.input(placeholder="Filter by note", value=self.query)
                search.props("dense outlined clearable").classes("pp-gal-search")
                with search.add_slot("prepend"):
                    line_icon("search", "s")
                search.on_value_change(lambda e: self._set("query", (e.value or "").strip()))
                self._choice(FILTERS, "filter")
                self._choice(SORTS, "sort")
                self._choice(tuple(SIZES), "size")
                icon_button("x", self._dialog.close, "Close")
            with ui.row().classes("pp-gal-body no-wrap w-full"):
                self._grid = ui.column().classes("pp-gal-grid")
                self._side = ui.column().classes("pp-gal-side")
            self._side.set_visibility(False)
        self._dialog.on("hide", lambda _e: self._dialog.delete())
        self._dialog.open()
        with self._grid:
            ui.label("Loading…").classes("pp-muted")
        await self.reload()

    def _choice(self, options: tuple[str, ...], attr: str) -> None:
        """A small segmented control bound to one toolbar attribute."""
        items: dict[str, ui.element] = {}

        def pick(value: str) -> None:
            for key, el in items.items():
                if key == value:
                    el.classes("pp-seg-on")
                else:
                    el.classes(remove="pp-seg-on")
            self._set(attr, value)

        with ui.row().classes("pp-seg no-wrap"):
            for option in options:
                item = ui.row().classes("pp-seg-item items-center no-wrap")
                if option == getattr(self, attr):
                    item.classes("pp-seg-on")
                with item:
                    ui.label(option)
                item.on("click", lambda _e, o=option: pick(o))
                items[option] = item

    def _set(self, attr: str, value: str) -> None:
        setattr(self, attr, value)
        self._render()

    async def reload(self) -> None:
        folder = str(sanitized(self.config.values)["vault.images_folder"])
        self._images = await run.io_bound(list_images, self.vault, folder)
        if self._picked is not None:
            self._picked = next((i for i in self._images if i.path == self._picked.path), None)
        self._render()
        self._render_side()

    # ---- the grid --------------------------------------------------------------------------

    def _shown(self) -> list[ImageInfo]:
        words = self.query.lower().split()
        out = []
        for info in self._images:
            if self.filter == "Used" and not info.used_by:
                continue
            if self.filter == "Unused" and info.used_by:
                continue
            if words and not any(all(w in n.lower() for w in words) for n in info.used_by):
                continue
            out.append(info)
        return out

    def _render(self) -> None:
        if self._grid.is_deleted:
            return
        shown = self._shown()
        total = len(self._images)
        self._count.set_text(f"{len(shown)} of {total}" if len(shown) != total else f"{total}")
        edge = SIZES[self.size]
        self._grid.clear()
        with self._grid:
            if not shown:
                text = "No images match." if total else "No images in this vault yet."
                ui.label(text).classes("pp-muted pp-gal-empty")
            for day, images in group_by_day(shown, self.sort == "Newest"):
                n = len(images)
                heading = f"{day:%A, %b %d, %Y}".replace(" 0", " ")
                ui.label(f"{heading} · {n} image{'s' * (n != 1)}").classes("pp-gal-day")
                with ui.element("div").classes("pp-gal-tiles").style(f"--pp-gal-edge:{edge}px"):
                    for info in images:
                        self._tile(info)

    def _tile(self, info: ImageInfo) -> None:
        tile = ui.element("div").classes("pp-gal-tile")
        if self._picked is not None and info.path == self._picked.path:
            tile.classes("pp-gal-tile-on")
        if not info.used_by:
            tile.classes("pp-gal-unused")
        with tile:
            ui.html(
                f'<img src="{html.escape(image_url(info.path))}" loading="lazy" '
                f'alt="{html.escape(info.name)}">',
                sanitize=False,
            ).classes("pp-gal-img")
            ui.label(info.name).classes("pp-gal-name")
        tip(tile, info.path)
        tile.on("click", lambda _e, i=info: self._pick(i))

    def _pick(self, info: ImageInfo) -> None:
        self._picked = None if self._picked is not None and self._picked.path == info.path else info
        self._render()
        self._render_side()

    # ---- one image -------------------------------------------------------------------------

    def _toggle_wide(self) -> None:
        self._wide = not self._wide
        self._render_side()

    def _render_side(self) -> None:
        if self._side.is_deleted:
            return
        info = self._picked
        self._side.set_visibility(info is not None)
        if self._wide:
            self._side.classes("pp-gal-side-wide")
        else:
            self._side.classes(remove="pp-gal-side-wide")
        self._side.clear()
        if info is None:
            return
        with self._side:
            with ui.row().classes("items-center no-wrap w-full"):
                ui.label(info.name).classes("pp-gal-side-title")
                ui.space()
                wide = self._wide
                icon_button(
                    "minimize-2" if wide else "maximize-2",
                    self._toggle_wide,
                    "Narrower" if wide else "Wider",
                    "s",
                )
                icon_button("x", lambda: self._pick(info), "Close", "s")
            ui.html(
                f'<img src="{html.escape(image_url(info.path))}" alt="{html.escape(info.name)}">',
                sanitize=False,
            ).classes("pp-gal-preview")
            size = f"{info.width} × {info.height} px · " if info.width else ""
            when = f"{info.day:%b %d, %Y}".replace(" 0", " ")
            ui.label(f"{size}{_bytes(info.bytes)} · {when}").classes("pp-muted pp-gal-meta")
            tip(ui.label(info.path).classes("pp-muted pp-gal-path"), info.path)
            ui.label("Used in" if info.used_by else "Not used by any note").classes(
                "pp-gal-used-title"
            )
            for note in info.used_by:
                link = ui.label(note.rsplit("/", 1)[-1].rsplit(".", 1)[0]).classes("pp-gal-note")
                tip(link, note)
                link.on("click", lambda _e, n=note: self._go_to(n))
            with ui.column().classes("pp-gal-actions w-full"):
                self._action("copy", "Copy markdown", lambda: self._copy(info))
                self._action("file-plus", "Insert into note", lambda: self._insert_into(info))
                self._action("trash-2", "Move to trash", lambda: self._trash(info), danger=True)

    def _action(
        self, icon: str, label: str, on_click: Callable[[], object], danger: bool = False
    ) -> None:
        button = ui.button(label, on_click=on_click, color=None).props("flat dense no-caps")
        button.classes("pp-gal-action" + (" pp-gal-danger" if danger else ""))
        with button:
            line_icon(icon, "s").classes("order-first")

    def _markdown(self, info: ImageInfo) -> str:
        width = min(info.width, 640) if info.width else None
        return image_markdown(_relative_ref(info.path, self._active()), width)

    def _copy(self, info: ImageInfo) -> None:
        text = self._markdown(info)
        ui.run_javascript(
            f"navigator.clipboard && navigator.clipboard.writeText({json.dumps(text)})"
        )
        ui.notify("Copied", timeout=1200, position="bottom")

    def _insert_into(self, info: ImageInfo) -> None:
        if self._active() is None:
            ui.notify("Open a note first.", type="warning")
            return
        self._insert(self._markdown(info) + "\n")
        self._dialog.close()
        ui.notify("Inserted into the note", timeout=1500, position="bottom")

    def _go_to(self, note: str) -> None:
        self._dialog.close()
        self._open_note(note)

    async def _trash(self, info: ImageInfo) -> None:
        if info.used_by:
            n = len(info.used_by)
            with ui.dialog() as ask, ui.card().classes("pp-dialog"):
                ui.label("Move this image to the trash?").classes("pp-dialog-title")
                ui.label(
                    f"{n} note{'s' * (n != 1)} still show{'s' * (n == 1)} it and will show a "
                    "broken image. You can restore it from the vault's trash."
                ).classes("pp-muted pp-dialog-text")
                with ui.row().classes("justify-end w-full"):
                    ui.button("Cancel", on_click=lambda: ask.submit(False)).props("flat no-caps")
                    ui.button("Move to trash", on_click=lambda: ask.submit(True)).props(
                        "no-caps color=negative"
                    )
            ok = await ask
            ask.delete()
            if not ok:
                return
        try:
            trash_image(self.vault, info.path)
        except (OSError, VaultError):
            log.exception("could not trash %s", info.path)
            ui.notify("Could not move the image to the trash.", type="negative")
            return
        self._picked = None
        ui.notify("Image moved to the trash", timeout=1500, position="bottom")
        await self.reload()
