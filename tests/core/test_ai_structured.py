"""P26.1: per-call JSON schema and "no thinking" options, token counts, the scripted fake and
``ask_json`` (PLAN §4.29)."""

import json
from collections.abc import Callable
from pathlib import Path

import httpx
import pytest

from paper_pile.core.ai.engine import AiEngine
from paper_pile.core.ai.fake import FakeProvider
from paper_pile.core.ai.provider import ChatMessage, Finish, GenerationOptions, ProviderError
from paper_pile.core.ai.structured import parse_json_object
from paper_pile.core.config import Config
from paper_pile.core.vault import Vault

MSGS = [ChatMessage("user", "hi")]
SCHEMA = {"type": "object", "properties": {"a": {"type": "integer"}}, "required": ["a"]}


def ndjson(*parts: dict[str, object]) -> bytes:
    return b"".join(json.dumps(p).encode() + b"\n" for p in parts)


def ollama_provider(handler: Callable[[httpx.Request], httpx.Response]):  # type: ignore[no-untyped-def]
    pytest.importorskip("ollama")
    from paper_pile.core.ai.ollama import OllamaProvider

    return OllamaProvider("http://ollama.test", "m1", transport=httpx.MockTransport(handler))


def engine(tmp_path: Path, fake: FakeProvider) -> AiEngine:
    root = tmp_path / "v"
    root.mkdir()
    cfg = Config(vault=root)
    return AiEngine(Vault(root), cfg, user_name=lambda: "Ana", provider_factory=lambda _c: fake)


def test_parse_json_object_finds_the_object() -> None:
    assert parse_json_object('{"a": 1}') == {"a": 1}
    assert parse_json_object('Sure! Here it is: {"a": 1} hope it helps') == {"a": 1}
    assert parse_json_object('{bad} then {"a": {"b": 2}}') == {"a": {"b": 2}}
    assert parse_json_object("[1, 2]") is None  # an object, not a list
    assert parse_json_object('{"a": 1') is None  # cut off
    assert parse_json_object("") is None


async def test_schema_and_think_go_to_ollama_and_token_counts_come_back() -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(json.loads(request.content))
        return httpx.Response(
            200,
            content=ndjson(
                {"message": {"role": "assistant", "content": '{"a": 1}'}, "done": False},
                {
                    "message": {"role": "assistant", "content": ""},
                    "done": True,
                    "prompt_eval_count": 12,
                    "eval_count": 5,
                },
            ),
        )

    options = GenerationOptions(schema=SCHEMA, think=False)
    pieces = [x async for x in ollama_provider(handler).chat(MSGS, options=options)]
    assert seen["format"] == SCHEMA and seen["think"] is False
    end = pieces[-1]
    assert isinstance(end, Finish) and (end.prompt_tokens, end.eval_tokens) == (12, 5)
    assert end == Finish("stop")  # the counts do not change what an ending is


async def test_a_model_without_thinking_is_asked_again_without_think() -> None:
    bodies: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        bodies.append(body)
        if "think" in body:
            return httpx.Response(400, json={"error": '"m1" does not support thinking'})
        return httpx.Response(
            200, content=ndjson({"message": {"role": "assistant", "content": "ok"}, "done": True})
        )

    options = GenerationOptions(think=False)
    pieces = [x async for x in ollama_provider(handler).chat(MSGS, options=options)]
    assert pieces == ["ok", Finish("stop")]
    assert len(bodies) == 2 and "think" not in bodies[1]


async def test_other_errors_are_not_retried() -> None:
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(500, json={"error": "boom"})

    with pytest.raises(ProviderError, match="boom"):
        options = GenerationOptions(think=False)
        [x async for x in ollama_provider(handler).chat(MSGS, options=options)]
    assert len(calls) == 1


async def test_the_fake_follows_a_script() -> None:
    fake = FakeProvider(delay=0, script=["first answer", '{"a": 2}'])
    one = "".join([p async for p in fake.chat(MSGS) if isinstance(p, str)])
    two = "".join([p async for p in fake.chat(MSGS) if isinstance(p, str)])
    assert (one, two) == ("first answer", '{"a": 2}')  # exactly, no trailing space
    with pytest.raises(ProviderError):
        [p async for p in fake.chat(MSGS)]

    by_messages = FakeProvider(delay=0, script=lambda ms: ms[-1].content.upper())
    assert "".join([p async for p in by_messages.chat(MSGS) if isinstance(p, str)]) == "HI"


async def test_ask_json_sends_the_schema_without_thinking(tmp_path: Path) -> None:
    fake = FakeProvider(delay=0, script=['Here: {"a": 3}'])
    ai = engine(tmp_path, fake)
    assert await ai.ask_json(MSGS, SCHEMA, max_answer=100) == {"a": 3}
    sent = fake.options
    assert sent is not None and sent.schema == SCHEMA and sent.think is False
    assert sent.temperature == 0.0 and sent.num_predict is not None and sent.num_predict <= 100


async def test_ask_json_is_none_for_a_cut_or_bad_answer(tmp_path: Path) -> None:
    fake = FakeProvider(delay=0, script=['{"a": 1}', "no json here"])
    fake.finish = "length"
    ai = engine(tmp_path, fake)
    assert await ai.ask_json(MSGS, SCHEMA) is None  # cut off: never trusted
    fake.finish = "stop"
    assert await ai.ask_json(MSGS, SCHEMA) is None


async def test_stream_overrides_only_for_that_call(tmp_path: Path) -> None:
    fake = FakeProvider(delay=0, script=["a", "b"])
    ai = engine(tmp_path, fake)
    [p async for p in ai.stream(MSGS, temperature=0.1, think=False, max_answer=50)]
    first = fake.options
    [p async for p in ai.stream(MSGS)]
    second = fake.options
    assert first is not None and second is not None
    assert (first.temperature, first.think) == (0.1, False) and first.num_predict == 50
    assert second.think is None and second.schema is None and second.temperature != 0.1
