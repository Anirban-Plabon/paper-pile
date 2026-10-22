"""``OllamaProvider``: a local Ollama server (https://ollama.com), reached with the official
``ollama`` library. Errors are turned into :class:`ProviderError` with messages for the user."""

import logging
from collections.abc import AsyncIterator, Sequence
from typing import Any

import httpx
import ollama

from paper_pile.core.ai.provider import (
    ChatMessage,
    GenerationOptions,
    Health,
    ModelNotFoundError,
    ProviderError,
    ProviderUnavailableError,
)

log = logging.getLogger("paper_pile.ai")

DEFAULT_HOST = "http://localhost:11434"
NOT_RUNNING = "Ollama isn't running — start it with `ollama serve`."
HEALTH_TIMEOUT_S = 3.0


def describe_model(parameter_size: str | None, family: str | None, size: int | None) -> str:
    """``"9B · gemma3 · 5.4 GB"`` from whatever Ollama reports (parts it lacks are left out)."""
    parts = [p for p in (parameter_size, family) if p]
    if size:
        parts.append(f"{size / 1e9:.1f} GB")
    return " · ".join(parts)


def ollama_options(options: GenerationOptions | None) -> dict[str, Any]:
    """``options`` / ``keep_alive`` arguments for ``AsyncClient.chat`` (only the set ones)."""
    if options is None:
        return {}
    model = {
        k: v
        for k, v in (
            ("temperature", options.temperature),
            ("top_p", options.top_p),
            ("num_ctx", options.num_ctx),
        )
        if v is not None
    }
    out: dict[str, Any] = {"options": model} if model else {}
    if options.keep_alive_min is not None:
        out["keep_alive"] = f"{options.keep_alive_min}m"
    return out


class OllamaProvider:
    def __init__(
        self,
        host: str = DEFAULT_HOST,
        model: str = "gemma4:12b",
        embed_model: str = "",
        *,
        timeout: float | None = 300.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.host = host or DEFAULT_HOST
        self.model = model
        self.embed_model = embed_model
        extra: dict[str, Any] = {"transport": transport} if transport is not None else {}
        self._client = ollama.AsyncClient(host=self.host, timeout=timeout, **extra)
        self._probe = ollama.AsyncClient(host=self.host, timeout=HEALTH_TIMEOUT_S, **extra)

    # ---- chat ------------------------------------------------------------------------------

    async def chat(
        self,
        messages: Sequence[ChatMessage],
        *,
        model: str | None = None,
        options: GenerationOptions | None = None,
    ) -> AsyncIterator[str]:
        name = model or self.model
        payload = [{"role": m.role, "content": m.content} for m in messages]
        extra = ollama_options(options)
        try:
            stream = await self._client.chat(model=name, messages=payload, stream=True, **extra)
            async for part in stream:
                text = part.message.content if part.message else ""
                if text:  # reasoning ("thinking") text is not part of the answer
                    yield text
        except Exception as exc:
            raise self._friendly(exc, name) from exc

    async def embed(self, texts: Sequence[str], *, model: str | None = None) -> list[list[float]]:
        name = model or self.embed_model
        if not name:
            raise ProviderError("No embedding model is set.")
        try:
            result = await self._client.embed(model=name, input=list(texts))
        except Exception as exc:
            raise self._friendly(exc, name) from exc
        return [list(v) for v in result.embeddings]

    # ---- state -----------------------------------------------------------------------------

    async def models(self) -> list[str]:
        return sorted(await self._listing())

    async def _listing(self) -> dict[str, str]:
        """Installed models and a one-line description of each."""
        try:
            listing = await self._probe.list()
        except Exception as exc:
            raise self._friendly(exc, "") from exc
        out: dict[str, str] = {}
        for m in listing.models:
            if m.model:
                d = m.details
                out[m.model] = describe_model(
                    d.parameter_size if d else None, d.family if d else None, m.size
                )
        return out

    async def health(self) -> Health:
        try:
            listing = await self._listing()
        except ProviderError as exc:
            return Health(False, str(exc))
        if not listing:
            return Health(True, "Ollama is running but has no models: `ollama pull gemma4:12b`", [])
        return Health(True, "", sorted(listing), listing)

    # ---- errors ----------------------------------------------------------------------------

    @staticmethod
    def _friendly(exc: Exception, model: str) -> ProviderError:
        if isinstance(exc, ProviderError):
            return exc
        if isinstance(exc, ollama.ResponseError):
            if exc.status_code == 404:
                return ModelNotFoundError(
                    f"The model “{model}” is not installed — run `ollama pull {model}`."
                )
            return ProviderError(f"Ollama said: {exc.error}")
        if isinstance(exc, ConnectionError | httpx.TransportError):
            return ProviderUnavailableError(NOT_RUNNING)
        log.exception("unexpected AI error")
        return ProviderError(f"Something went wrong talking to Ollama: {exc}")
