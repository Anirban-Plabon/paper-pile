from pathlib import Path

import pytest

from paper_pile.core.config import DEFAULTS, Config
from paper_pile.core.settings import (
    ACCENTS,
    ALL,
    SECTIONS,
    accent_colors,
    hex_to_rgb,
    parse_value,
    sanitized,
    validate,
)


def test_every_setting_has_a_default_that_is_valid() -> None:
    for key, setting in ALL.items():
        node = DEFAULTS
        for part in key.split("."):
            node = node[part]
        parsed = parse_value(setting, node)
        assert parsed.ok, (key, parsed.error)
        assert parsed.value == node or str(parsed.value) == str(node), key


def test_sections_cover_the_spec() -> None:
    assert list(SECTIONS) == ["Appearance", "Editor", "Vault", "AI", "Paste"]
    keys = set(ALL)
    assert {"appearance.theme", "appearance.accent", "appearance.density"} <= keys
    assert {
        "editor.font_family",
        "editor.font_size",
        "editor.line_height",
        "editor.word_wrap",
    } <= keys
    assert {"editor.tab_size", "editor.spell_check", "editor.default_mode"} <= keys
    assert {"vault.templates_folder", "vault.daily_notes_folder"} <= keys
    assert {
        "ai.host",
        "ai.model",
        "ai.embed_model",
        "ai.context_budget",
        "paste.smart_paste",
    } <= keys
    assert len(ACCENTS) == 8  # "6-8 preset palette"


@pytest.mark.parametrize(
    ("key", "raw", "ok", "value"),
    [
        ("appearance.theme", "dark", True, "dark"),
        ("appearance.theme", "purple", False, None),
        ("appearance.accent", "teal", True, "teal"),
        ("editor.font_size", "16", True, 16),
        ("editor.font_size", 16, True, 16),
        ("editor.font_size", "7", False, None),
        ("editor.font_size", "41", False, None),
        ("editor.font_size", "abc", False, None),
        ("editor.font_size", "1.5", False, None),
        ("editor.line_height", "1.8", True, 1.8),
        ("editor.line_height", "0.5", False, None),
        ("editor.word_wrap", True, True, True),
        ("editor.word_wrap", "yes", False, None),
        ("editor.tab_size", "2", True, 2),
        ("editor.tab_size", 8, True, 8),
        ("editor.tab_size", "5", False, None),
        ("editor.default_mode", "source", True, "source"),
        ("ai.host", "http://localhost:11434/", True, "http://localhost:11434"),
        ("ai.host", "localhost:11434", False, None),
        ("ai.host", "ftp://x", False, None),
        ("ai.host", "", False, None),
        ("ai.context_budget", "100", False, None),
        ("ai.context_budget", "8000", True, 8000),
        ("ai.model", "  gemma4:12b ", True, "gemma4:12b"),
        ("ai.model", "", False, None),
        ("ai.embed_model", "", True, ""),
        ("vault.templates_folder", "/Templates/", True, "Templates"),
        ("vault.templates_folder", "a/b", True, "a/b"),
        ("vault.templates_folder", "", True, ""),
        ("vault.templates_folder", "../x", False, None),
        ("vault.templates_folder", ".trash", False, None),
        ("editor.font_family", "Georgia, serif", True, "Georgia, serif"),
        ("editor.font_family", "x; } body { color: red", False, None),
        ("editor.font_family", "", False, None),
        ("paste.smart_paste", False, True, False),
    ],
)
def test_parse_value(key: str, raw: object, ok: bool, value: object) -> None:
    parsed = parse_value(ALL[key], raw)
    assert parsed.ok is ok
    if ok:
        assert parsed.value == value and type(parsed.value) is type(value)
    else:
        assert parsed.error


def test_validate_splits_good_and_bad_and_ignores_unknown() -> None:
    clean, errors = validate(
        {
            "editor.font_size": "18",
            "ai.context_budget": "5",
            "nonsense.key": "x",
            "paste.smart_paste": True,
        }
    )
    assert clean == {"editor.font_size": 18, "paste.smart_paste": True}
    assert list(errors) == ["ai.context_budget"]


def test_sanitized_replaces_bad_values_with_defaults() -> None:
    merged = {"appearance": {"theme": "neon"}, "editor": {"font_size": "99", "tab_size": 2}}
    out = sanitized(merged)
    assert out["appearance.theme"] == "system" and out["editor.font_size"] == 14
    assert out["editor.tab_size"] == 2 and len(out) == len(ALL)


def test_accent_colours() -> None:
    assert accent_colors("pink") == ACCENTS["pink"] and accent_colors("nope") == ACCENTS["blue"]
    assert hex_to_rgb("#3b82f6") == "59, 130, 246"
    for light, dark in ACCENTS.values():
        assert len(light) == 7 and len(dark) == 7


# ---- Config: unset / layers -----------------------------------------------------------------


def test_config_unset_and_layers(tmp_path: Path) -> None:
    cfg = Config(global_path=tmp_path / "g.toml", vault=tmp_path)
    cfg.set("editor.font_size", 18, "global")
    cfg.set("editor.font_size", 20, "vault")
    cfg.set("ai.model", "m", "vault")
    assert cfg.get("editor.font_size") == 20  # the vault wins
    cfg.unset("editor.font_size", "vault")
    assert cfg.get("editor.font_size") == 18  # back to the global value
    cfg.unset("ai.model", "vault")
    assert cfg.layer("vault") == {}  # the emptied table is gone too
    cfg.unset("ai.model", "vault")  # unsetting what is not there is harmless
    cfg.unset("no.such.key", "global")
    assert cfg.layer("global") == {"editor": {"font_size": 18}}
    cfg.save("global")
    assert Config(global_path=tmp_path / "g.toml", vault=tmp_path).get("editor.font_size") == 18
