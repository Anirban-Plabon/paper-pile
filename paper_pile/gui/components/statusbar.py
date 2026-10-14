"""Status bar. The save indicator is live (P2.1); the other values are placeholders (P9.4)."""

from collections.abc import Callable
from dataclasses import dataclass

from nicegui import ui


@dataclass
class StatusBar:
    left_toggle: ui.button
    right_toggle: ui.button
    save_label: ui.label
    mode_label: ui.label

    def set_mode(self, mode: str, plain: bool = False) -> None:
        """Show Live/Source, or "Plain text" (not toggleable) while a .txt note is active."""
        self.mode_label.set_text(
            "Plain text" if plain else ("Live" if mode == "live" else "Source")
        )
        if plain:
            self.mode_label.classes("pp-mode-plain")
        else:
            self.mode_label.classes(remove="pp-mode-plain")

    def set_save_state(self, text: str, *, error: bool = False) -> None:
        self.save_label.set_text(text)
        if error:
            self.save_label.classes("pp-save-error")
        else:
            self.save_label.classes(remove="pp-save-error")


def status_bar(
    on_toggle_left: Callable[[], None],
    on_toggle_right: Callable[[], None],
    on_toggle_mode: Callable[[], None],
    mode: str = "live",
) -> StatusBar:
    with ui.row().classes("pp-statusbar items-center no-wrap"):
        left = (
            ui.button(icon="menu", on_click=on_toggle_left)
            .props("flat dense size=sm")
            .tooltip("Toggle file tree (Ctrl+B)")
        )
        ui.space()
        mode_label = ui.label("Live" if mode == "live" else "Source")
        mode_label.classes("pp-muted pp-mode-toggle").tooltip("Live Preview / Source (Ctrl+E)")
        mode_label.on("click", lambda _e: on_toggle_mode())
        ui.label("0 words · Ln 1, Col 1").classes("pp-muted")
        save = ui.label("Ready").classes("pp-muted pp-save")
        ui.label("●").classes("pp-dot pp-dot-off").tooltip("Ollama status")
        right = (
            ui.button(icon="chat_bubble_outline", on_click=on_toggle_right)
            .props("flat dense size=sm")
            .tooltip("Toggle AI chat (Ctrl+L)")
        )
    return StatusBar(left, right, save, mode_label)
