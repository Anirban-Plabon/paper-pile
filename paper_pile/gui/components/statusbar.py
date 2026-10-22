"""Status bar: Live/Source, word count + caret position, save state, Ollama dot (P9.4)."""

from collections.abc import Callable
from dataclasses import dataclass

from nicegui import ui

from paper_pile.gui.tips import tip


@dataclass
class StatusBar:
    save_label: ui.label
    mode_label: ui.label
    ollama_dot: ui.label
    stats_label: ui.label

    def set_stats(self, words: int | None, line: int, col: int) -> None:
        """``words`` is None without an open note: nothing to count."""
        if words is None:
            self.stats_label.set_text("")
            return
        self.stats_label.set_text(f"{words} word{'' if words == 1 else 's'} · Ln {line}, Col {col}")

    def set_mode(self, mode: str, plain: bool = False) -> None:
        """Show Live/Source, or "Plain text" (not toggleable) while a .txt note is active."""
        self.mode_label.set_text(
            "Plain text" if plain else ("Live" if mode == "live" else "Source")
        )
        if plain:
            self.mode_label.classes("pp-mode-plain")
        else:
            self.mode_label.classes(remove="pp-mode-plain")

    def show_ollama(self, on: bool) -> None:
        """The dot is there only while the AI feature is on."""
        self.ollama_dot.set_visibility(on)

    def set_ollama(self, ok: bool, text: str) -> None:
        """Green dot when Ollama can be reached, grey otherwise; the tooltip says why."""
        self.ollama_dot.classes(
            add="pp-dot-on" if ok else "pp-dot-off", remove="pp-dot-off" if ok else "pp-dot-on"
        )
        tip(self.ollama_dot, text)

    def set_save_state(self, text: str, *, error: bool = False) -> None:
        self.save_label.set_text(text)
        if error:
            self.save_label.classes("pp-save-error")
        else:
            self.save_label.classes(remove="pp-save-error")


def status_bar(
    on_toggle_mode: Callable[[], None],
    mode: str = "live",
) -> StatusBar:
    with ui.row().classes("pp-statusbar items-center no-wrap"):
        ui.space()
        mode_label = ui.label("Live" if mode == "live" else "Source")
        mode_label.classes("pp-muted pp-mode-toggle")
        mode_label.on("click", lambda _e: on_toggle_mode())
        stats = ui.label("").classes("pp-muted pp-stats")
        save = ui.label("Ready").classes("pp-muted pp-save")
        dot = tip(ui.label("●").classes("pp-dot pp-dot-off"), "Ollama status")
    return StatusBar(save, mode_label, dot, stats)
