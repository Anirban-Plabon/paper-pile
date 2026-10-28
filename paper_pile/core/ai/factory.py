"""Which provider the app uses, from the configuration."""

import os
from collections.abc import AsyncIterator, Sequence

from paper_pile.core.ai.fake import FakeProvider
from paper_pile.core.ai.install import NOT_INSTALLED, ai_installed
from paper_pile.core.ai.provider import (
    DEFAULT_HOST,
    ChatMessage,
    GenerationOptions,
    Health,
    Provider,
    ProviderUnavailableError,
)
from paper_pile.core.config import Config


class MissingProvider:
    """Stands in while the ``ai`` extra is not installed: never reached (AI is off then), but
    whatever asks gets the install hint instead of an ImportError."""

    host = ""

    async def chat(
        self,
        messages: Sequence[ChatMessage],
        *,
        model: str | None = None,
        options: GenerationOptions | None = None,
    ) -> AsyncIterator[str]:
        raise ProviderUnavailableError(NOT_INSTALLED)
        yield ""  # makes this an async generator, like the real ones

    async def embed(self, texts: Sequence[str], *, model: str | None = None) -> list[list[float]]:
        raise ProviderUnavailableError(NOT_INSTALLED)

    async def models(self) -> list[str]:
        return []

    async def health(self) -> Health:
        return Health(False, NOT_INSTALLED)


def make_provider(config: Config | None) -> Provider:
    """The configured provider (``ai.host``, ``ai.model``, ``ai.embed_model``). With the
    environment variable ``PAPER_PILE_FAKE_AI=1`` a stand-in that needs no model is used
    (``PAPER_PILE_FAKE_AI_REPLY`` sets the text it answers with). ``ollama`` is imported only
    here, so the app starts without the ``ai`` extra."""
    if os.environ.get("PAPER_PILE_FAKE_AI"):
        return FakeProvider(reply=os.environ.get("PAPER_PILE_FAKE_AI_REPLY") or None)
    if not ai_installed():
        return MissingProvider()
    from paper_pile.core.ai.ollama import OllamaProvider

    get = config.get if config is not None else (lambda _key, default=None: default)
    return OllamaProvider(
        host=str(get("ai.host", DEFAULT_HOST)),
        model=str(get("ai.model", "gemma4:12b")),
        embed_model=str(get("ai.embed_model", "")),
    )


def chat_model(provider: Provider, config: Config | None) -> str:
    """The model chat uses: ``ai.model`` from the configuration."""
    value = config.get("ai.model", "gemma4:12b") if config is not None else "gemma4:12b"
    return str(value or "gemma4:12b")


def generation_options(config: Config | None) -> GenerationOptions:
    """Temperature, top-p, context window and keep-alive from Settings → AI → Advanced. A context
    window of 0 means the model's own default."""
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
