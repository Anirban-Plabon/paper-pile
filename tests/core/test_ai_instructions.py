from pathlib import Path

from paper_pile.core.ai.instructions import (
    MAX_FILE_CHARS,
    draft_messages,
    instruction_file,
    system_instruction,
)
from paper_pile.core.config import Config
from paper_pile.core.settings import ALL, parse_value


def _config(tmp_path: Path, **values: object) -> Config:
    config = Config(global_path=tmp_path / "c.toml")
    for key, value in values.items():
        config.set(f"ai.{key}", value, "global")
    return config


def test_typed_instruction(tmp_path: Path) -> None:
    assert system_instruction(None, tmp_path) == ""
    assert system_instruction(_config(tmp_path), tmp_path) == ""
    config = _config(tmp_path, instructions="  Be brief.\nUse lists. ")
    assert system_instruction(config, tmp_path) == "Be brief.\nUse lists."


def test_instruction_from_a_file(tmp_path: Path) -> None:
    (tmp_path / "AI").mkdir()
    (tmp_path / "AI" / "me.md").write_text("# Rules\n\nAnswer in haiku.\n" + "x" * 9000)
    config = _config(tmp_path, instructions="typed", instructions_from="file")
    assert system_instruction(config, tmp_path) == ""  # no file chosen yet
    config.set("ai.instructions_file", "AI/me.md", "global")
    text = system_instruction(config, tmp_path)
    assert text.startswith("# Rules\n\nAnswer in haiku.") and len(text) == MAX_FILE_CHARS
    config.set("ai.instructions_file", "AI/missing.md", "global")
    assert system_instruction(config, tmp_path) == ""  # a broken file never stops the AI


def test_instruction_file_paths(tmp_path: Path) -> None:
    assert instruction_file(tmp_path, "") is None
    assert instruction_file(tmp_path, "a/b.md") == tmp_path / "a" / "b.md"
    assert instruction_file(tmp_path, "/x/y.md") == Path("/x/y.md")


def test_instruction_settings_validate() -> None:
    long = ALL["ai.instructions"]
    assert parse_value(long, "line one\nline {two}").ok  # several lines and braces are fine
    assert not parse_value(long, "x" * 4001).ok
    file = ALL["ai.instructions_file"]
    assert parse_value(file, "AI/me.md").ok and parse_value(file, "").ok
    assert not parse_value(file, "AI/me.pdf").ok


def test_draft_messages() -> None:
    system, user = draft_messages("  a strict math tutor ", "Bengali")
    assert system.role == "system" and "Bengali" in system.content
    assert user.content.endswith("a strict math tutor")
