"""Saved chats: one JSON file per conversation in the memories folder (``ai.chats_folder``,
default ``<vault>/.memory``; vault-relative or absolute). Every function takes that folder.

The chat pane keeps its turns in memory; this module writes them out after each exchange so
the ⋮ menu can list earlier chats and open them again. Plain files (no index), newest first by
their ``updated`` time. A deleted chat goes to ``<vault>/.trash/`` like any other file.
"""

import json
import logging
import re
import shutil
import time
import uuid
from collections.abc import Iterable
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any

from paper_pile.core.fsutil import atomic_write_bytes
from paper_pile.core.session import META_DIR
from paper_pile.core.vault import Vault

log = logging.getLogger("paper_pile.ai.chats")

CHATS_DIR = "chats"  # the old place: <vault>/.paper-pile/chats
MEMORY_DIR = ".memory"
TITLE_CHARS = 60


@dataclass(slots=True)
class SavedTurn:
    role: str  # "user" | "assistant"
    text: str
    attachment: str = ""
    summary: str = ""
    error: bool = False


@dataclass(slots=True)
class SavedChat:
    id: str
    title: str
    created: float
    updated: float
    turns: list[SavedTurn] = field(default_factory=list)


def new_chat_id() -> str:
    return time.strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:6]


def chat_title(turns: list[SavedTurn]) -> str:
    """The first user message, on one line and cut to ``TITLE_CHARS``."""
    first = next((t.text for t in turns if t.role == "user" and t.text.strip()), "")
    line = " ".join(first.split())
    return line if len(line) <= TITLE_CHARS else line[: TITLE_CHARS - 1].rstrip() + "…"


def ago(ts: float, now: float) -> str:
    """A short "when" for the chat list: just now, 5 min ago, 3 h ago, yesterday, Oct 12."""
    seconds = max(0.0, now - ts)
    if seconds < 60:
        return "just now"
    if seconds < 3600:
        return f"{int(seconds // 60)} min ago"
    day, today = time.localtime(ts), time.localtime(now)
    if seconds < 86400 and day.tm_yday == today.tm_yday:
        return f"{int(seconds // 3600)} h ago"
    if seconds < 2 * 86400 and (today.tm_yday - day.tm_yday) % 366 == 1:
        return "yesterday"
    fmt = "%b %d" if day.tm_year == today.tm_year else "%b %d, %Y"
    return time.strftime(fmt, day).replace(" 0", " ")


def chats_folder(vault: Path, setting: str = "") -> Path:
    """Where a vault's chats are kept: ``setting`` (``ai.chats_folder``; relative to the vault
    unless absolute, ``~`` allowed) or, when empty, ``<vault>/.memory``. (Before P13 the place
    was ``.paper-pile/chats``; ``vault_folders.move_old_chats`` moves those.)"""
    chosen = setting.strip()
    if not chosen:
        return vault / MEMORY_DIR
    path = Path(chosen).expanduser()
    return path if path.is_absolute() else vault / path


def _path(folder: Path, chat_id: str) -> Path:
    if not chat_id or "/" in chat_id or "\\" in chat_id or chat_id.startswith("."):
        raise ValueError(f"bad chat id: {chat_id!r}")
    return folder / f"{chat_id}.json"


def save_chat(folder: Path, chat: SavedChat) -> None:
    """Write the chat atomically. Failure is logged, never fatal."""
    path = _path(folder, chat.id)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        data = json.dumps(asdict(chat), ensure_ascii=False, indent=1)
        atomic_write_bytes(path, data.encode("utf-8"))
    except OSError:
        log.exception("could not save chat %s", chat.id)


def _turn(raw: Any) -> SavedTurn | None:
    if not isinstance(raw, dict) or raw.get("role") not in ("user", "assistant"):
        return None
    if not isinstance(raw.get("text"), str):
        return None
    return SavedTurn(
        raw["role"],
        raw["text"],
        str(raw.get("attachment", "")),
        str(raw.get("summary", "")),
        bool(raw.get("error", False)),
    )


def load_chat(folder: Path, chat_id: str) -> SavedChat | None:
    """The chat, or None when it is missing or not a chat file."""
    try:
        data = json.loads(_path(folder, chat_id).read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return None
    if not isinstance(data, dict) or not isinstance(data.get("turns"), list):
        return None
    turns = [t for t in map(_turn, data["turns"]) if t is not None]
    created = data.get("created")
    updated = data.get("updated")
    return SavedChat(
        chat_id,
        str(data.get("title") or chat_title(turns)),
        float(created) if isinstance(created, int | float) else 0.0,
        float(updated) if isinstance(updated, int | float) else 0.0,
        turns,
    )


def list_chats(folder: Path) -> list[SavedChat]:
    """Every readable saved chat, newest first (turns included)."""
    if not folder.is_dir():
        return []
    chats = [load_chat(folder, p.stem) for p in folder.glob("*.json") if not p.name.startswith(".")]
    found = [c for c in chats if c is not None and c.turns]
    return sorted(found, key=lambda c: c.updated, reverse=True)


def delete_chat(vault: Vault, folder: Path, chat_id: str) -> None:
    """Move the chat's file to ``<vault>/.trash/`` (never a hard delete), also from a folder
    outside the vault."""
    path = _path(folder, chat_id)
    if not path.exists():
        return
    try:
        rel = path.resolve().relative_to(vault.root.resolve()).as_posix()
    except ValueError:  # outside the vault: filed under the default place
        rel = f"{META_DIR}/{CHATS_DIR}/{path.name}"
    vault.trash_move(path, rel)


def move_chats(src: Path, dst: Path) -> int:
    """Move every chat file from ``src`` to ``dst`` (the memories folder changed). A file whose
    name is already taken in ``dst`` stays where it is; returns how many moved."""
    if not src.is_dir() or src.resolve() == dst.resolve():
        return 0
    dst.mkdir(parents=True, exist_ok=True)
    moved = 0
    for path in sorted(src.glob("*.json")):
        if path.name.startswith(".") or (dst / path.name).exists():
            continue
        try:
            shutil.move(str(path), dst / path.name)
        except OSError:
            log.exception("could not move chat %s", path.name)
            continue
        moved += 1
    return moved


def delete_chats(vault: Vault, folder: Path, chat_ids: Iterable[str]) -> int:
    """Move several chats to the trash; how many went (a failing one is logged and skipped)."""
    moved = 0
    for chat_id in chat_ids:
        try:
            delete_chat(vault, folder, chat_id)
        except (OSError, ValueError):
            log.exception("could not delete chat %s", chat_id)
            continue
        moved += 1
    return moved


def chat_day(chat: SavedChat) -> date:
    """The local day the chat was last written to."""
    return datetime.fromtimestamp(chat.updated).date()


def filter_chats(
    chats: Iterable[SavedChat],
    query: str = "",
    start: date | None = None,
    end: date | None = None,
) -> list[SavedChat]:
    """The chats whose title or messages hold every word of ``query`` and that were last
    written to between ``start`` and ``end`` (both days included; either may be left open)."""
    words = query.lower().split()
    found: list[SavedChat] = []
    for chat in chats:
        day = chat_day(chat)
        if (start is not None and day < start) or (end is not None and day > end):
            continue
        if words:
            text = " ".join([chat.title, *(t.text for t in chat.turns)]).lower()
            if not all(w in text for w in words):
                continue
        found.append(chat)
    return found


def expired_chats(chats: Iterable[SavedChat], days: int, now: float) -> list[SavedChat]:
    """The chats not written to for more than ``days`` days (none when ``days`` is 0)."""
    if days <= 0:
        return []
    cutoff = now - days * 86400
    return [c for c in chats if c.updated < cutoff]


def chat_markdown(chat: SavedChat, user_name: str = "") -> str:
    """The chat as a markdown document: title, when, then each message under its speaker."""
    when = time.strftime("%b %d, %Y %H:%M", time.localtime(chat.updated)).replace(" 0", " ")
    n = len(chat.turns)
    lines = [f"# {chat.title or 'Untitled chat'}", "", f"*{when} · {n} message{'s' * (n != 1)}*"]
    for turn in chat.turns:
        who = (user_name or "You") if turn.role == "user" else "Assistant"
        lines += ["", f"### {who}", ""]
        if turn.attachment:
            lines += [f"*Attached: {'; '.join(turn.attachment.splitlines())}*", ""]
        lines.append(turn.text.strip() or "*(empty)*")
    return "\n".join(lines) + "\n"


_NOT_IN_NAMES = re.compile(r'[\\/:*?"<>|#^\[\]\x00-\x1f]+')


def chat_note_name(chat: SavedChat) -> str:
    """A note name for saving the chat into the vault (its title, minus what names forbid)."""
    name = " ".join(_NOT_IN_NAMES.sub(" ", chat.title).split()).lstrip(".").strip()
    return name[:TITLE_CHARS].rstrip(" .…") or "Chat"
