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
    stepped,
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
    assert list(SECTIONS) == ["General", "Appearance", "Editor", "Print", "AI"]
    keys = set(ALL)
    assert {"appearance.theme", "appearance.accent", "appearance.density"} <= keys
    assert {
        "editor.font_family",
        "editor.font_size",
        "editor.line_height",
        "editor.word_wrap",
    } <= keys
    assert {"editor.tab_size", "editor.spell_check", "editor.default_mode"} <= keys
    assert {"editor.page_view", "print.paper"} <= keys
    assert {"vault.templates_folder", "vault.daily_notes_folder"} <= keys
    assert {
        "ai.host",
        "ai.model",
        "ai.embed_model",
        "ai.context_budget",
        "paste.smart_paste",
    } <= keys
    assert len(ACCENTS) == 12  # the preset grid (2 rows of 6)


@pytest.mark.parametrize(
    ("key", "raw", "ok", "value"),
    [
        ("appearance.theme", "dark", True, "dark"),
        ("appearance.theme", "purple", False, None),
        ("appearance.accent", "teal", True, "teal"),
        ("appearance.accent", "Teal", True, "teal"),
        ("appearance.accent", "#F97316", True, "#f97316"),
        ("appearance.accent", "rgb(1, 2, 3)", True, "#010203"),
        ("appearance.accent", "not a colour", False, None),
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
    assert accent_colors("#000000") == ("#000000", "#595959")  # custom: lifted for dark
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


def test_search_finds_by_name_help_and_section() -> None:
    from paper_pile.core.settings import search_settings

    assert [s.key for s in search_settings("font size")] == ["editor.font_size"]
    assert "ai.host" in [s.key for s in search_settings("ollama")]
    assert {s.key for s in search_settings("paste")} >= {"paste.smart_paste"}
    assert search_settings("") == [] and search_settings("zzzz") == []
    assert [s.key for s in search_settings("theme dark")] == []  # every word must match


def test_language_is_a_known_code_and_defaults_to_english() -> None:
    from paper_pile.core.settings import ALL, LANGUAGES, parse_value, sanitized

    assert parse_value(ALL["general.language"], "bn").ok
    assert not parse_value(ALL["general.language"], "klingon").ok
    assert sanitized({})["general.language"] == "en" and "en" in LANGUAGES


def test_general_groups_language_paste_folders_daily() -> None:
    groups = [s.group for s in SECTIONS["General"]]
    assert groups == [
        *["Features"] * 3,
        "Language",
        "Paste",
        "Images",
        *["Daily notes"] * 4,
        "Templates",
        "Templates",
    ]
    assert "ai.chats_folder" not in {s.key for s in SECTIONS["General"]}  # it is under AI


def test_folder_settings_allow_the_app_folders_only() -> None:
    from paper_pile.core.settings import ALL, parse_value

    images, chats = ALL["vault.images_folder"], ALL["ai.chats_folder"]
    assert parse_value(images, ".image").value == ".image"
    assert parse_value(images, "Pictures/2026/").value == "Pictures/2026"
    assert not parse_value(images, ".trash").ok and not parse_value(images, "a/.hidden").ok
    assert not parse_value(images, ".paper-pile").ok
    assert parse_value(chats, "/data/chats/").value == "/data/chats"  # outside the vault: kept
    assert parse_value(chats, "~/chats").value == "~/chats"
    assert not parse_value(images, "/data/pics").value.startswith("/")  # images stay inside
    tpl = ALL["vault.daily_notes_template"]
    assert parse_value(tpl, ".template/Daily.md").ok


def test_daily_note_settings_are_checked() -> None:
    from paper_pile.core.settings import ALL, parse_value

    fmt, tpl = ALL["vault.daily_notes_format"], ALL["vault.daily_notes_template"]
    assert parse_value(fmt, "YYYY/MM/YYYY-MM-DD").ok
    assert not parse_value(fmt, "YYYY-MM").ok and not parse_value(fmt, "").ok
    assert parse_value(tpl, "Templates/Daily.md").value == "Templates/Daily.md"
    assert parse_value(tpl, "").value == "" and not parse_value(tpl, "../x.md").ok


def test_steps_stay_on_the_grid_and_within_limits() -> None:
    size, height = ALL["editor.font_size"], ALL["editor.line_height"]
    assert stepped(size, 14, 1) == 15
    assert stepped(size, "14", -1) == 13
    assert stepped(size, 40, 1) == 40
    assert stepped(size, 8, -1) == 8
    assert stepped(height, 1.6, 1) == 1.7
    assert stepped(height, 1.65, -1) == 1.5  # snaps to the 0.1 grid first (1.65 -> 1.6)
    assert stepped(height, 3.0, 1) == 3.0
    assert stepped(height, "junk", 1) == 1.1


def test_code_font_is_a_setting_with_a_default() -> None:
    code = ALL["editor.code_font_family"]
    assert sanitized({})["editor.code_font_family"] == DEFAULTS["editor"]["code_font_family"]
    assert parse_value(code, "'Fira Code', monospace").ok
    assert not parse_value(code, "").ok
    assert not parse_value(code, "x; color: red").ok


def test_page_view_is_off_lines_or_pages_and_reads_the_old_switch() -> None:
    setting = ALL["editor.page_view"]
    assert setting.choices == ("off", "lines", "pages")
    assert parse_value(setting, True).value == "lines"  # before Real pages it was on / off
    assert parse_value(setting, False).value == "off"
    assert not parse_value(setting, "maybe").ok
    assert sanitized({})["editor.page_view"] == "off"


def test_feature_switches_and_minimal_settings_decide_what_is_listed() -> None:
    from paper_pile.core.settings import SECTIONS, is_shown, search_settings, shown_sections

    values = sanitized({})
    assert values["features.ai"] and values["features.calendar"] and values["settings.minimal"]
    general = {s.key: s for s in SECTIONS["General"]}
    ai = {s.key: s for s in SECTIONS["AI"]}
    assert [s.key for s in SECTIONS["General"][:3]] == [
        "features.ai",
        "features.calendar",
        "settings.minimal",
    ]
    # minimal: essentials only, but search still finds everything
    assert is_shown("AI", ai["ai.model"], values)
    assert not is_shown("AI", ai["ai.temperature"], values)
    assert is_shown("AI", ai["ai.temperature"], values, searching=True)
    assert search_settings("temperature", values)
    # AI off: its section is gone, even from search
    off = {**values, "features.ai": False}
    assert "AI" not in shown_sections(off)
    assert not search_settings("temperature", off)
    # calendar off: the daily-note settings go (in every view)
    full = {**values, "settings.minimal": False, "features.calendar": False}
    assert not is_shown("General", general["vault.daily_notes_folder"], full)
    assert is_shown("General", general["vault.templates_folder"], full)
    assert shown_sections({**values, "settings.minimal": False}) == list(SECTIONS)
