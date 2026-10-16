import json
from collections.abc import Callable

import httpx
import pytest

from paper_pile.core.ai.fake import FakeProvider
from paper_pile.core.ai.ollama import NOT_RUNNING, OllamaProvider
from paper_pile.core.ai.provider import (
    ChatMessage,
    ModelNotFoundError,
    ProviderError,
    ProviderUnavailableError,
)

MSGS = [ChatMessage("system", "be brief"), ChatMessage("user", "hi")]


def ndjson(*parts: dict[str, object]) -> bytes:
    return b"".join(json.dumps(p).encode() + b"\n" for p in parts)


def provider(handler: Callable[[httpx.Request], httpx.Response]) -> OllamaProvider:
    return OllamaProvider("http://ollama.test", "m1", transport=httpx.MockTransport(handler))


async def collect(p: OllamaProvider, **kw: str) -> str:
    return "".join([piece async for piece in p.chat(MSGS, **kw)])


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
    assert pieces == ["Hel", "lo"]
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


async def test_not_running_is_a_friendly_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    p = provider(handler)
    with pytest.raises(ProviderUnavailableError) as err:
        await collect(p)
    assert str(err.value) == NOT_RUNNING
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


async def test_health_never_raises() -> None:
    def down(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    h = await provider(down).health()
    assert not h.ok and h.message == NOT_RUNNING

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


async def test_embed() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body["model"] == "emb" and body["input"] == ["a", "b"]
        return httpx.Response(200, json={"model": "emb", "embeddings": [[1.0, 2.0], [3.0, 4.0]]})

    p = provider(handler)
    assert await p.embed(["a", "b"], model="emb") == [[1.0, 2.0], [3.0, 4.0]]
    with pytest.raises(ProviderError):
        await p.embed(["a"])  # no embedding model configured


async def test_the_fake_provider_follows_the_protocol() -> None:
    fake = FakeProvider(delay=0)
    assert "".join([x async for x in fake.chat(MSGS)]).strip() == "You said: hi"
    assert fake.calls == [MSGS]
    assert (await fake.health()).ok and await fake.models() == ["fake-model", "fake-model-2"]
    fake.up = False
    assert not (await fake.health()).ok
