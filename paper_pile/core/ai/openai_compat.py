"""``OpenAICompatProvider``: any server that speaks the OpenAI Chat Completions API — vLLM,
OpenAI, OpenRouter, LM Studio, llama.cpp's server, … (PLAN §4.30). Plain ``httpx``, no client
library. The API key is read from an environment variable whose name is in the settings; the key
itself is never stored.

``flavor="vllm"`` adds vLLM's extensions (repetition penalty, ``enable_thinking`` for the chat
template, ``max_model_len`` in the model list); a plain OpenAI-compatible server gets only the
standard fields (no thinking: ``reasoning_effort: "none"``). A field the server refuses
(``response_format``, ``stream_options``, ``reasoning_effort``) is dropped and the request sent
once more, so a smaller server still answers.
"""

import json
import logging
from collections.abc import AsyncIterator, Sequence
from typing import Any, Literal

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
    is_chat_model,
    is_local_host,
)

log = logging.getLogger("paper_pile.ai")

Flavor = Literal["vllm", "openai"]
DEFAULT_HOSTS: dict[Flavor, str] = {f: BACKENDS[f].default_host for f in ("vllm", "openai")}
LABELS: dict[Flavor, str] = {f: BACKENDS[f].label for f in ("vllm", "openai")}
HEALTH_TIMEOUT_S = 5.0
OPTIONAL = (
    "response_format",
    "stream_options",
    "reasoning_effort",
    "chat_template_kwargs",
    "repetition_penalty",
)


def request_fields(options: GenerationOptions | None, flavor: Flavor) -> dict[str, Any]:
    """The generation fields of a ``/chat/completions`` request (only the set ones). There is
    no per-request window or keep-alive: the server's are fixed."""
    if options is None:
        return {}
    out: dict[str, Any] = {
        k: v
        for k, v in (
            ("temperature", options.temperature),
            ("top_p", options.top_p),
            ("max_tokens", options.num_predict),
        )
        if v is not None
    }
    if options.schema is not None:
        out["response_format"] = {
            "type": "json_schema",
            "json_schema": {"name": "answer", "schema": dict(options.schema)},
        }
    if flavor == "vllm":
        if options.repeat_penalty is not None:
            out["repetition_penalty"] = options.repeat_penalty
        if options.think is not None:  # templates without a thinking switch ignore it
            out["chat_template_kwargs"] = {"enable_thinking": options.think}
    elif options.think is False:  # a model that cannot reason refuses it: dropped then
        out["reasoning_effort"] = "none"
    return out


class ApiError(Exception):
    """The server answered with an error status."""

    def __init__(self, message: str, status_code: int) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


async def _raise_for(response: httpx.Response) -> None:
    if response.is_success:
        return
    body = (await response.aread()).decode("utf-8", "replace")
    try:
        data = json.loads(body)
        error = data.get("error", data) if isinstance(data, dict) else data
        if isinstance(error, dict):
            error = error.get("message") or error.get("detail") or error
        message = str(error)
    except ValueError:
        message = body or response.reason_phrase
    raise ApiError(message, response.status_code)


class OpenAICompatProvider:
    sizes_window = False  # the server's window is set when it starts (vLLM: --max-model-len)

    def __init__(
        self,
        host: str = "",
        model: str = "",
        *,
        flavor: Flavor = "openai",
        api_key: str = "",
        timeout: float | None = 300.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.flavor = flavor
        self.label = LABELS[flavor]
        self.host = (host or DEFAULT_HOSTS[flavor]).rstrip("/")
        self.model = model
        self.local = is_local_host(self.host)
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        extra: dict[str, Any] = {"transport": transport} if transport is not None else {}
        self._client = httpx.AsyncClient(
            base_url=self.host, timeout=timeout, headers=headers, **extra
        )
        self._probe = httpx.AsyncClient(
            base_url=self.host, timeout=HEALTH_TIMEOUT_S, headers=headers, **extra
        )
        self._listed: dict[str, dict[str, Any]] = {}  # model id -> its entry in /models

    def missing_model(self, model: str) -> str:
        if self.flavor == "vllm":
            return "start vLLM with it (`vllm serve <model>`), or pick the one it serves"
        return "check the model name on the server, or pick one it lists"

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
            "stream_options": {"include_usage": True},
            **request_fields(options, self.flavor),
        }
        while True:
            started = False
            try:
                async for piece in self._stream(body):
                    started = True
                    yield piece
                return
            except Exception as exc:
                refused = self._refused_field(exc, body) if not started else None
                if refused is not None:  # an optional field this server does not take
                    log.info("%s refused %s: asking again without it", self.host, refused)
                    body.pop(refused)
                    continue
                raise self._friendly(exc, name) from exc

    async def _stream(self, body: dict[str, Any]) -> AsyncIterator[str | Reasoning | Finish]:
        reason = ""
        usage: dict[str, Any] = {}
        async with self._client.stream("POST", "/chat/completions", json=body) as response:
            await _raise_for(response)
            async for line in response.aiter_lines():
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                chunk = json.loads(data)
                if chunk.get("error"):
                    error = chunk["error"]
                    message = error.get("message", error) if isinstance(error, dict) else error
                    raise ApiError(str(message), response.status_code)
                usage = chunk.get("usage") or usage
                for choice in chunk.get("choices") or []:
                    delta = choice.get("delta") or {}
                    thinking = delta.get("reasoning_content") or delta.get("reasoning")
                    if thinking:  # not part of the answer; shown folded above it
                        yield Reasoning(thinking)
                    if delta.get("content"):
                        yield delta["content"]
                    reason = choice.get("finish_reason") or reason
        if reason:  # an answer without one was cut off by the connection
            yield Finish(reason, usage.get("prompt_tokens"), usage.get("completion_tokens"))

    @staticmethod
    def _refused_field(exc: Exception, body: dict[str, Any]) -> str | None:
        if not isinstance(exc, ApiError) or exc.status_code not in (400, 422):
            return None
        return next((f for f in OPTIONAL if f in body and f in exc.message), None)

    # ---- state -----------------------------------------------------------------------------

    async def _listing(self) -> dict[str, dict[str, Any]]:
        try:
            response = await self._probe.get("/models")
            await _raise_for(response)
            data = response.json().get("data") or []
        except Exception as exc:
            raise self._friendly(exc, "") from exc
        listed = {
            str(m["id"]): m
            for m in data
            if isinstance(m, dict) and m.get("id") and is_chat_model(str(m["id"]))
        }
        self._listed = listed
        return listed

    async def models(self) -> list[str]:
        return sorted(await self._listing())

    async def context_length(self, model: str | None = None) -> int | None:
        """From the model list (vLLM: ``max_model_len``; some servers: ``context_length``)."""
        name = model or self.model
        if name not in self._listed:
            try:
                await self._listing()
            except ProviderError:
                return None
        entry = self._listed.get(name) or {}
        for key in ("max_model_len", "context_length", "context_window"):
            value = entry.get(key)
            if isinstance(value, int) and value > 0:
                return value
        return None

    async def memory_use(self, model: str, num_ctx: int) -> tuple[int, int] | None:
        return None  # a server's memory is not ours to measure

    async def preload(self, model: str, options: GenerationOptions) -> bool:
        return False  # the server loaded its model when it started

    async def health(self) -> Health:
        try:
            listed = await self._listing()
        except ProviderError as exc:
            return Health(False, str(exc))
        if not listed:
            return Health(True, f"{self.label} at {self.host} lists no models", [])
        details = {}
        for name, entry in listed.items():
            window = entry.get("max_model_len") or entry.get("context_length")
            details[name] = f"{window // 1024}k context" if isinstance(window, int) else ""
        return Health(True, "", sorted(listed), details)

    # ---- errors ----------------------------------------------------------------------------

    def _friendly(self, exc: Exception, model: str) -> ProviderError:
        if isinstance(exc, ProviderError):
            return exc
        if isinstance(exc, ApiError):
            if exc.status_code in (401, 403):
                return ProviderError(
                    f"{self.label} refused the API key ({exc.message}) — set the variable named "
                    "in Settings → AI → API key variable."
                )
            if exc.status_code == 404 and model:
                return ModelNotFoundError(
                    f"The model “{model}” is not on {self.host} — {self.missing_model(model)}."
                )
            if exc.status_code == 429:
                return ProviderError(f"{self.label} is busy or over its limit: {exc.message}")
            return ProviderError(f"{self.label} said: {exc.message}")
        if isinstance(exc, ConnectionError | httpx.TransportError):
            return ProviderUnavailableError(f"{self.label} at {self.host} can't be reached.")
        log.exception("unexpected AI error")
        return ProviderError(f"Something went wrong talking to {self.label}: {exc}")
