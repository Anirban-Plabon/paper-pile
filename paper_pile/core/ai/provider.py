"""The AI provider interface. The app talks to ``Provider`` only; the backends (``ollama.py``,
``openai_compat.py``: vLLM and any OpenAI-compatible API) and the test double implement it, and
``factory.py`` picks one from ``ai.provider`` (PLAN §4.30).

Nothing here knows about the UI or a particular backend or model: chat, slash commands and
context building only ever see this protocol, so another backend can be dropped in.
"""

import ipaddress
from collections.abc import AsyncIterator, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol
from urllib.parse import urlsplit

Role = Literal["system", "user", "assistant"]


def is_local_host(host: str) -> bool:
    """Does ``host`` (``http://localhost:11434``, ``10.0.0.5:8000``) run on this computer? Only
    then do notes sent to the AI stay on it (PLAN §4.26). An empty host is not local."""
    raw = host.strip()
    name = urlsplit(raw if "://" in raw else "http://" + raw).hostname or ""
    if name == "localhost":
        return True
    try:
        return ipaddress.ip_address(name).is_loopback
    except ValueError:
        return False


# model names that are not chat models (backends list embedding, speech and image models too)
NOT_CHAT = ("embed", "whisper", "tts", "dall-e", "moderation", "transcribe", "image")


def is_chat_model(name: str) -> bool:
    return not any(word in name.lower() for word in NOT_CHAT)


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
    details: dict[str, str] = field(default_factory=dict)  # model -> "9B · llama · 5.4 GB"


@dataclass(frozen=True, slots=True)
class GenerationOptions:
    """How the model answers (Settings → AI → Advanced). ``None`` leaves the backend's default.
    These are requests, not promises: a backend drops what it cannot do (a hosted API has no
    per-request window, no keep-alive, maybe no repeat penalty)."""

    temperature: float | None = None
    top_p: float | None = None
    num_ctx: int | None = None  # the model's context window, in tokens
    num_predict: int | None = None  # the longest answer, in tokens
    keep_alive_min: int | None = None  # how long the model stays loaded after a reply
    schema: Mapping[str, Any] | None = None  # a JSON schema the answer must follow (PLAN §4.29)
    think: bool | None = None  # False: a thinking model answers without reasoning first
    repeat_penalty: float | None = None  # > 1 makes tokens just used less likely (loops)


class ProviderError(Exception):
    """A request to the AI backend failed; the message is fit to show to the user."""


class RepeatLoopError(ProviderError):
    """The model kept repeating itself and the backend stopped it (Ollama: "token repeat limit
    reached"); asking again with more variety usually works."""


class ProviderUnavailableError(ProviderError):
    """The backend cannot be reached (not running, wrong address, offline)."""


class ModelNotFoundError(ProviderError):
    """The chosen model is not on the backend."""


class Provider(Protocol):
    host: str  # where requests go ("" when the backend has no address)
    label: str  # the backend's name for the user: "Ollama", "vLLM", "OpenAI-compatible API"
    local: bool  # notes sent to it stay on this computer (the consent card says so otherwise)
    # the app picks the context window per request and can measure what fits the GPU (window.py);
    # else the server's window is fixed and only ``context_length`` is used
    sizes_window: bool

    def missing_model(self, model: str) -> str:
        """What to tell the user when ``model`` is not on the backend (how to get it)."""
        ...

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

    async def memory_use(self, model: str, num_ctx: int) -> tuple[int, int] | None:
        """``model`` loaded with a ``num_ctx`` window: its size and the part of it in GPU memory,
        in bytes; None when unknown (always, unless :attr:`sizes_window`). Never raises."""
        ...

    async def health(self) -> Health:
        """Can the backend be reached? Never raises."""
        ...

    async def preload(self, model: str, options: GenerationOptions) -> bool:
        """Load ``model`` now, as a request with ``options`` would (its window, keep-alive), so
        the first answer does not wait for it; False when this backend loads nothing itself (a
        server keeps its model loaded). Never raises."""
        ...
