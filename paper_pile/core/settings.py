"""What can be set, and what values are allowed (PLAN §4.12).

The settings dialog is generated from :data:`SECTIONS`; every value that comes back from it (or
from a hand-edited ``config.toml``) goes through :func:`parse_value`, so an invalid number or a
made-up theme can never reach the app. No UI here.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal

Kind = Literal["choice", "int", "float", "bool", "text", "url"]

# accent colour presets: name -> (light theme colour, dark theme colour)
ACCENTS: dict[str, tuple[str, str]] = {
    "blue": ("#3b82f6", "#6ea8fe"),
    "indigo": ("#6366f1", "#a5a8ff"),
    "violet": ("#8b5cf6", "#b79cff"),
    "pink": ("#ec4899", "#f59bc8"),
    "red": ("#ef4444", "#ff8a8a"),
    "orange": ("#f97316", "#ffb06b"),
    "green": ("#16a34a", "#5fd98a"),
    "teal": ("#0d9488", "#4fd1c5"),
}
THEMES = ("light", "dark", "system")
DENSITIES = ("comfortable", "compact")
MODES = ("live", "source")
FONT_FAMILIES = (
    "monospace",
    "ui-monospace, 'JetBrains Mono', Menlo, Consolas, monospace",
    "system-ui, sans-serif",
    "Georgia, 'Times New Roman', serif",
)


@dataclass(frozen=True, slots=True)
class Setting:
    key: str  # dotted, as in config.toml: "editor.font_size"
    label: str
    kind: Kind
    choices: tuple[str, ...] = ()
    minimum: float | None = None
    maximum: float | None = None
    help: str = ""
    placeholder: str = ""


@dataclass(frozen=True, slots=True)
class Parsed:
    ok: bool
    value: Any = None
    error: str = ""


SECTIONS: dict[str, tuple[Setting, ...]] = {
    "Appearance": (
        Setting("appearance.theme", "Theme", "choice", THEMES, help="System follows your desktop"),
        Setting("appearance.accent", "Accent colour", "choice", tuple(ACCENTS)),
        Setting("appearance.density", "Density", "choice", DENSITIES),
    ),
    "Editor": (
        Setting("editor.font_family", "Font family", "text", help="Any CSS font-family list"),
        Setting("editor.font_size", "Font size (px)", "int", minimum=8, maximum=40),
        Setting("editor.line_height", "Line height", "float", minimum=1.0, maximum=3.0),
        Setting("editor.word_wrap", "Wrap long lines", "bool"),
        Setting("editor.tab_size", "Tab size", "choice", ("2", "3", "4", "8")),
        Setting("editor.spell_check", "Check spelling", "bool"),
        Setting(
            "editor.auto_title",
            "Title property from the note name",
            "bool",
            help="Writes title: <name> into a note's properties on open; a rename updates it",
        ),
        Setting("editor.default_mode", "Mode for a vault opened the first time", "choice", MODES),
    ),
    "Vault": (
        Setting(
            "vault.templates_folder",
            "Templates folder",
            "text",
            placeholder="e.g. Templates",
            help="Notes in it are offered by /template",
        ),
        Setting(
            "vault.daily_notes_folder",
            "Daily notes folder",
            "text",
            placeholder="e.g. Daily",
        ),
    ),
    "AI": (
        Setting("ai.host", "Ollama address", "url", placeholder="http://localhost:11434"),
        Setting("ai.model", "Chat model", "text", placeholder="gemma4:12b"),
        Setting("ai.embed_model", "Embedding model", "text", help="Not used yet"),
        Setting("ai.context_budget", "Context budget (tokens)", "int", minimum=500, maximum=200000),
    ),
    "Paste": (
        Setting(
            "paste.smart_paste",
            "Smart Paste",
            "bool",
            help="Clean markdown from copied web pages and AI chats",
        ),
    ),
}

ALL: dict[str, Setting] = {s.key: s for group in SECTIONS.values() for s in group}


def get_nested(values: Mapping[str, Any], key: str, default: Any = None) -> Any:
    node: Any = values
    for part in key.split("."):
        if not isinstance(node, Mapping) or part not in node:
            return default
        node = node[part]
    return node


def parse_value(setting: Setting, raw: Any) -> Parsed:
    """Check ``raw`` (what a form field or a config file holds) against ``setting``."""
    kind = setting.kind
    if kind == "bool":
        return Parsed(True, raw) if isinstance(raw, bool) else Parsed(False, error="Yes or no")
    if kind in {"int", "float"}:
        if isinstance(raw, bool):
            return Parsed(False, error="A number is needed")
        try:
            number = int(str(raw).strip()) if kind == "int" else float(str(raw).strip())
        except ValueError:
            return Parsed(False, error="A number is needed")
        lo, hi = setting.minimum, setting.maximum
        if (lo is not None and number < lo) or (hi is not None and number > hi):
            return Parsed(False, error=f"Between {lo:g} and {hi:g}")
        return Parsed(True, number)
    text = str(raw if raw is not None else "").strip()
    if kind == "choice":
        if setting.key == "editor.tab_size":
            return (
                Parsed(True, int(text))
                if text in setting.choices
                else Parsed(False, error="Not an option")
            )
        return (
            Parsed(True, text) if text in setting.choices else Parsed(False, error="Not an option")
        )
    if kind == "url":
        if not text:
            return Parsed(False, error="An address is needed")
        if not text.lower().startswith(("http://", "https://")) or " " in text:
            return Parsed(False, error="Start with http:// or https://")
        return Parsed(True, text.rstrip("/"))
    if setting.key.endswith("_folder"):
        folder = text.strip("/")
        if (
            any(part in {"", ".", ".."} or part.startswith(".") for part in folder.split("/"))
            and folder
        ):
            return Parsed(False, error="A folder inside the vault")
        return Parsed(True, folder)
    if setting.key in {"editor.font_family", "ai.model"} and not text:
        return Parsed(False, error="Cannot be empty")
    if len(text) > 200 or any(c in text for c in "{};\n\r<>"):
        return Parsed(False, error="Contains characters that are not allowed")
    return Parsed(True, text)


def validate(values: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, str]]:
    """``(clean values, errors)`` for a flat ``{"editor.font_size": "14", ...}`` mapping.

    Unknown keys are ignored. ``clean`` only holds the values that passed.
    """
    clean: dict[str, Any] = {}
    errors: dict[str, str] = {}
    for key, raw in values.items():
        setting = ALL.get(key)
        if setting is None:
            continue
        parsed = parse_value(setting, raw)
        if parsed.ok:
            clean[key] = parsed.value
        else:
            errors[key] = parsed.error
    return clean, errors


def sanitized(values: Mapping[str, Any]) -> dict[str, Any]:
    """A complete ``{key: value}`` of every known setting from ``values`` (a merged config); a
    missing or invalid value falls back to its default."""
    from paper_pile.core.config import DEFAULTS  # local: config imports nothing from here

    out: dict[str, Any] = {}
    for key, setting in ALL.items():
        parsed = parse_value(setting, get_nested(values, key))
        out[key] = parsed.value if parsed.ok else get_nested(DEFAULTS, key)
    return out


def accent_colors(name: str) -> tuple[str, str]:
    """``(light, dark)`` colour of an accent preset (blue for an unknown name)."""
    return ACCENTS.get(name, ACCENTS["blue"])


def hex_to_rgb(color: str) -> str:
    """``#3b82f6`` -> ``"59, 130, 246"`` (for ``rgba(var(--x), .1)``)."""
    h = color.lstrip("#")
    return ", ".join(str(int(h[i : i + 2], 16)) for i in (0, 2, 4))
