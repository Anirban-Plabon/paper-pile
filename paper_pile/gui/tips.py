"""Hover names for controls that show no text (icon buttons, the Ollama dot, a cut-off path).

One look everywhere: ``static/tips.js`` draws a single small tooltip for any element with a
``data-tip`` attribute, keeps it 8 px inside the window and hides it on click, key or scroll.
Native ``title`` attributes (yellow, unstyled boxes in the Qt window) and Quasar tooltips
(which can touch the window edge) are not used.
"""

from nicegui import ui


def tip[E: ui.element](element: E, text: str) -> E:
    """Give ``element`` a hover name (an empty text removes it). Returns the element."""
    if text:
        element._props["data-tip"] = text
    else:
        element._props.pop("data-tip", None)
    element.update()
    return element
