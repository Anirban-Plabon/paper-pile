"""What the app knows about each AI backend before talking to it (PLAN §4.30): its name, default
address and API-key hint; the per-backend settings kept when the user switches backends; and
the short status shown next to each backend in Settings. No HTTP and no UI here.
"""

import os
import re
from dataclasses import dataclass
from typing import Any

from paper_pile.core.ai.provider import Health, is_local_host
from paper_pile.core.config import Config


@dataclass(frozen=True, slots=True)
class Backend:
    key: str  # ai.provider
    label: str
    default_host: str  # "" = not a server (a program on this computer): no address setting
    key_hint: str  # placeholder of "API key variable"; "" = this backend takes no key
    loads_models: bool = False  # loads a model on demand (so "Load model at start" helps)


BACKENDS: dict[str, Backend] = {
    b.key: b
    for b in (
        Backend("ollama", "Ollama", "http://localhost:11434", "", loads_models=True),
        Backend("vllm", "vLLM", "http://localhost:8000/v1", "only with --api-key"),
        Backend(
            "openai", "OpenAI-compatible API", "https://api.openai.com/v1", "e.g. OPENAI_API_KEY"
        ),
        Backend("antigravity", "Antigravity CLI", "", ""),  # a program: no address, no key
    )
}
# kept per backend: switching to another one and back restores them (ai.saved.<backend>)
PER_BACKEND = ("host", "model", "api_key_env")
ENV_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def backend(kind: str) -> Backend:
    return BACKENDS.get(kind, BACKENDS["ollama"])


def api_key(variable: str) -> str:
    """The API key from the environment variable named ``variable`` ("" without one). Only the
    variable's name is in the settings, so a key never lands in a config file."""
    return os.environ.get(variable, "") if ENV_NAME.fullmatch(variable) else ""


def switch_backend(config: Config, new: str) -> set[str]:
    """Make ``new`` the backend: the current one's address / model / key variable are kept in
    ``ai.saved.<old>`` and ``new``'s come back (or the defaults: its address, the first model it
    lists). All in the global layer (ai.provider is global only). Returns the changed keys."""
    old = str(config.get("ai.provider") or "ollama")
    if new == old:
        return set()
    own = config.layer("global").get("ai", {})
    saved: dict[str, Any] = dict(own.get("saved") or {})
    saved[old] = {k: own[k] for k in PER_BACKEND if own.get(k)}
    restored = saved.pop(new, {}) or {}
    if saved:
        config.set("ai.saved", saved, "global")
    for k in PER_BACKEND:
        if restored.get(k):
            config.set(f"ai.{k}", restored[k], "global")
        else:
            config.unset(f"ai.{k}", "global")
    config.set("ai.provider", new, "global")
    return {"ai.provider", "ai.saved", *(f"ai.{k}" for k in PER_BACKEND)}


def settings_for(config: Config, kind: str) -> dict[str, str]:
    """``kind``'s address / model / key variable: the live ones when it is the current backend,
    else what was kept for it."""
    if kind == str(config.get("ai.provider") or "ollama"):
        return {k: str(config.get(f"ai.{k}", "") or "") for k in PER_BACKEND}
    kept = (config.get("ai.saved") or {}).get(kind) or {}
    return {k: str(kept.get(k, "") or "") for k in PER_BACKEND}


def worth_probing(config: Config, kind: str) -> bool:
    """Ask a backend whether it is there only when it is the chosen one or runs on this
    computer: a hosted API the user did not pick is never contacted."""
    if kind == str(config.get("ai.provider") or "ollama"):
        return True
    return is_local_host(settings_for(config, kind)["host"] or backend(kind).default_host)


def status(health: Health | None) -> str:
    """A few words for the backend list: "6 models", "not reachable", "" (not asked)."""
    if health is None:
        return ""
    if not health.ok:
        return "key refused" if "API key" in health.message else "not reachable"
    n = len(health.models)
    return "no models" if n == 0 else f"{n} model" + ("s" if n > 1 else "")


def hints(key: str, kind: str, value: str = "") -> tuple[str, str] | None:
    """``(help, placeholder)`` of an AI setting that depends on the backend; None for others.
    ``value`` is the setting's current value (the key variable: says whether it is set)."""
    b = backend(kind)
    if key == "ai.host":
        return "", b.default_host  # empty = this
    if key == "ai.api_key_env":
        if not value:
            return "A variable's name, not the key", b.key_hint
        return ("Set" if api_key(value) else "Not set — export it, then restart"), b.key_hint
    if key == "ai.model":
        return "", "First listed"
    return None
