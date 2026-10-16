"""Which provider the app uses, from the configuration."""

import os

from paper_pile.core.ai.fake import FakeProvider
from paper_pile.core.ai.ollama import DEFAULT_HOST, OllamaProvider
from paper_pile.core.ai.provider import Provider
from paper_pile.core.config import Config


def make_provider(config: Config | None) -> Provider:
    """The configured provider (``ai.host``, ``ai.model``, ``ai.embed_model``). With the
    environment variable ``PAPER_PILE_FAKE_AI=1`` a stand-in that needs no model is used
    (``PAPER_PILE_FAKE_AI_REPLY`` sets the text it answers with)."""
    if os.environ.get("PAPER_PILE_FAKE_AI"):
        return FakeProvider(reply=os.environ.get("PAPER_PILE_FAKE_AI_REPLY") or None)
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
