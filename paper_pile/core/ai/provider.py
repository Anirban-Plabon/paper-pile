"""The AI provider interface. The app talks to ``Provider``; ``OllamaProvider`` is the real one.

Nothing here knows about the UI: chat, slash commands and context building only ever see this
protocol, so another backend (or a test double) can be dropped in.
"""

import ipaddress
from collections.abc import AsyncIterator, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol
from urllib.parse import urlsplit

Role = Literal["system", "user", "assistant"]

DEFAULT_HOST = "http://localhost:11434"  # Ollama's


def is_local_host(host: str) -> bool:
    """Does ``host`` (``http://localhost:11434``, ``10.0.0.5:11434``) run on this computer? Only
    then do notes sent to the AI stay on it (PLAN §4.26)."""
    raw = host.strip() or DEFAULT_HOST
    name = urlsplit(raw if "://" in raw else "http://" + raw).hostname or ""
    if name == "localhost":
        return True
    try:
        return ipaddress.ip_address(name).is_loopback
    except ValueError:
        return False


@dataclass(frozen=True, slots=True)
class ChatMessage:
    role: Role
    content: str


@dataclass(frozen=True, slots=True)
class Reasoning:
    """A piece of a thinking model's reasoning: streamed along with the answer, not part of it."""

    text: str


@dataclass(frozen=True, slots=True)
class Finish:
    """The last piece of an answer: why it ended (``"stop"``: the model was done; ``"length"``:
    it reached the answer limit). An answer without one was stopped or failed. The token counts
    are what the backend reports (None when it does not): the prompt tokens it evaluated (fewer
    than the prompt when the start was cached) and the answer's."""

    reason: str
    prompt_tokens: int | None = field(default=None, compare=False)
    eval_tokens: int | None = field(default=None, compare=False)


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
    num_predict: int | None = None  # the longest answer, in tokens
    keep_alive_min: int | None = None  # how long the model stays loaded after a reply
    schema: Mapping[str, Any] | None = None  # a JSON schema the answer must follow (PLAN §4.29)
    think: bool | None = None  # False: a thinking model answers without reasoning first


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
    ) -> AsyncIterator[str | Reasoning | Finish]:
        """The reply to ``messages`` as it is generated, piece by piece (a thinking model's
        reasoning as :class:`Reasoning` pieces), ending with a :class:`Finish`. Cancelling the
        task that iterates it stops the generation."""
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
