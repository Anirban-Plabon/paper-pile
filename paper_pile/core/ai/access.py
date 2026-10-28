"""What the AI may read (PLAN §4.26): granted per vault, recorded outside every vault.

``ai_access.json`` in the app's config folder (``~/.config/paper-pile/``) holds one record per
vault, keyed by the vault's resolved absolute path. A grant counts for exactly that path: a vault
inside or around a granted one asks for its own, and a moved vault asks again. Kept out of the
vault, so a copied vault cannot grant itself access.

With a grant the AI may read the vault's notes of the allowed file types, except the app's own
folders, the memories folder, excluded paths and notes whose properties say ``ai: false``; and,
outside the vault, only the folders / files the user added. Every AI read goes through
:class:`AccessPolicy`. No UI imports here.
"""

import contextlib
import fnmatch
import json
import logging
import os
import re
from collections.abc import Iterable
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any

import platformdirs
import yaml

from paper_pile.core.fsutil import atomic_write_bytes
from paper_pile.core.parser import front_matter_lines

log = logging.getLogger("paper_pile.ai.access")

ACCESS_FILE = "ai_access.json"
DEFAULT_TYPES = (".md",)
NEVER = (".trash", ".paper-pile")  # vault folders the AI never reads (the memories folder too)
MAX_OUTSIDE_FILES = 2000  # listed from the granted outside folders
MAX_OUTSIDE_BYTES = 200 * 1024


class AccessDeniedError(Exception):
    """The AI may not read what it was asked to; the message is fit to show to the user."""


@dataclass(slots=True)
class Grant:
    granted: str  # when: "2026-10-28T14:05"
    file_types: list[str] = field(default_factory=lambda: list(DEFAULT_TYPES))
    allow_paths: list[str] = field(default_factory=list)  # outside the vault: absolute
    exclude: list[str] = field(default_factory=list)  # vault-relative paths or patterns


def access_file(config_dir: Path | None = None) -> Path:
    base = (
        config_dir if config_dir is not None else Path(platformdirs.user_config_dir("paper-pile"))
    )
    return base / ACCESS_FILE


def vault_key(vault: Path) -> str:
    """The record's key: the vault's resolved absolute path."""
    return str(vault.expanduser().resolve())


def _load_all(config_dir: Path | None) -> dict[str, Any]:
    try:
        data = json.loads(access_file(config_dir).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    vaults = data.get("vaults") if isinstance(data, dict) else None
    return vaults if isinstance(vaults, dict) else {}


def _strings(raw: Any) -> list[str]:
    return [s for s in raw if isinstance(s, str) and s.strip()] if isinstance(raw, list) else []


def load_grant(vault: Path, config_dir: Path | None = None) -> Grant | None:
    """The vault's grant, or None when it has none (or the record is damaged)."""
    raw = _load_all(config_dir).get(vault_key(vault))
    if not isinstance(raw, dict) or not isinstance(raw.get("granted"), str):
        return None
    types = [normalize_type(t) for t in _strings(raw.get("file_types"))]
    return Grant(
        raw["granted"],
        [t for t in types if t] if "file_types" in raw else list(DEFAULT_TYPES),
        _strings(raw.get("allow_paths")),
        _strings(raw.get("exclude")),
    )


def _write_all(vaults: dict[str, Any], config_dir: Path | None) -> None:
    path = access_file(config_dir)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        text = json.dumps({"vaults": vaults}, ensure_ascii=False, indent=1)
        atomic_write_bytes(path, text.encode("utf-8"))
    except OSError:
        log.exception("could not save %s", path)


def save_grant(vault: Path, grant: Grant, config_dir: Path | None = None) -> None:
    vaults = _load_all(config_dir)
    vaults[vault_key(vault)] = asdict(grant)
    _write_all(vaults, config_dir)


def grant_now(vault: Path, config_dir: Path | None = None) -> Grant:
    """Allow the AI to read ``vault`` (default file types, nothing outside, nothing excluded)."""
    grant = Grant(datetime.now().strftime("%Y-%m-%dT%H:%M"))
    save_grant(vault, grant, config_dir)
    return grant


def revoke(vault: Path, config_dir: Path | None = None) -> None:
    vaults = _load_all(config_dir)
    if vaults.pop(vault_key(vault), None) is not None:
        _write_all(vaults, config_dir)


def normalize_type(text: str) -> str:
    """``"md"`` / ``".MD"`` / ``"*.md"`` → ``".md"`` ("" when it is not a file type)."""
    t = text.strip().lstrip("*").lower()
    t = t if t.startswith(".") else "." + t
    return t if len(t) > 1 and "/" not in t and " " not in t else ""


def parse_types(text: str) -> list[str]:
    """File types typed as ``.md, .txt`` (commas or spaces), each once."""
    found = [normalize_type(t) for t in text.replace(",", " ").split()]
    return list(dict.fromkeys(t for t in found if t))


def says_private(text: str) -> bool:
    """Does the note's front matter say ``ai: false``?"""
    lines = front_matter_lines(text)
    if not lines:
        return False
    head = "\n".join(text.splitlines()[1 : lines - 1])
    try:
        data = yaml.safe_load(head)
    except yaml.YAMLError:
        return False
    return isinstance(data, dict) and data.get("ai") is False


class AccessPolicy:
    def __init__(self, vault: Path, grant: Grant | None, memory_dir: Path | None = None) -> None:
        self.vault = vault.expanduser().resolve()
        self.grant = grant
        never = list(NEVER)
        if memory_dir is not None:
            with contextlib.suppress(ValueError):  # a memories folder outside the vault
                never.append(memory_dir.resolve().relative_to(self.vault).as_posix())
        self._never = never

    @property
    def granted(self) -> bool:
        return self.grant is not None

    def _type_ok(self, name: str) -> bool:
        return (
            self.grant is not None and PurePosixPath(name).suffix.lower() in self.grant.file_types
        )

    def may_read(self, rel: str) -> bool:
        """May the AI read the vault note ``rel`` (vault-relative, POSIX)? Its text is checked
        separately (:func:`says_private`)."""
        if self.grant is None or not rel or not self._type_ok(rel):
            return False
        if any(rel == d or rel.startswith(d + "/") for d in self._never):
            return False
        for pattern in self.grant.exclude:
            p = pattern.strip().strip("/")
            if p and (rel == p or rel.startswith(p + "/") or fnmatch.fnmatch(rel, p)):
                return False
        return True

    def may_send(self, rel: str | None, text: str) -> bool:
        """May the note ``rel`` with ``text`` go to the model (path and properties)?"""
        return rel is not None and self.may_read(rel) and not says_private(text)

    # ---- outside the vault -----------------------------------------------------------------

    def _roots(self) -> list[Path]:
        if self.grant is None:
            return []
        return [Path(p).expanduser().resolve() for p in self.grant.allow_paths]

    def covers(self, path: Path) -> bool:
        """Is ``path`` (a folder or file outside the vault) granted already?"""
        real = path.expanduser().resolve()
        return any(real == root or root in real.parents for root in self._roots())

    def may_read_outside(self, path: Path) -> bool:
        """Is ``path`` (outside the vault) one of, or inside one of, the granted paths?"""
        try:
            real = path.expanduser().resolve()
        except OSError:
            return False
        if real == self.vault or self.vault in real.parents or not self._type_ok(real.name):
            return False
        return any(real == root or root in real.parents for root in self._roots())

    def outside_files(self) -> list[Path]:
        """The files the granted outside paths hold (allowed types, no hidden folders), at most
        ``MAX_OUTSIDE_FILES``."""
        found: list[Path] = []
        for root in self._roots():
            if root.is_file():
                if self.may_read_outside(root):
                    found.append(root)
                continue
            for folder, dirs, files in os.walk(root):
                dirs[:] = sorted(d for d in dirs if not d.startswith("."))
                for name in sorted(files):
                    path = Path(folder) / name
                    if self._type_ok(name) and self.may_read_outside(path):
                        found.append(path)
                    if len(found) >= MAX_OUTSIDE_FILES:
                        return found
        return found

    def read_outside(self, path: Path) -> str | None:
        """The text of a granted outside file, or None (not granted, too big, not text)."""
        if not self.may_read_outside(path):
            return None
        try:
            data = path.read_bytes()
        except OSError:
            return None
        if len(data) > MAX_OUTSIDE_BYTES or b"\x00" in data:
            return None
        try:
            return data.decode("utf-8-sig")
        except UnicodeDecodeError:
            return None

    def describe(self) -> str:
        """One line for the composer: what the AI can read."""
        if self.grant is None:
            return "AI can read: nothing yet (asks first)"
        types = ", ".join(self.grant.file_types) or "no files"
        line = f"AI can read: this vault ({types})"
        if self.grant.allow_paths:
            n = len(self.grant.allow_paths)
            line += f" + {n} outside path{'s' * (n != 1)}"
        if self.grant.exclude:
            line += f", {len(self.grant.exclude)} excluded"
        return line


def check_outside_path(text: str, vault: Path) -> str:
    """Why ``text`` cannot be granted as an outside path ("" when it can)."""
    raw = text.strip()
    if not raw:
        return "Type a path."
    path = Path(raw).expanduser()
    if not path.is_absolute():
        return "Use a full path (starting with / or ~)."
    real = path.resolve()
    if not real.exists():
        return "No such file or folder."
    vault_real = vault.expanduser().resolve()
    if real == vault_real or vault_real in real.parents:
        return "That is inside this vault already."
    return ""


_PATH = re.compile(r"""(?<![\w/~.])(~?/[^\s'"`<>()\[\]]+)""")


def paths_in(text: str, vault: Path) -> list[Path]:
    """Folders and files outside ``vault`` that ``text`` names by a full path (``/…`` or ``~/…``)
    and that exist, each once, resolved."""
    found: list[Path] = []
    for m in _PATH.finditer(text):
        raw = m.group(1).rstrip(".,;:!?")
        if check_outside_path(raw, vault):
            continue
        path = Path(raw).expanduser().resolve()
        if path not in found:
            found.append(path)
    return found


def unique(items: Iterable[str]) -> list[str]:
    return list(dict.fromkeys(i for i in items if i))
