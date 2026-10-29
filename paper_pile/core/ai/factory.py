"""Which provider the app uses, from the configuration."""

import os
from collections.abc import AsyncIterator, Sequence

from paper_pile.core.ai.fake import FakeProvider
from paper_pile.core.ai.install import ai_available, ai_unavailable
from paper_pile.core.ai.provider import (
    DEFAULT_HOST,
    ChatMessage,
    Finish,
    GenerationOptions,
    Health,
    Provider,
    ProviderUnavailableError,
    Reasoning,
)
from paper_pile.core.config import Config


class MissingProvider:
    """Stands in while the AI cannot run (not started with ``--ai``, or ``ollama`` missing):
    never reached (AI is off then), but whatever asks gets the reason, not an ImportError."""

    host = ""

    async def chat(
        self,
        messages: Sequence[ChatMessage],
        *,
        model: str | None = None,
        options: GenerationOptions | None = None,
    ) -> AsyncIterator[str | Reasoning | Finish]:
        raise ProviderUnavailableError(ai_unavailable())
        yield ""  # makes this an async generator, like the real ones

    async def models(self) -> list[str]:
        return []

    async def context_length(self, model: str | None = None) -> int | None:
        return None

    async def health(self) -> Health:
        return Health(False, ai_unavailable())


def make_provider(config: Config | None) -> Provider:
    """The configured provider (``ai.host``, ``ai.model``). With the
    environment variable ``PAPER_PILE_FAKE_AI=1`` a stand-in that needs no model is used
    (``PAPER_PILE_FAKE_AI_REPLY`` sets the text it answers with, ``…_THINKING`` its reasoning).
    ``ollama`` is imported only here, so the app also starts without it."""
    if os.environ.get("PAPER_PILE_FAKE_AI"):
        fake = FakeProvider(reply=os.environ.get("PAPER_PILE_FAKE_AI_REPLY") or None)
        fake.thinking = os.environ.get("PAPER_PILE_FAKE_AI_THINKING", "")
        return fake
    if not ai_available():
        return MissingProvider()
    from paper_pile.core.ai.ollama import OllamaProvider

    get = config.get if config is not None else (lambda _key, default=None: default)
    return OllamaProvider(
        host=str(get("ai.host", DEFAULT_HOST)),
        model=str(get("ai.model", "gemma4:12b")),
    )


def chat_model(provider: Provider, config: Config | None) -> str:
    """The model chat uses: ``ai.model`` from the configuration."""
    value = config.get("ai.model", "gemma4:12b") if config is not None else "gemma4:12b"
    return str(value or "gemma4:12b")


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
