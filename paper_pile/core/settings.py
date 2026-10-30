"""What can be set, and what values are allowed (PLAN §4.12).

The settings dialog is generated from :data:`SECTIONS`; every value that comes back from it (or
from a hand-edited ``config.toml``) goes through :func:`parse_value`, so an invalid number or a
made-up theme can never reach the app. No UI here.
"""

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal

from paper_pile.core.ai.install import ai_available
from paper_pile.core.colors import lighten, parse_color
from paper_pile.core.vault import is_hidden_part

Kind = Literal["choice", "int", "float", "bool", "text", "longtext", "url", "color"]

# accent colour presets (the grid in Settings): name -> (light theme colour, dark theme colour).
# The accent may also be any colour code (see core/colors.py); it is then stored as #rrggbb.
ACCENTS: dict[str, tuple[str, str]] = {
    "blue": ("#3b82f6", "#6ea8fe"),
    "sky": ("#0284c7", "#5cc4f5"),
    "teal": ("#0d9488", "#4fd1c5"),
    "green": ("#16a34a", "#5fd98a"),
    "lime": ("#65a30d", "#a3e05a"),
    "amber": ("#d97706", "#fbbf47"),
    "orange": ("#f97316", "#ffb06b"),
    "red": ("#ef4444", "#ff8a8a"),
    "pink": ("#ec4899", "#f59bc8"),
    "violet": ("#8b5cf6", "#b79cff"),
    "indigo": ("#6366f1", "#a5a8ff"),
    "slate": ("#64748b", "#a3b1c6"),
}
THEMES = ("light", "dark", "system")
DENSITIES = ("comfortable", "compact")
MOTIONS = ("off", "fast", "normal", "slow")
MOTION_LABELS = {"off": "Off", "fast": "Fast", "normal": "Normal", "slow": "Slow"}
ICON_COLORS = {"default": "Default", "accent": "Accent"}  # value -> shown
EDIT_MODES = {"ask": "Ask first", "auto": "Apply at once", "readonly": "Read-only"}  # ai.edits
MOTION_FACTORS = {"off": 0.0, "fast": 0.6, "normal": 1.0, "slow": 1.6}  # × every duration
MODES = ("live", "source")
PAPER_SIZES = ("A4", "Letter")  # core/printdoc.py PAPERS
PAGE_VIEWS = {"off": "Off", "lines": "Page lines", "pages": "Real pages"}  # value -> shown
# editor fonts: (name shown, CSS font-family); any other CSS list can be typed in
FONTS: tuple[tuple[str, str], ...] = (
    ("Monospace", "monospace"),
    ("Code", "ui-monospace, 'JetBrains Mono', Menlo, Consolas, monospace"),
    ("Sans", "system-ui, sans-serif"),
    ("Humanist", "'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif"),
    ("Serif", "Georgia, 'Times New Roman', serif"),
    ("Book", "'Iowan Old Style', 'Palatino Linotype', Palatino, Georgia, serif"),
)
FONT_FAMILIES = tuple(css for _name, css in FONTS)
# code fonts (code blocks, inline code, code in chat): installed fonts only, falling back to the
# system monospace when one is missing; any other CSS list can be typed in
CODE_FONTS: tuple[tuple[str, str], ...] = (
    ("Monospace", "monospace"),
    ("System mono", "ui-monospace, Menlo, Consolas, monospace"),
    ("JetBrains Mono", "'JetBrains Mono', ui-monospace, monospace"),
    ("Fira Code", "'Fira Code', ui-monospace, monospace"),
    ("Cascadia Code", "'Cascadia Code', 'Cascadia Mono', Consolas, monospace"),
    ("Source Code Pro", "'Source Code Pro', ui-monospace, monospace"),
    ("DejaVu Sans Mono", "'DejaVu Sans Mono', monospace"),
)
# writing languages: code -> name (spell checking, and the language the AI answers in)
LANGUAGES: dict[str, str] = {
    "en": "English",
    "bn": "বাংলা (Bengali)",
    "es": "Español",
    "fr": "Français",
    "de": "Deutsch",
    "pt": "Português",
    "it": "Italiano",
    "hi": "हिन्दी (Hindi)",
    "ar": "العربية (Arabic)",
    "zh": "中文 (Chinese)",
    "ja": "日本語 (Japanese)",
}

MAX_LONGTEXT = 4000  # the system instruction


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
    group: str = ""  # a heading shown above it inside its section
    step: float | None = None  # numbers with a step get − / + buttons
    essential: bool = False  # listed while Settings is minimal (PLAN §4.18)


@dataclass(frozen=True, slots=True)
class Parsed:
    ok: bool
    value: Any = None
    error: str = ""


_CHATS_FOLDER = Setting(
    "ai.chats_folder",
    "Memories",
    "text",
    placeholder=".memory",
    help="Saved AI chats",
    group="Memories",
)

SECTIONS: dict[str, tuple[Setting, ...]] = {
    "General": (
        Setting(
            "features.ai",
            "AI",
            "bool",
            help="Chat, AI commands, Ollama",
            group="Features",
            essential=True,
        ),
        Setting(
            "features.calendar",
            "Calendar",
            "bool",
            help="Calendar tab, daily notes",
            group="Features",
            essential=True,
        ),
        Setting(
            "settings.minimal",
            "Minimal settings",
            "bool",
            help="Only the essentials",
            group="Features",
            essential=True,
        ),
        Setting(
            "general.language",
            "Writing language",
            "choice",
            tuple(LANGUAGES),
            help="Spell check and AI replies",
            group="Language",
            essential=True,
        ),
        Setting(
            "general.restore_tabs",
            "Reopen last tabs",
            "bool",
            help="On start, open the notes you had open",
            group="Startup and files",
        ),
        Setting(
            "general.confirm_delete",
            "Ask before deleting",
            "bool",
            help="Confirm before a note or folder goes to the trash",
            group="Startup and files",
            essential=True,
        ),
        Setting(
            "paste.smart_paste",
            "Smart Paste",
            "bool",
            help="Tidy pasted web text",
            group="Paste",
            essential=True,
        ),
        Setting(
            "vault.images_folder",
            "Folder",
            "text",
            placeholder=".image",
            help="Pasted pictures",
            group="Images",
        ),
        Setting(
            "vault.daily_notes_folder",
            "Folder",
            "text",
            placeholder=".daily-notes",
            help="New daily notes",
            group="Daily notes",
        ),
        Setting(
            "vault.show_daily_notes",
            "Show in file tree",
            "bool",
            group="Daily notes",
        ),
        Setting(
            "vault.daily_notes_format",
            "Date format",
            "text",
            placeholder="YYYY-MM-DD",
            help="/ makes subfolders",
            group="Daily notes",
        ),
        Setting(
            "vault.daily_notes_template",
            "Template",
            "text",
            placeholder="e.g. .template/daily/Day.md",
            help="Copied into new ones",
            group="Daily notes",
        ),
        Setting(
            "vault.templates_folder",
            "Folder",
            "text",
            placeholder=".template",
            help="Used by /template",
            group="Templates",
        ),
        Setting(
            "vault.show_templates",
            "Show in file tree",
            "bool",
            group="Templates",
        ),
    ),
    "Appearance": (
        Setting(
            "appearance.theme",
            "Mode",
            "choice",
            THEMES,
            help="System follows the OS",
            group="Theme",
            essential=True,
        ),
        Setting(
            "appearance.accent",
            "Accent colour",
            "color",
            tuple(ACCENTS),
            help="Links and highlights",
            group="Theme",
            essential=True,
        ),
        Setting(
            "appearance.icons",
            "Icon colour",
            "choice",
            tuple(ICON_COLORS),
            help="Accent: icons take the accent colour",
            group="Theme",
        ),
        Setting(
            "appearance.density",
            "Density",
            "choice",
            DENSITIES,
            help="Interface spacing",
            group="Interface",
        ),
        Setting(
            "appearance.motion",
            "Animation speed",
            "choice",
            MOTIONS,
            help="Off turns animations off",
            group="Interface",
            essential=True,
        ),
    ),
    "Editor": (
        Setting(
            "editor.font_family",
            "Font family",
            "text",
            help="Any CSS font list",
            group="Font",
            essential=True,
        ),
        Setting(
            "editor.font_size",
            "Font size (px)",
            "int",
            minimum=8,
            maximum=40,
            help="Editor text size",
            step=1,
            group="Font",
            essential=True,
        ),
        Setting(
            "editor.line_height",
            "Line height",
            "float",
            minimum=1.0,
            maximum=3.0,
            help="× text size",
            step=0.1,
            group="Font",
        ),
        Setting(
            "editor.code_font_family",
            "Code font",
            "text",
            help="Code and inline code",
            group="Font",
        ),
        Setting(
            "editor.word_wrap",
            "Wrap long lines",
            "bool",
            help="Wrap long lines",
            group="Layout",
            essential=True,
        ),
        Setting(
            "editor.readable_width",
            "Readable line length",
            "bool",
            help="Keep lines narrow on wide windows",
            group="Layout",
            essential=True,
        ),
        Setting(
            "editor.line_numbers",
            "Show line numbers",
            "bool",
            help="Line numbers beside the text",
            group="Layout",
            essential=True,
        ),
        Setting(
            "editor.highlight_line",
            "Highlight current line",
            "bool",
            help="A soft band behind the caret's line",
            group="Layout",
        ),
        Setting(
            "editor.tab_size",
            "Tab size",
            "choice",
            ("2", "3", "4", "8"),
            help="In code blocks",
            group="Layout",
        ),
        Setting(
            "editor.spell_check",
            "Check spelling",
            "bool",
            help="Underline misspellings",
            group="Writing",
            essential=True,
        ),
        Setting(
            "editor.auto_title",
            "Title property from the note name",
            "bool",
            help="Adds title: to properties",
            group="Writing",
        ),
        Setting(
            "editor.last_edited",
            "Last edited",
            "bool",
            help="In the note's properties",
            group="Writing",
        ),
        Setting(
            "editor.tidy_button",
            "Tidy note button",
            "bool",
            help="Floating tidy button",
            group="Writing",
        ),
        Setting(
            "editor.word_count",
            "Word count",
            "bool",
            help="Words, line and column in the status bar",
            group="Writing",
        ),
        Setting(
            "editor.default_mode",
            "Starting mode",
            "choice",
            MODES,
            help="For new vaults",
            group="Writing",
        ),
        Setting(
            "editor.page_view",
            "Page view",
            "choice",
            tuple(PAGE_VIEWS),
            help="Pages as in the PDF",
            group="Page view",
            essential=True,
        ),
        Setting(
            "print.paper",
            "Paper size",
            "choice",
            PAPER_SIZES,
            help="Page view and PDF",
            group="Page view",
            essential=True,
        ),
        Setting(
            "editor.block_spacing",
            "Blank lines around blocks",
            "bool",
            help="Around tables, images, lists",
            group="Advanced",
        ),
    ),
    "AI": (
        Setting(
            "ai.host",
            "Ollama address",
            "url",
            placeholder="http://localhost:11434",
            group="Model",
            essential=True,
        ),
        Setting(
            "ai.model",
            "Chat model",
            "text",
            placeholder="gemma4:12b",
            help="Chat and AI commands",
            group="Model",
            essential=True,
        ),
        Setting(
            "ai.edits",
            "AI changes to notes",
            "choice",
            tuple(EDIT_MODES),
            help="Ask first shows a diff to accept",
            group="Context",
            essential=True,
        ),
        Setting(
            "ai.selection_popup",
            "Ask box under a selection",
            "bool",
            help="Ask about or rewrite the selected text",
            group="Context",
            essential=True,
        ),
        Setting(
            "ai.prompts_file",
            "Your prompts",
            "text",
            placeholder="e.g. AI/prompts.md",
            help="A list (- …) offered in the chat",
            group="Context",
        ),
        Setting(
            "ai.context_budget",
            "Context budget (tokens)",
            "int",
            minimum=500,
            maximum=200000,
            help="Most note text per message",
            group="Context",
        ),
        Setting(
            "ai.instructions",
            "System instruction",
            "longtext",
            placeholder="e.g. Answer briefly. Use bullet points.",
            help="Sent with every request",
            group="Context",
        ),
        Setting(
            "ai.instructions_from",
            "System instruction from",
            "choice",
            ("text", "file"),
            group="Context",
        ),
        Setting(
            "ai.instructions_file",
            "System instruction file",
            "text",
            placeholder="e.g. AI/instruction.md",
            group="Context",
        ),
        Setting(
            "ai.save_chats",
            "Save chats",
            "bool",
            group="Memories",
            essential=True,
        ),
        Setting(
            "ai.keep_chats_days",
            "Auto-delete after (days)",
            "int",
            minimum=0,
            maximum=3650,
            step=30,
            help="0 = never",
            group="Memories",
        ),
        _CHATS_FOLDER,
        Setting(
            "ai.temperature",
            "Temperature",
            "float",
            minimum=0,
            maximum=2,
            step=0.1,
            help="Low = focused, high = creative",
            group="Advanced",
        ),
        Setting(
            "ai.top_p",
            "Top-p",
            "float",
            minimum=0.05,
            maximum=1,
            step=0.05,
            help="Word variety",
            group="Advanced",
        ),
        Setting(
            "ai.num_ctx",
            "Context window (tokens)",
            "int",
            minimum=0,
            maximum=262144,
            step=2048,
            help="0 = automatic (up to 8k)",
            group="Advanced",
        ),
        Setting(
            "ai.history_turns",
            "Chat history sent",
            "int",
            minimum=0,
            maximum=50,
            step=2,
            help="Past messages per reply",
            group="Advanced",
        ),
        Setting(
            "ai.keep_alive",
            "Keep model loaded (min)",
            "int",
            minimum=0,
            maximum=1440,
            step=5,
            help="Faster replies, uses RAM",
            group="Advanced",
        ),
    ),
}

ALL: dict[str, Setting] = {s.key: s for group in SECTIONS.values() for s in group}


def is_shown(
    section: str, setting: Setting, values: Mapping[str, Any], *, searching: bool = False
) -> bool:
    """Whether Settings lists ``setting`` now (``values``: :func:`sanitized`). A switched-off
    feature hides its settings everywhere; minimal settings hide the non-essential ones except
    in search results (PLAN §4.18)."""
    if section == "AI" and not values["features.ai"]:
        return False
    if setting.group == "Daily notes" and not values["features.calendar"]:
        return False
    return searching or setting.essential or not values["settings.minimal"]


def shown_sections(values: Mapping[str, Any]) -> list[str]:
    """The sections that have at least one setting to list."""
    return [
        name for name, group in SECTIONS.items() if any(is_shown(name, s, values) for s in group)
    ]


def search_settings(query: str, values: Mapping[str, Any] | None = None) -> list[Setting]:
    """The settings whose name, help text or section matches every word of ``query`` (with
    ``values``: only those of features that are on)."""
    words = query.lower().split()
    if not words:
        return []
    found: list[Setting] = []
    for section, group in SECTIONS.items():
        for setting in group:
            if values is not None and not is_shown(section, setting, values, searching=True):
                continue
            haystack = (
                f"{section} {setting.group} {setting.label} {setting.help} {setting.key}".lower()
            )
            if all(w in haystack for w in words):
                found.append(setting)
    return found


def feature_on(values: Mapping[str, Any], key: str) -> bool:
    """A feature switch (``features.ai``, ``features.calendar``): on unless set to false. AI is
    also off unless the app was started with ``--ai``."""
    if key == "features.ai" and not ai_available():
        return False
    return get_nested(values, key, True) is not False


def get_nested(values: Mapping[str, Any], key: str, default: Any = None) -> Any:
    node: Any = values
    for part in key.split("."):
        if not isinstance(node, Mapping) or part not in node:
            return default
        node = node[part]
    return node


def stepped(setting: Setting, value: Any, direction: int) -> int | float:
    """``value`` moved one ``setting.step`` up (+1) or down (-1), on the step grid and within the
    setting's limits (what the − / + buttons do). An unreadable value starts from the minimum."""
    step = setting.step or 1
    try:
        number = float(str(value).strip())
    except ValueError:
        number = setting.minimum if setting.minimum is not None else 0.0
    moved = round(round(number / step) * step + direction * step, 6)
    if setting.minimum is not None:
        moved = max(moved, setting.minimum)
    if setting.maximum is not None:
        moved = min(moved, setting.maximum)
    return int(round(moved)) if setting.kind == "int" else round(moved, 2)


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
    if setting.key == "editor.page_view" and isinstance(raw, bool):
        return Parsed(True, "lines" if raw else "off")  # before Real pages it was on / off
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
    if kind == "color":
        if text.lower() in setting.choices:
            return Parsed(True, text.lower())
        color = parse_color(text)
        return (
            Parsed(True, color)
            if color
            else Parsed(False, error="A colour: #f97316, rgb(…), hsl(…)")
        )
    if kind == "url":
        if not text:
            return Parsed(False, error="An address is needed")
        if not text.lower().startswith(("http://", "https://")) or " " in text:
            return Parsed(False, error="Start with http:// or https://")
        return Parsed(True, text.rstrip("/"))
    if kind == "longtext":
        if len(text) > MAX_LONGTEXT:
            return Parsed(False, error=f"At most {MAX_LONGTEXT} characters")
        return Parsed(True, text)
    if setting.key == "ai.instructions_file" and text:
        if not text.lower().endswith((".md", ".txt")) or any(ord(c) < 32 for c in text):
            return Parsed(False, error="A .md or .txt file")
        return Parsed(True, text)
    if setting.key == "vault.daily_notes_format":
        from paper_pile.core.daily import format_problem

        problem = format_problem(text)
        return Parsed(False, error=problem) if problem else Parsed(True, text)
    if setting.key == "vault.daily_notes_template":
        path = text.strip("/")
        if path and any(
            part in {"", ".", ".."} or is_hidden_part(part, depth)
            for depth, part in enumerate(path.split("/"))
        ):
            return Parsed(False, error="A note inside the vault")
        return Parsed(True, path)
    if setting.key == "ai.chats_folder" and text.startswith(("/", "~")):
        return Parsed(True, text.rstrip("/") or "/")  # memories may live outside the vault
    if setting.key.endswith("_folder"):
        folder = text.strip("/")
        if folder and any(
            part in {"", ".", ".."} or is_hidden_part(part, depth)
            for depth, part in enumerate(folder.split("/"))
        ):
            return Parsed(False, error="A folder inside the vault")
        return Parsed(True, folder)
    if setting.key in {"editor.font_family", "editor.code_font_family", "ai.model"} and not text:
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
    if not ai_available():  # not started with --ai: the switch cannot be on
        out["features.ai"] = False
    return out


def language_name(code: str) -> str:
    """The English name of a writing language, for prompts ("Bengali"); "" for English."""
    if code in {"", "en"}:
        return ""
    shown = LANGUAGES.get(code, "")
    m = re.search(r"\((.+)\)", shown)
    return m.group(1) if m else shown


def accent_colors(value: str) -> tuple[str, str]:
    """``(light, dark)`` colour of an accent: a preset, or a colour code (lightened for dark).

    Anything else falls back to blue."""
    if value in ACCENTS:
        return ACCENTS[value]
    color = parse_color(value)
    return (color, lighten(color)) if color else ACCENTS["blue"]


def hex_to_rgb(color: str) -> str:
    """``#3b82f6`` -> ``"59, 130, 246"`` (for ``rgba(var(--x), .1)``)."""
    h = color.lstrip("#")
    return ", ".join(str(int(h[i : i + 2], 16)) for i in (0, 2, 4))
