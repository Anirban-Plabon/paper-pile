"""Global and per-vault TOML configuration with defaults.

Load order: defaults -> global (``~/.config/paper-pile/config.toml``) ->
vault (``<vault>/.paper-pile/vault.toml``). Each layer is saved on its own,
so a file only ever contains the values the user changed.
"""

import copy
import io
import logging
import shutil
import tomllib
from pathlib import Path
from typing import Any, Literal

import platformdirs
import tomli_w

from paper_pile.core.fsutil import atomic_write_bytes

log = logging.getLogger("paper_pile.config")

Scope = Literal["global", "vault"]

DEFAULTS: dict[str, Any] = {
    "profile": {"name": "", "avatar": ""},
    "appearance": {"theme": "system", "accent": "blue", "density": "comfortable"},
    "editor": {
        "font_family": "monospace",
        "code_font_family": "monospace",
        "font_size": 14,
        "line_height": 1.6,
        "word_wrap": True,
        "line_numbers": False,
        "tab_size": 4,
        "spell_check": False,
        "default_mode": "live",
        "auto_title": True,
        "block_spacing": True,
        "tidy_button": True,
        "page_view": "off",  # off | lines | pages (PLAN §4.17)
        "page_view_last": "lines",  # the style the ⋯ menu turns on
    },
    "print": {"paper": "A4"},
    "general": {"language": "en"},
    "vault": {
        "templates_folder": ".template",
        "daily_notes_folder": ".daily-notes",
        "images_folder": ".image",
        "show_templates": True,
        "show_daily_notes": True,
        "daily_notes_format": "YYYY-MM-DD",
        "daily_notes_template": "",
    },
    "ai": {
        "host": "http://localhost:11434",
        "model": "gemma4:12b",
        "embed_model": "",
        "context_budget": 6000,
        "instructions": "",
        "instructions_from": "text",  # text | file
        "instructions_file": "",
        "temperature": 0.8,
        "top_p": 0.9,
        "num_ctx": 0,  # 0 = the model's default
        "keep_alive": 5,  # minutes
        "history_turns": 12,
        "save_chats": True,
        "keep_chats_days": 0,  # 0 = forever
        "chats_folder": ".memory",  # vault-relative, or absolute
    },
    "paste": {"smart_paste": True},
    "features": {"ai": True, "calendar": True},  # PLAN §4.18
    "settings": {"minimal": True},  # Settings lists only the essential rows
}


def global_config_path() -> Path:
    return Path(platformdirs.user_config_dir("paper-pile")) / "config.toml"


def vault_config_path(vault: Path) -> Path:
    return vault / ".paper-pile" / "vault.toml"


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Return a new dict: ``override`` merged over ``base``, recursing into tables."""
    result = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result


def _read_toml(path: Path) -> tuple[dict[str, Any], bool]:
    """Read a TOML file. Returns (data, corrupt). Missing file is not corrupt."""
    try:
        with path.open("rb") as f:
            return tomllib.load(f), False
    except FileNotFoundError:
        return {}, False
    except (tomllib.TOMLDecodeError, OSError):
        log.warning("could not parse %s; ignoring it", path, exc_info=True)
        return {}, True


def _write_toml_atomic(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    buf = io.BytesIO()
    tomli_w.dump(data, buf)
    atomic_write_bytes(path, buf.getvalue())


class Config:
    """Layered configuration. Dotted keys address nested tables (``"ai.model"``)."""

    def __init__(self, global_path: Path | None = None, vault: Path | None = None) -> None:
        self._paths: dict[Scope, Path | None] = {
            "global": global_path if global_path is not None else global_config_path(),
            "vault": vault_config_path(vault) if vault is not None else None,
        }
        self._layers: dict[Scope, dict[str, Any]] = {"global": {}, "vault": {}}
        self._corrupt: set[Scope] = set()
        self.reload()

    def reload(self) -> None:
        self._corrupt.clear()
        for scope, path in self._paths.items():
            if path is None:
                self._layers[scope] = {}
                continue
            data, corrupt = _read_toml(path)
            self._layers[scope] = data
            if corrupt:
                self._corrupt.add(scope)

    @property
    def values(self) -> dict[str, Any]:
        """Fully merged configuration (defaults -> global -> vault)."""
        merged = deep_merge(DEFAULTS, self._layers["global"])
        return deep_merge(merged, self._layers["vault"])

    def get(self, key: str, default: Any = None) -> Any:
        node: Any = self.values
        for part in key.split("."):
            if not isinstance(node, dict) or part not in node:
                return default
            node = node[part]
        return node

    def set(self, key: str, value: Any, scope: Scope = "global") -> None:
        """Set ``key`` in one layer (in memory); call :meth:`save` to persist."""
        if self._paths[scope] is None:
            raise ValueError(f"no {scope} config path (no vault open?)")
        *parents, leaf = key.split(".")
        node = self._layers[scope]
        for part in parents:
            child = node.get(part)
            if not isinstance(child, dict):
                child = node[part] = {}
            node = child
        node[leaf] = value

    def unset(self, key: str, scope: Scope = "global") -> None:
        """Remove ``key`` from one layer (it falls back to the layer below); empty tables go too."""
        *parents, leaf = key.split(".")
        chain: list[dict[str, Any]] = [self._layers[scope]]
        for part in parents:
            child = chain[-1].get(part)
            if not isinstance(child, dict):
                return
            chain.append(child)
        chain[-1].pop(leaf, None)
        for part, node in zip(reversed(parents), reversed(chain[1:]), strict=True):
            if node:
                break
            chain[chain.index(node) - 1].pop(part, None)

    def layer(self, scope: Scope) -> dict[str, Any]:
        """What one layer holds on its own (a copy)."""
        return copy.deepcopy(self._layers[scope])

    def save(self, scope: Scope = "global") -> None:
        path = self._paths[scope]
        if path is None:
            raise ValueError(f"no {scope} config path (no vault open?)")
        if scope in self._corrupt and path.exists():
            shutil.copy2(path, path.with_name(path.name + ".bak"))
            self._corrupt.discard(scope)
        _write_toml_atomic(path, self._layers[scope])
