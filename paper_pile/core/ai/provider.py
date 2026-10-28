"""The AI provider interface. The app talks to ``Provider``; ``OllamaProvider`` is the real one.

Nothing here knows about the UI: chat, slash commands and context building only ever see this
protocol, so another backend (or a test double) can be dropped in.
"""

from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass, field
from typing import Literal, Protocol

Role = Literal["system", "user", "assistant"]

DEFAULT_HOST = "http://localhost:11434"  # Ollama's


@dataclass(frozen=True, slots=True)
class ChatMessage:
    role: Role
    content: str


@dataclass(frozen=True, slots=True)
class Health:
    ok: bool
    message: str = ""  # what to tell the user when not ok
    models: list[str] = field(default_factory=list)
    details: dict[str, str] = field(default_factory=dict)  # model -> "9B · gemma3 · 5.4 GB"


@dataclass(frozen=True, slots=True)
class GenerationOptions:
    """How the model answers (Settings → AI → Advanced). ``None`` leaves the backend's default."""

    temperature: float | None = None
    top_p: float | None = None
    num_ctx: int | None = None  # the model's context window, in tokens
    keep_alive_min: int | None = None  # how long the model stays loaded after a reply


class ProviderError(Exception):
    """A request to the AI backend failed; the message is fit to show to the user."""


class ProviderUnavailableError(ProviderError):
    """The backend cannot be reached (for Ollama: it is not running)."""


class ModelNotFoundError(ProviderError):
    """The chosen model is not installed."""


class Provider(Protocol):
    host: str

    def chat(
        self,
        messages: Sequence[ChatMessage],
        *,
        model: str | None = None,
        options: GenerationOptions | None = None,
    ) -> AsyncIterator[str]:
        """The reply to ``messages`` as it is generated, piece by piece. Cancelling the task that
        iterates it stops the generation."""
        ...

    async def embed(self, texts: Sequence[str], *, model: str | None = None) -> list[list[float]]:
        """One vector per text (not used in phase 1)."""
        ...

    async def models(self) -> list[str]:
        """Names of the installed chat models."""
        ...

    async def context_length(self, model: str | None = None) -> int | None:
        """The longest context ``model`` takes, in tokens; None when unknown. Never raises."""
        ...

    async def health(self) -> Health:
        """Can the backend be reached? Never raises."""
        ...
