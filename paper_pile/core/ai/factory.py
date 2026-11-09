"""Which provider the app uses, from the configuration (``ai.provider``, PLAN §4.30).

Every backend is built here and nowhere else; the rest of the app only knows :class:`Provider`.
A new backend is one module implementing it plus one entry in :func:`make_provider`.
"""

import asyncio
import json
import logging
import os
from collections.abc import AsyncIterator, Awaitable, Sequence
from pathlib import Path

from paper_pile.core.ai.backends import BACKENDS, api_key, settings_for, worth_probing
from paper_pile.core.ai.fake import FakeProvider
from paper_pile.core.ai.install import ai_available, ai_unavailable
from paper_pile.core.ai.provider import (
    ChatMessage,
    Finish,
    GenerationOptions,
    Health,
    Provider,
    ProviderUnavailableError,
    Reasoning,
    is_chat_model,
)
from paper_pile.core.config import Config

log = logging.getLogger("paper_pile.ai")


class MissingProvider:
    """Stands in while the AI cannot run (not started with ``--ai``): never reached (AI is off
    then), but whatever asks gets the reason."""

    host = ""
    label = "AI"
    local = True  # sends nothing anywhere
    sizes_window = False

    def __init__(self, reason: str = "") -> None:
        self.reason = reason or ai_unavailable()

    def missing_model(self, model: str) -> str:
        return self.reason

    async def chat(
        self,
        messages: Sequence[ChatMessage],
        *,
        model: str | None = None,
        options: GenerationOptions | None = None,
    ) -> AsyncIterator[str | Reasoning | Finish]:
        raise ProviderUnavailableError(self.reason)
        yield ""  # makes this an async generator, like the real ones

    async def models(self) -> list[str]:
        return []

    async def context_length(self, model: str | None = None) -> int | None:
        return None

    async def memory_use(self, model: str, num_ctx: int) -> tuple[int, int] | None:
        return None

    async def health(self) -> Health:
        return Health(False, self.reason)

    async def preload(self, model: str, options: GenerationOptions) -> bool:
        return False


def make_provider(config: Config | None) -> Provider:
    """The configured provider (``ai.provider``, ``ai.host``, ``ai.model``, ``ai.api_key_env``).
    With the environment variable ``PAPER_PILE_FAKE_AI=1`` a stand-in that needs no model is
    used (``PAPER_PILE_FAKE_AI_REPLY`` sets the text it answers with, ``…_THINKING`` its
    reasoning, ``…_SCRIPT`` a JSON file with a list of answers given in turn — for checking AI
    edits; ``…_DELAY`` the seconds before each word, to check what shows while it waits).
    The backends are imported only here."""
    if os.environ.get("PAPER_PILE_FAKE_AI"):
        script = _fake_script(os.environ.get("PAPER_PILE_FAKE_AI_SCRIPT", ""))
        fake = FakeProvider(
            delay=float(os.environ.get("PAPER_PILE_FAKE_AI_DELAY") or 0.02),
            reply=os.environ.get("PAPER_PILE_FAKE_AI_REPLY") or None,
            script=script,
        )
        fake.thinking = os.environ.get("PAPER_PILE_FAKE_AI_THINKING", "")
        return fake
    if not ai_available():
        return MissingProvider()
    get = config.get if config is not None else (lambda _key, default=None: default)
    return build_provider(
        str(get("ai.provider", "ollama") or "ollama"),
        host=str(get("ai.host", "") or ""),
        model=str(get("ai.model", "") or ""),
        api_key_env=str(get("ai.api_key_env", "") or ""),
    )


def build_provider(
    kind: str, *, host: str = "", model: str = "", api_key_env: str = ""
) -> Provider:
    """Backend ``kind`` (``ai.provider``) at ``host`` ("" = its default)."""
    if kind == "ollama":
        from paper_pile.core.ai.ollama import OllamaProvider

        return OllamaProvider(host=host, model=model)
    if kind == "vllm" or kind == "openai":
        from paper_pile.core.ai.openai_compat import Flavor, OpenAICompatProvider

        flavor: Flavor = "vllm" if kind == "vllm" else "openai"
        key = api_key(api_key_env)
        return OpenAICompatProvider(host=host, model=model, flavor=flavor, api_key=key)
    if kind == "antigravity":
        from paper_pile.core.ai.antigravity_cli import AntigravityCliProvider

        return AntigravityCliProvider(model=model)
    log.warning("unknown AI provider %r", kind)
    return MissingProvider(f"Unknown AI provider “{kind}” — pick one in Settings → AI.")


async def shutdown_providers() -> None:
    """End what a backend keeps between requests (the app's shutdown, a tool's end): the
    Antigravity CLI's processes started ahead and the data it kept. Nothing for the others."""
    import sys

    agy = sys.modules.get("paper_pile.core.ai.antigravity_cli")
    if agy is not None:
        await agy.end_session()  # processes started ahead ended, its data wiped


async def closing[T](job: Awaitable[T]) -> T:
    """``job``, then :func:`shutdown_providers` — for a tool's ``asyncio.run``, whose loop
    ends with it (a process started ahead must not outlive its loop)."""
    try:
        return await job
    finally:
        await shutdown_providers()


async def probe_backends(config: Config) -> dict[str, Health | None]:
    """Each backend's health with its own settings (Settings → AI lists which are there); None
    for one not asked (:func:`backends.worth_probing`). Never raises; a few seconds at most."""
    if os.environ.get("PAPER_PILE_FAKE_AI") or not ai_available():
        return dict.fromkeys(BACKENDS)
    kinds = [k for k in BACKENDS if worth_probing(config, k)]
    providers = [build_provider(k, **settings_for(config, k)) for k in kinds]
    found = await asyncio.gather(*(p.health() for p in providers))
    return {k: dict(zip(kinds, found, strict=True)).get(k) for k in BACKENDS}


def _fake_script(path: str) -> list[str] | None:
    if not path:
        return None
    try:
        replies = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return [str(r) for r in replies] if isinstance(replies, list) else None


def chat_model(config: Config | None, listed: Sequence[str] = ()) -> str:
    """The model chat uses: ``ai.model`` from the configuration; when that is empty
    (automatic), the first model the backend lists (``listed``); "" when none is known yet."""
    value = str(config.get("ai.model", "") or "") if config is not None else ""
    return value or next((m for m in listed if is_chat_model(m)), "")


def generation_options(config: Config | None) -> GenerationOptions:
    """Temperature, top-p, context window and keep-alive from Settings → AI → Advanced. A context
    window of 0 (automatic) is left out here: the engine sends the window it works out."""
    from paper_pile.core.settings import sanitized  # settings imports config, not the reverse

    if config is None:
        return GenerationOptions()
    values = sanitized(config.values)
    num_ctx = int(values["ai.num_ctx"])
    return GenerationOptions(
        temperature=float(values["ai.temperature"]),
        top_p=float(values["ai.top_p"]),
        num_ctx=num_ctx or None,
        keep_alive_min=int(values["ai.keep_alive"]),
    )
