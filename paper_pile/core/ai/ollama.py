"""``OllamaProvider``: an Ollama server (https://ollama.com), reached over its HTTP API with
``httpx`` (no client library). Errors are turned into :class:`ProviderError` with messages for
the user."""

import json
import logging
from collections.abc import AsyncIterator, Sequence
from dataclasses import replace
from typing import Any

import httpx

from paper_pile.core.ai.backends import BACKENDS
from paper_pile.core.ai.provider import (
    ChatMessage,
    Finish,
    GenerationOptions,
    Health,
    ModelNotFoundError,
    ProviderError,
    ProviderUnavailableError,
    Reasoning,
    RepeatLoopError,
    is_local_host,
)

log = logging.getLogger("paper_pile.ai")

DEFAULT_HOST = BACKENDS["ollama"].default_host
REPEAT_LOOP = "repeat limit"  # in Ollama's error when it stopped a model repeating itself
NOT_RUNNING = "Ollama isn't running — start it with `ollama serve`."
HEALTH_TIMEOUT_S = 3.0


def not_running(host: str) -> str:
    """What to say when Ollama cannot be reached: start it here, or check the other computer."""
    return NOT_RUNNING if is_local_host(host) else f"Ollama at {host} can't be reached."


def describe_model(parameter_size: str | None, family: str | None, size: int | None) -> str:
    """``"9B · gemma3 · 5.4 GB"`` from whatever Ollama reports (parts it lacks are left out)."""
    parts = [p for p in (parameter_size, family) if p]
    if size:
        parts.append(f"{size / 1e9:.1f} GB")
    return " · ".join(parts)


def ollama_options(options: GenerationOptions | None) -> dict[str, Any]:
    """``options`` / ``keep_alive`` / ``format`` / ``think`` fields of a ``/api/chat`` request
    (only the set ones)."""
    if options is None:
        return {}
    model = {
        k: v
        for k, v in (
            ("temperature", options.temperature),
            ("top_p", options.top_p),
            ("num_ctx", options.num_ctx),
            ("num_predict", options.num_predict),
            ("repeat_penalty", options.repeat_penalty),
        )
        if v is not None
    }
    out: dict[str, Any] = {"options": model} if model else {}
    if options.keep_alive_min is not None:
        out["keep_alive"] = f"{options.keep_alive_min}m"
    if options.schema is not None:
        out["format"] = dict(options.schema)
    if options.think is not None:
        out["think"] = options.think
    return out


class OllamaError(Exception):
    """Ollama answered with an error (``{"error": …}``, on a status or inside the stream)."""

    def __init__(self, error: str, status_code: int) -> None:
        super().__init__(error)
        self.error = error
        self.status_code = status_code


def no_thinking(exc: Exception) -> bool:
    """Ollama refused ``think`` because the model has no thinking mode."""
    return isinstance(exc, OllamaError) and "does not support thinking" in exc.error


async def _raise_for(response: httpx.Response) -> None:
    if response.is_success:
        return
    body = (await response.aread()).decode("utf-8", "replace")
    try:
        error = str(json.loads(body).get("error", body))
    except (ValueError, AttributeError):
        error = body or response.reason_phrase
    raise OllamaError(error, response.status_code)


class OllamaProvider:
    label = "Ollama"
    sizes_window = True

    def __init__(
        self,
        host: str = DEFAULT_HOST,
        model: str = "",
        *,
        timeout: float | None = 300.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.host = (host or DEFAULT_HOST).rstrip("/")
        self.model = model
        self.local = is_local_host(self.host)
        extra: dict[str, Any] = {"transport": transport} if transport is not None else {}
        self._client = httpx.AsyncClient(base_url=self.host, timeout=timeout, **extra)
        self._probe = httpx.AsyncClient(base_url=self.host, timeout=HEALTH_TIMEOUT_S, **extra)

    def missing_model(self, model: str) -> str:
        return f"run `ollama pull {model}`"

    async def _json(self, method: str, path: str, body: dict[str, Any] | None = None) -> Any:
        client = self._client if path == "/api/generate" else self._probe
        response = await client.request(method, path, json=body)
        await _raise_for(response)
        return response.json()

    # ---- chat ------------------------------------------------------------------------------

    async def chat(
        self,
        messages: Sequence[ChatMessage],
        *,
        model: str | None = None,
        options: GenerationOptions | None = None,
    ) -> AsyncIterator[str | Reasoning | Finish]:
        name = model or self.model
        body: dict[str, Any] = {
            "model": name,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            "stream": True,
            **ollama_options(options),
        }
        while True:
            started = False
            try:
                async with self._client.stream("POST", "/api/chat", json=body) as response:
                    await _raise_for(response)
                    async for line in response.aiter_lines():
                        if not line.strip():
                            continue
                        part = json.loads(line)
                        if "error" in part:
                            raise OllamaError(str(part["error"]), response.status_code)
                        started = True
                        message = part.get("message") or {}
                        if message.get("thinking"):  # not part of the answer; shown folded
                            yield Reasoning(message["thinking"])
                        if message.get("content"):
                            yield message["content"]
                        if part.get("done"):
                            yield Finish(
                                part.get("done_reason") or "stop",
                                part.get("prompt_eval_count"),
                                part.get("eval_count"),
                            )
                return
            except Exception as exc:
                if not started and "think" in body and no_thinking(exc):
                    body.pop("think")  # asked not to think and it cannot: ask again without
                    continue
                raise self._friendly(exc, name) from exc

    # ---- state -----------------------------------------------------------------------------

    async def models(self) -> list[str]:
        return sorted(await self._listing())

    async def _listing(self) -> dict[str, str]:
        """Installed models and a one-line description of each."""
        try:
            listing = await self._json("GET", "/api/tags")
        except Exception as exc:
            raise self._friendly(exc, "") from exc
        out: dict[str, str] = {}
        for m in listing.get("models") or []:
            if m.get("model"):
                d = m.get("details") or {}
                out[m["model"]] = describe_model(
                    d.get("parameter_size"), d.get("family"), m.get("size")
                )
        return out

    async def context_length(self, model: str | None = None) -> int | None:
        """From the model's metadata (``<architecture>.context_length``)."""
        try:
            info = await self._json("POST", "/api/show", {"model": model or self.model})
        except Exception:
            log.debug("no model info for %s", model or self.model, exc_info=True)
            return None
        for key, value in (info.get("model_info") or {}).items():
            if key.endswith(".context_length") and isinstance(value, int) and value > 0:
                return value
        return None

    async def memory_use(self, model: str, num_ctx: int) -> tuple[int, int] | None:
        """Loads ``model`` with a ``num_ctx`` window (an empty prompt) and reads how big it is
        and how much of it Ollama put in VRAM. Takes a few seconds per call."""
        load = {
            "model": model,
            "prompt": "",
            "options": {"num_ctx": num_ctx},
            "keep_alive": "5m",
            "stream": False,
        }
        try:
            await self._json("POST", "/api/generate", load)
            running = await self._json("GET", "/api/ps")
        except Exception:
            log.debug("could not measure %s at %d", model, num_ctx, exc_info=True)
            return None
        for m in running.get("models") or []:
            if model in (m.get("model"), m.get("name")) and m.get("size"):
                return m["size"], m.get("size_vram") or 0
        return None

    async def preload(self, model: str, options: GenerationOptions) -> bool:
        """An empty generate with the window and keep-alive of a real request: Ollama loads the
        model and keeps it (a request with another window would load it again)."""
        extra = ollama_options(replace(options, num_predict=None, schema=None, think=None))
        try:
            await self._json(
                "POST", "/api/generate", {"model": model, "prompt": "", **extra, "stream": False}
            )
        except Exception:
            log.info("could not preload %s", model, exc_info=True)
            return False
        return True

    async def health(self) -> Health:
        try:
            listing = await self._listing()
        except ProviderError as exc:
            return Health(False, str(exc))
        if not listing:
            return Health(True, "Ollama is running but has no models: `ollama pull <model>`", [])
        return Health(True, "", sorted(listing), listing)

    # ---- errors ----------------------------------------------------------------------------

    def _friendly(self, exc: Exception, model: str) -> ProviderError:
        if isinstance(exc, ProviderError):
            return exc
        if isinstance(exc, OllamaError):
            if exc.status_code == 404:
                return ModelNotFoundError(
                    f"The model “{model}” is not installed — {self.missing_model(model)}."
                )
            if REPEAT_LOOP in exc.error:
                return RepeatLoopError(f"Ollama said: {exc.error}")
            return ProviderError(f"Ollama said: {exc.error}")
        if isinstance(exc, ConnectionError | httpx.TransportError):
            return ProviderUnavailableError(not_running(self.host))
        log.exception("unexpected AI error")
        return ProviderError(f"Something went wrong talking to Ollama: {exc}")
