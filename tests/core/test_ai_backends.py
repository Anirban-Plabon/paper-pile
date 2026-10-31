"""P28: the AI harness is independent of the backend and the model (PLAN §4.30) — the
OpenAI-compatible provider (vLLM, hosted APIs), choosing a backend from the settings, and what
the engine does with a backend whose window is fixed."""

import json
from collections.abc import Callable
from pathlib import Path

import httpx
import pytest

from paper_pile.core.ai.engine import NO_MODEL, AiEngine
from paper_pile.core.ai.factory import MissingProvider, api_key, chat_model, make_provider
from paper_pile.core.ai.fake import FakeProvider
from paper_pile.core.ai.ollama import OllamaProvider
from paper_pile.core.ai.openai_compat import Flavor, OpenAICompatProvider, request_fields
from paper_pile.core.ai.provider import (
    ChatMessage,
    Finish,
    GenerationOptions,
    ModelNotFoundError,
    ProviderError,
    ProviderUnavailableError,
    Reasoning,
)
from paper_pile.core.config import Config
from paper_pile.core.vault import Vault

MSGS = [ChatMessage("system", "be brief"), ChatMessage("user", "hi")]
SCHEMA = {"type": "object", "properties": {"a": {"type": "integer"}}}


def sse(*chunks: dict[str, object]) -> bytes:
    lines = [f"data: {json.dumps(c)}\n\n" for c in chunks] + ["data: [DONE]\n\n"]
    return "".join(lines).encode()


def delta(content: str = "", finish: str | None = None, **extra: str) -> dict[str, object]:
    return {"choices": [{"delta": {"content": content, **extra}, "finish_reason": finish}]}


def provider(
    handler: Callable[[httpx.Request], httpx.Response], flavor: Flavor = "vllm", key: str = ""
) -> OpenAICompatProvider:
    return OpenAICompatProvider(
        "http://vllm.test/v1",
        "m1",
        flavor=flavor,
        api_key=key,
        transport=httpx.MockTransport(handler),
    )


# ---- the OpenAI-compatible provider ----------------------------------------------------------


async def test_chat_streams_answer_reasoning_and_usage() -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/chat/completions"
        seen.update(json.loads(request.content))
        seen["auth"] = request.headers.get("authorization", "")
        return httpx.Response(
            200,
            content=sse(
                delta(reasoning_content="hmm"),
                delta("Hel"),
                delta("lo", finish="stop"),
                {"choices": [], "usage": {"prompt_tokens": 12, "completion_tokens": 2}},
            ),
        )

    pieces = [x async for x in provider(handler, key="sk-1").chat(MSGS)]
    assert pieces == [Reasoning("hmm"), "Hel", "lo", Finish("stop")]
    end = pieces[-1]
    assert isinstance(end, Finish) and (end.prompt_tokens, end.eval_tokens) == (12, 2)
    assert seen["model"] == "m1" and seen["stream"] is True and seen["auth"] == "Bearer sk-1"
    assert seen["messages"] == [
        {"role": "system", "content": "be brief"},
        {"role": "user", "content": "hi"},
    ]


async def test_a_cut_answer_says_why_and_a_broken_stream_has_no_ending() -> None:
    def cut(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=sse(delta("a"), delta("", finish="length")))

    assert [x async for x in provider(cut).chat(MSGS)] == ["a", Finish("length")]

    def broken(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b'data: {"choices": [{"delta": {"content": "a"}}]}\n')

    assert [x async for x in provider(broken).chat(MSGS)] == ["a"]  # stopped, not finished


def test_options_per_flavor() -> None:
    options = GenerationOptions(
        temperature=0.2,
        top_p=0.5,
        num_ctx=8192,  # fixed by the server: never sent
        num_predict=100,
        keep_alive_min=5,  # an Ollama thing: never sent
        schema=SCHEMA,
        think=False,
        repeat_penalty=1.1,
    )
    common = {
        "temperature": 0.2,
        "top_p": 0.5,
        "max_tokens": 100,
        "response_format": {
            "type": "json_schema",
            "json_schema": {"name": "answer", "schema": SCHEMA},
        },
    }
    assert request_fields(options, "openai") == {**common, "reasoning_effort": "none"}
    assert request_fields(options, "vllm") == {
        **common,
        "repetition_penalty": 1.1,
        "chat_template_kwargs": {"enable_thinking": False},
    }
    assert request_fields(None, "vllm") == {} and request_fields(GenerationOptions(), "vllm") == {}


async def test_a_refused_optional_field_is_dropped_and_asked_again() -> None:
    bodies: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        bodies.append(body)
        for field in ("reasoning_effort", "response_format"):
            if field in body:
                return httpx.Response(400, json={"error": {"message": f"unknown {field}"}})
        return httpx.Response(200, content=sse(delta('{"a": 1}', finish="stop")))

    options = GenerationOptions(schema=SCHEMA, think=False)
    pieces = [x async for x in provider(handler, "openai").chat(MSGS, options=options)]
    assert pieces == ['{"a": 1}', Finish("stop")]
    assert len(bodies) == 3 and not {"reasoning_effort", "response_format"} & set(bodies[2])

    def broken(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": {"message": "messages: bad"}})

    with pytest.raises(ProviderError, match="messages: bad"):  # a real error: not retried
        [x async for x in provider(broken, "openai").chat(MSGS, options=options)]


@pytest.mark.parametrize(
    ("status", "body", "error", "text"),
    [
        (401, {"error": {"message": "bad key"}}, ProviderError, "refused the API key (bad key)"),
        (404, {"error": {"message": "no such model"}}, ModelNotFoundError, "“m1” is not on"),
        (429, {"error": {"message": "slow down"}}, ProviderError, "over its limit: slow down"),
        (500, {"detail": "boom"}, ProviderError, "vLLM said: boom"),
    ],
)
async def test_errors_are_told_plainly(
    status: int, body: dict[str, object], error: type[Exception], text: str
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json=body)

    with pytest.raises(error) as err:
        [x async for x in provider(handler).chat(MSGS)]
    assert text in str(err.value)


async def test_not_reachable_and_health_never_raises() -> None:
    def down(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    p = provider(down)
    with pytest.raises(ProviderUnavailableError, match="vLLM at http://vllm.test/v1 can't be"):
        [x async for x in p.chat(MSGS)]
    health = await p.health()
    assert not health.ok and "can't be reached" in health.message


async def test_models_window_and_health_from_the_model_list() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/models"
        data = [
            {"id": "qwen3-8b", "max_model_len": 32768},
            {"id": "text-embedding-3-small"},  # not a chat model
            {"id": "gpt-x", "context_length": 128000},
        ]
        return httpx.Response(200, json={"data": data})

    p = provider(handler)
    assert await p.models() == ["gpt-x", "qwen3-8b"]
    assert await p.context_length("qwen3-8b") == 32768
    assert await p.context_length("gpt-x") == 128000
    assert await p.context_length("unknown") is None
    assert await p.memory_use("qwen3-8b", 8192) is None  # never measured on a server
    health = await p.health()
    assert health.ok and health.details == {"qwen3-8b": "32k context", "gpt-x": "125k context"}


def test_where_notes_go() -> None:
    assert OpenAICompatProvider("http://localhost:8000/v1", flavor="vllm").local
    assert not OpenAICompatProvider("", flavor="openai").local  # api.openai.com
    assert OpenAICompatProvider("", flavor="openai").host == "https://api.openai.com/v1"
    assert OllamaProvider("").local and OllamaProvider("").host == "http://localhost:11434"
    assert not OllamaProvider("http://10.0.0.5:11434").local


# ---- choosing a backend -------------------------------------------------------------------


@pytest.fixture
def ai_on(monkeypatch: pytest.MonkeyPatch) -> None:
    from paper_pile.core.ai.install import ai_unavailable

    for name in ("PAPER_PILE_NO_AI", "PAPER_PILE_FAKE_AI"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("PAPER_PILE_AI", "1")
    ai_unavailable.cache_clear()
    yield
    ai_unavailable.cache_clear()


def config(tmp_path: Path, **values: str) -> Config:
    cfg = Config(global_path=tmp_path / "c.toml")
    for key, value in values.items():
        cfg.set(f"ai.{key}", value)
    return cfg


@pytest.mark.usefixtures("ai_on")
def test_the_provider_comes_from_the_settings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert isinstance(make_provider(config(tmp_path)), OllamaProvider)  # the default
    monkeypatch.setenv("MY_KEY", "sk-9")
    p = make_provider(config(tmp_path, provider="vllm", api_key_env="MY_KEY", model="q"))
    assert isinstance(p, OpenAICompatProvider)
    assert (p.flavor, p.label, p.host, p.model) == ("vllm", "vLLM", "http://localhost:8000/v1", "q")
    assert p._client.headers["authorization"] == "Bearer sk-9"
    p = make_provider(config(tmp_path, provider="openai", host="https://openrouter.ai/api/v1"))
    assert isinstance(p, OpenAICompatProvider) and p.host == "https://openrouter.ai/api/v1"
    unknown = make_provider(config(tmp_path, provider="nope"))
    assert isinstance(unknown, MissingProvider) and "Unknown AI provider" in unknown.reason


def test_the_api_key_is_read_from_a_variable_only(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MY_KEY", "sk-9")
    assert api_key("MY_KEY") == "sk-9"
    assert api_key("") == "" and api_key("UNSET_VAR_XYZ") == ""
    assert api_key("sk-9") == ""  # a key typed where the name goes is not used as a name


def test_no_model_is_assumed(tmp_path: Path) -> None:
    cfg = config(tmp_path)
    assert chat_model(cfg) == ""
    assert chat_model(cfg, ["nomic-embed-text", "qwen3:8b"]) == "qwen3:8b"  # chat models only
    cfg.set("ai.model", "mine")
    assert chat_model(cfg, ["qwen3:8b"]) == "mine"


# ---- the engine with any backend ----------------------------------------------------------


def engine(tmp_path: Path, fake: FakeProvider) -> AiEngine:
    root = tmp_path / "v"
    root.mkdir(exist_ok=True)
    return AiEngine(Vault(root), Config(vault=root), provider_factory=lambda _c: fake)


async def test_a_fixed_window_is_used_whole_and_never_measured(tmp_path: Path) -> None:
    fake = FakeProvider(delay=0)
    fake.sizes_window = False  # a server (vLLM, an API): its window is set when it starts
    fake.max_context = 131072
    fake.gpu_share = {8192: 1.0}
    ai = engine(tmp_path, fake)
    assert await ai.window() == 131072 and fake.measured == []


async def test_the_model_is_the_first_listed_until_one_is_chosen(tmp_path: Path) -> None:
    fake = FakeProvider(delay=0)
    ai = engine(tmp_path, fake)
    assert ai.model() == ""  # nothing listed yet
    parts = [p async for p in ai.stream([ChatMessage("user", "hi")], max_answer=10)]
    assert parts and ai.model() == "fake-model"  # asked the backend before sending


async def test_without_any_model_the_user_is_told(tmp_path: Path) -> None:
    fake = FakeProvider(delay=0)
    fake.up = False
    ai = engine(tmp_path, fake)
    with pytest.raises(ProviderError, match=NO_MODEL):
        [p async for p in ai.stream([ChatMessage("user", "hi")])]


# ---- Settings follow the backend ------------------------------------------------------------


def test_switching_backends_keeps_each_ones_settings(tmp_path: Path) -> None:
    from paper_pile.core.ai.backends import settings_for, switch_backend

    cfg = config(tmp_path, model="ornith-1.5:9b")
    changed = switch_backend(cfg, "openai")
    assert {"ai.provider", "ai.host", "ai.model", "ai.api_key_env"} <= changed
    assert cfg.get("ai.provider") == "openai" and cfg.get("ai.model") == ""  # not Ollama's model
    cfg.set("ai.host", "https://openrouter.ai/api/v1")
    cfg.set("ai.api_key_env", "OPENROUTER_API_KEY")
    cfg.set("ai.model", "google/gemini-2.5-flash")
    assert settings_for(cfg, "ollama")["model"] == "ornith-1.5:9b"  # kept while away
    switch_backend(cfg, "ollama")
    assert (cfg.get("ai.model"), cfg.get("ai.host"), cfg.get("ai.api_key_env")) == (
        "ornith-1.5:9b",
        "",
        "",
    )
    switch_backend(cfg, "openai")
    assert cfg.get("ai.host") == "https://openrouter.ai/api/v1"
    assert cfg.get("ai.model") == "google/gemini-2.5-flash"
    assert switch_backend(cfg, "openai") == set()  # already the one
    cfg.save("global")
    reread = Config(global_path=tmp_path / "c.toml")
    assert settings_for(reread, "ollama")["model"] == "ornith-1.5:9b"  # saved in config.toml


def test_a_hosted_api_is_only_asked_when_chosen(tmp_path: Path) -> None:
    from paper_pile.core.ai.backends import worth_probing

    cfg = config(tmp_path)  # Ollama chosen
    assert worth_probing(cfg, "ollama") and worth_probing(cfg, "vllm")  # local defaults
    assert not worth_probing(cfg, "openai")  # api.openai.com: never contacted unasked
    cfg.set("ai.saved", {"openai": {"host": "http://localhost:1234/v1"}})  # LM Studio here
    assert worth_probing(cfg, "openai")


@pytest.mark.usefixtures("ai_on")
async def test_probe_tells_which_backends_answer(tmp_path: Path) -> None:
    from paper_pile.core.ai import factory
    from paper_pile.core.ai.backends import status

    asked: list[str] = []

    def build(kind: str, **_kw: str) -> FakeProvider:
        asked.append(kind)
        fake = FakeProvider(delay=0)
        fake.up = kind == "ollama"
        return fake

    original = factory.build_provider
    factory.build_provider = build  # type: ignore[assignment]
    try:
        found = await factory.probe_backends(config(tmp_path))
    finally:
        factory.build_provider = original
    assert asked == ["ollama", "vllm"]  # not the hosted API
    assert [status(found[k]) for k in ("ollama", "vllm", "openai")] == [
        "2 models",
        "not reachable",
        "",
    ]


def test_hints_follow_the_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    from paper_pile.core.ai.backends import hints

    assert hints("ai.host", "vllm") == ("", "http://localhost:8000/v1")  # the default, shown
    assert hints("ai.host", "ollama") == ("", "http://localhost:11434")
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-1")
    monkeypatch.delenv("NOPE_KEY", raising=False)
    assert hints("ai.api_key_env", "openai", "OPENROUTER_API_KEY") == ("Set", "e.g. OPENAI_API_KEY")
    assert "Not set" in hints("ai.api_key_env", "openai", "NOPE_KEY")[0]  # type: ignore[index]
    assert hints("ai.model", "ollama") == ("", "First listed")
    assert hints("ai.temperature", "ollama") is None


def test_the_key_row_only_for_backends_that_take_one() -> None:
    from paper_pile.core.settings import ALL, is_shown, sanitized

    for kind, shown in (("ollama", False), ("vllm", True), ("openai", True)):
        values = sanitized({"features": {"ai": True}, "ai": {"provider": kind}})
        values["features.ai"] = True  # as with --ai
        assert is_shown("AI", ALL["ai.api_key_env"], values, searching=True) is shown, kind


# ---- Load model at start --------------------------------------------------------------------


async def test_the_model_is_loaded_once_with_the_window_requests_use(tmp_path: Path) -> None:
    fake = FakeProvider(delay=0)
    fake.max_context = 32768
    fake.gpu_share = {8192: 1.0, 16384: 1.0, 32768: 1.0}
    ai = engine(tmp_path, fake)
    await ai.health()
    await ai.health()  # every 30 s: not loaded again
    assert ai._preloading is not None
    await ai._preloading
    ((model, options),) = fake.preloaded
    assert model == "fake-model" and options.num_ctx == 32768 == await ai.window()
    [p async for p in ai.stream([ChatMessage("user", "hi")], max_answer=10)]
    assert fake.options is not None and fake.options.num_ctx == options.num_ctx  # no reload
    assert fake.options.keep_alive_min == options.keep_alive_min
    ai.config.set("ai.model", "fake-model-2")  # type: ignore[union-attr]
    await ai.health()
    await ai._preloading
    assert [m for m, _ in fake.preloaded] == ["fake-model", "fake-model-2"]  # a new pick loads


async def test_no_load_at_start_when_switched_off(tmp_path: Path) -> None:
    fake = FakeProvider(delay=0)
    ai = engine(tmp_path, fake)
    ai.config.set("ai.preload", False)  # type: ignore[union-attr]
    await ai.health()
    assert ai._preloading is None and fake.preloaded == []


async def test_ollama_preload_is_an_empty_generate_with_window_and_keep_alive() -> None:
    sent: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/generate"
        sent.append(json.loads(request.content))
        return httpx.Response(200, json={"done": True})

    p = OllamaProvider("http://ollama.test", transport=httpx.MockTransport(handler))
    options = GenerationOptions(temperature=0.8, num_ctx=32768, num_predict=99, keep_alive_min=5)
    assert await p.preload("g:12b", options)
    assert sent == [
        {
            "model": "g:12b",
            "prompt": "",
            "options": {"temperature": 0.8, "num_ctx": 32768},
            "keep_alive": "5m",
            "stream": False,
        }
    ]
    assert not await provider(lambda r: httpx.Response(500)).preload("m1", options)  # vLLM


def test_the_load_setting_only_for_backends_that_load_models() -> None:
    from paper_pile.core.settings import ALL, is_shown, sanitized

    for kind, shown in (("ollama", True), ("vllm", False), ("openai", False)):
        values = sanitized({"ai": {"provider": kind}})
        values["features.ai"] = True
        assert is_shown("AI", ALL["ai.preload"], values, searching=True) is shown, kind
