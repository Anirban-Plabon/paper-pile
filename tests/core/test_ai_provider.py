import json
from collections.abc import Callable
from pathlib import Path

import httpx
import pytest

pytest.importorskip("ollama", reason="the ai extra is not installed (uv sync --extra ai)")

from paper_pile.core.ai.fake import FakeProvider
from paper_pile.core.ai.ollama import NOT_RUNNING, OllamaProvider, describe_model
from paper_pile.core.ai.provider import (
    ChatMessage,
    Finish,
    ModelNotFoundError,
    ProviderError,
    ProviderUnavailableError,
    Reasoning,
)

MSGS = [ChatMessage("system", "be brief"), ChatMessage("user", "hi")]


def ndjson(*parts: dict[str, object]) -> bytes:
    return b"".join(json.dumps(p).encode() + b"\n" for p in parts)


def provider(handler: Callable[[httpx.Request], httpx.Response]) -> OllamaProvider:
    return OllamaProvider("http://ollama.test", "m1", transport=httpx.MockTransport(handler))


async def collect(p: OllamaProvider, **kw: str) -> str:
    return "".join([piece async for piece in p.chat(MSGS, **kw) if isinstance(piece, str)])


async def test_chat_streams_the_reply_in_pieces() -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(json.loads(request.content))
        return httpx.Response(
            200,
            content=ndjson(
                {"message": {"role": "assistant", "content": "Hel"}, "done": False},
                {"message": {"role": "assistant", "content": "lo"}, "done": False},
                {"message": {"role": "assistant", "content": ""}, "done": True},
            ),
        )

    p = provider(handler)
    pieces = [x async for x in p.chat(MSGS)]
    assert pieces == ["Hel", "lo", Finish("stop")]  # why it ended comes last
    assert seen["model"] == "m1" and seen["stream"] is True
    assert seen["messages"] == [
        {"role": "system", "content": "be brief"},
        {"role": "user", "content": "hi"},
    ]
    assert await collect(p, model="other") == "Hello"


async def test_reasoning_text_is_not_part_of_the_answer() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=ndjson(
                {"message": {"role": "assistant", "content": "", "thinking": "hmm"}, "done": False},
                {"message": {"role": "assistant", "content": "Answer"}, "done": True},
            ),
        )

    assert await collect(provider(handler)) == "Answer"
    pieces = [piece async for piece in provider(handler).chat(MSGS)]
    assert pieces[:2] == [Reasoning("hmm"), "Answer"]  # kept apart, shown folded


async def test_not_running_is_a_friendly_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    p = provider(handler)
    with pytest.raises(ProviderUnavailableError) as err:
        await collect(p)
    assert str(err.value) == "Ollama at http://ollama.test can't be reached."
    with pytest.raises(ProviderUnavailableError):
        await p.models()


async def test_missing_model_says_how_to_install_it() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"error": "model 'm1' not found"})

    with pytest.raises(ModelNotFoundError) as err:
        await collect(provider(handler))
    assert "ollama pull m1" in str(err.value)


async def test_other_server_errors_are_reported() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": "out of memory"})

    with pytest.raises(ProviderError) as err:
        await collect(provider(handler))
    assert "out of memory" in str(err.value)


async def test_models_and_health() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/tags"
        return httpx.Response(
            200, json={"models": [{"model": "zeta:1b"}, {"model": "alpha:7b"}, {"model": ""}]}
        )

    p = provider(handler)
    assert await p.models() == ["alpha:7b", "zeta:1b"]
    h = await p.health()
    assert h.ok and h.models == ["alpha:7b", "zeta:1b"] and h.message == ""


async def test_health_describes_each_model() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        model = {"model": "g:9b", "size": 5_400_000_000}
        model["details"] = {"parameter_size": "9B", "family": "gemma3"}  # type: ignore[assignment]
        return httpx.Response(200, json={"models": [model, {"model": "bare"}]})

    h = await provider(handler).health()
    assert h.details == {"g:9b": "9B · gemma3 · 5.4 GB", "bare": ""}


def test_describe_model_leaves_out_what_is_missing() -> None:
    assert describe_model("9B", "gemma3", 5_400_000_000) == "9B · gemma3 · 5.4 GB"
    assert describe_model(None, "llama", None) == "llama"
    assert describe_model(None, None, None) == ""


async def test_health_never_raises() -> None:
    def down(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    h = await provider(down).health()
    assert not h.ok and h.message == "Ollama at http://ollama.test can't be reached."

    def empty(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"models": []})

    h = await provider(empty).health()
    assert h.ok and "ollama pull" in h.message and h.models == []


async def test_stopping_the_iteration_closes_the_stream() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        parts = [
            {"message": {"role": "assistant", "content": f"w{i} "}, "done": False}
            for i in range(50)
        ]
        return httpx.Response(200, content=ndjson(*parts))

    stream = provider(handler).chat(MSGS)
    first = [await anext(stream) for _ in range(3)]
    assert first == ["w0 ", "w1 ", "w2 "]
    await stream.aclose()  # what cancelling a chat does: no error, nothing left running


async def test_the_fake_provider_follows_the_protocol() -> None:
    fake = FakeProvider(delay=0)
    pieces = [x async for x in fake.chat(MSGS)]
    assert "".join(x for x in pieces if isinstance(x, str)).strip() == "You said: hi"
    assert pieces[-1] == Finish("stop")
    assert fake.calls == [MSGS]
    assert (await fake.health()).ok and await fake.models() == ["fake-model", "fake-model-2"]
    fake.up = False
    assert not (await fake.health()).ok


async def test_generation_options_are_sent_to_ollama() -> None:
    from paper_pile.core.ai.provider import GenerationOptions

    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(json.loads(request.content))
        return httpx.Response(
            200, content=ndjson({"message": {"role": "assistant", "content": "ok"}, "done": True})
        )

    options = GenerationOptions(temperature=0.2, top_p=0.5, num_ctx=None, keep_alive_min=10)
    pieces = [x async for x in provider(handler).chat(MSGS, options=options)]
    assert pieces == ["ok", Finish("stop")]
    assert seen["options"] == {"temperature": 0.2, "top_p": 0.5}
    assert seen["keep_alive"] == "10m"


def test_ollama_options_leave_out_what_is_unset() -> None:
    from paper_pile.core.ai.ollama import ollama_options
    from paper_pile.core.ai.provider import GenerationOptions

    assert ollama_options(None) == {}
    assert ollama_options(GenerationOptions()) == {}
    assert ollama_options(GenerationOptions(num_ctx=8192, keep_alive_min=0)) == {
        "options": {"num_ctx": 8192},
        "keep_alive": "0m",
    }


def test_generation_options_from_the_config(tmp_path: Path) -> None:
    from paper_pile.core.ai.factory import generation_options
    from paper_pile.core.config import Config

    config = Config(global_path=tmp_path / "c.toml")
    opts = generation_options(config)
    assert (opts.temperature, opts.top_p, opts.num_ctx, opts.keep_alive_min) == (0.8, 0.9, None, 5)
    config.set("ai.temperature", 0.3, "global")
    config.set("ai.num_ctx", 16384, "global")
    config.set("ai.top_p", 7, "global")  # out of range: the default is used
    opts = generation_options(config)
    assert (opts.temperature, opts.top_p, opts.num_ctx) == (0.3, 0.9, 16384)
    assert generation_options(None).temperature is None


async def test_context_length_from_model_info() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/show"
        name = json.loads(request.content)["model"]
        if name == "gone":
            return httpx.Response(404, json={"error": "model not found"})
        return httpx.Response(200, json={"model_info": {"gemma3.context_length": 131072}})

    p = provider(handler)
    assert await p.context_length() == 131072
    assert await p.context_length("gone") is None


def test_local_hosts_and_the_not_running_text() -> None:
    from paper_pile.core.ai.ollama import not_running
    from paper_pile.core.ai.provider import is_local_host

    for host in ("http://localhost:11434", "127.0.0.1:11434", "http://[::1]:11434", ""):
        assert is_local_host(host), host
    for host in ("http://10.0.0.5:11434", "https://ollama.example.com", "box:11434"):
        assert not is_local_host(host), host
    assert not_running("http://localhost:11434") == NOT_RUNNING
    assert not_running("http://box:11434") == "Ollama at http://box:11434 can't be reached."


async def test_a_cut_answer_says_why() -> None:
    from paper_pile.core.ai.provider import GenerationOptions

    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(json.loads(request.content))
        return httpx.Response(
            200,
            content=ndjson(
                {"message": {"role": "assistant", "content": "a"}, "done": False},
                {
                    "message": {"role": "assistant", "content": ""},
                    "done": True,
                    "done_reason": "length",
                },
            ),
        )

    options = GenerationOptions(num_ctx=4096, num_predict=100)
    pieces = [x async for x in provider(handler).chat(MSGS, options=options)]
    assert pieces == ["a", Finish("length")]
    assert seen["options"] == {"num_ctx": 4096, "num_predict": 100}
