"""``OllamaProvider``: a local Ollama server (https://ollama.com), reached with the official
``ollama`` library. Errors are turned into :class:`ProviderError` with messages for the user."""

import logging
from collections.abc import AsyncIterator, Sequence
from typing import Any

import httpx
import ollama

from paper_pile.core.ai.provider import (
    DEFAULT_HOST,
    ChatMessage,
    Finish,
    GenerationOptions,
    Health,
    ModelNotFoundError,
    ProviderError,
    ProviderUnavailableError,
    Reasoning,
    is_local_host,
)

log = logging.getLogger("paper_pile.ai")

NOT_RUNNING = "Ollama isn't running — start it with `ollama serve`."


def not_running(host: str) -> str:
    """What to say when Ollama cannot be reached: start it here, or check the other computer."""
    return NOT_RUNNING if is_local_host(host) else f"Ollama at {host} can't be reached."


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
            ("num_predict", options.num_predict),
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
        *,
        timeout: float | None = 300.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.host = host or DEFAULT_HOST
        self.model = model
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
    ) -> AsyncIterator[str | Reasoning | Finish]:
        name = model or self.model
        payload = [{"role": m.role, "content": m.content} for m in messages]
        extra = ollama_options(options)
        try:
            stream = await self._client.chat(model=name, messages=payload, stream=True, **extra)
            async for part in stream:
                thinking = (part.message.thinking or "") if part.message else ""
                if thinking:  # reasoning is not part of the answer; shown folded above it
                    yield Reasoning(thinking)
                text = part.message.content if part.message else ""
                if text:
                    yield text
                if part.done:
                    yield Finish(part.done_reason or "stop")
        except Exception as exc:
            raise self._friendly(exc, name) from exc

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

    async def context_length(self, model: str | None = None) -> int | None:
        """From the model's metadata (``<architecture>.context_length``)."""
        try:
            info = await self._probe.show(model or self.model)
        except Exception:
            log.debug("no model info for %s", model or self.model, exc_info=True)
            return None
        for key, value in (info.modelinfo or {}).items():
            if key.endswith(".context_length") and isinstance(value, int) and value > 0:
                return value
        return None

    async def health(self) -> Health:
        try:
            listing = await self._listing()
        except ProviderError as exc:
            return Health(False, str(exc))
        if not listing:
            return Health(True, "Ollama is running but has no models: `ollama pull gemma4:12b`", [])
        return Health(True, "", sorted(listing), listing)

    # ---- errors ----------------------------------------------------------------------------

    def _friendly(self, exc: Exception, model: str) -> ProviderError:
        if isinstance(exc, ProviderError):
            return exc
        if isinstance(exc, ollama.ResponseError):
            if exc.status_code == 404:
                return ModelNotFoundError(
                    f"The model “{model}” is not installed — run `ollama pull {model}`."
                )
            return ProviderError(f"Ollama said: {exc.error}")
        if isinstance(exc, ConnectionError | httpx.TransportError):
            return ProviderUnavailableError(not_running(self.host))
        log.exception("unexpected AI error")
        return ProviderError(f"Something went wrong talking to Ollama: {exc}")
