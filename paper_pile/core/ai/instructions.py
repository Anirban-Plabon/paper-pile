"""The system instruction (Settings → AI): typed in the settings, or read from a markdown file.

It is added to the system prompt of chat and of the AI commands. ``draft_messages`` asks the
model to write one from a short description (the settings' *Write with AI*).
"""

import logging
from pathlib import Path

from paper_pile.core.ai.provider import ChatMessage
from paper_pile.core.config import Config

log = logging.getLogger("paper_pile.ai.instructions")

MAX_TEXT_CHARS = 4000  # typed in the settings
MAX_FILE_CHARS = 8000  # read from a file (the rest is left out)


def instruction_file(vault: Path, setting: str) -> Path | None:
    """The file ``ai.instructions_file`` names: absolute, ``~``, or relative to the vault."""
    chosen = setting.strip()
    if not chosen:
        return None
    path = Path(chosen).expanduser()
    return path if path.is_absolute() else vault / path


def system_instruction(config: Config | None, vault: Path | None) -> str:
    """What the user wants every answer to follow ("" when nothing is set or the file is
    missing: a broken file never stops the AI)."""
    if config is None:
        return ""
    if str(config.get("ai.instructions_from", "text")) != "file":
        return str(config.get("ai.instructions", "") or "").strip()
    path = instruction_file(vault or Path("."), str(config.get("ai.instructions_file", "") or ""))
    if path is None:
        return ""
    try:
        return path.read_text(encoding="utf-8", errors="replace")[:MAX_FILE_CHARS].strip()
    except OSError:
        log.warning("cannot read the system instruction file %s", path)
        return ""


def draft_messages(brief: str, language: str = "") -> list[ChatMessage]:
    """Ask the model for a system instruction that does what ``brief`` describes."""
    lang = f" Write it in {language}." if language else ""
    return [
        ChatMessage(
            "system",
            "You write system instructions for an AI assistant that lives inside a markdown "
            "note app. Reply with only the instruction itself: plain sentences or a short "
            'bullet list addressed to the assistant ("You …"), no title, no introduction, no '
            f"code block, at most 150 words.{lang}",
        ),
        ChatMessage("user", f"The assistant should be like this: {brief.strip()}"),
    ]
