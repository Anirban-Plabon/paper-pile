"""Right pane: AI chat. Empty shell for now; the real chat arrives in P7."""

from nicegui import ui


def chat_panel() -> None:
    with ui.column().classes("pp-pane pp-chat"), ui.column().classes("pp-pane-body"):
        ui.label("AI chat").classes("pp-pane-title")
        ui.label("No messages yet").classes("pp-muted")
