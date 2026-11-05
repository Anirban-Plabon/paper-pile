"""P28.6: Antigravity CLI (``agy``) as an AI backend (PLAN §4.30), driven through a stand-in
``agy`` script — the real CLI needs a sign-in and the network (checked by hand, TRACKER)."""

import json
import sys
from pathlib import Path

import pytest

from paper_pile.core.ai.antigravity_cli import (
    AGENTS,
    AntigravityCliProvider,
    flatten,
    parse_models,
)
from paper_pile.core.ai.factory import build_provider
from paper_pile.core.ai.provider import (
    ChatMessage,
    Finish,
    GenerationOptions,
    ModelNotFoundError,
    ProviderError,
    ProviderUnavailableError,
)

CID = "11111111-2222-3333-4444-555555555555"
MSGS = [ChatMessage("system", "be brief"), ChatMessage("user", "hi")]

# the stand-in: records its arguments and stdin, then answers as $MODE says
FAKE = r"""#!PYTHON
import json, os, sys, time
from pathlib import Path
log = Path(os.environ["AGY_LOG"])
if sys.argv[1:2] == ["models"]:
    print("Fetching available models...")
    print("gemini-flash-low\tGemini Flash (Low)")
    print("claude-x\tClaude X")
    sys.exit(0)
data = sys.stdin.read()
log.write_text(json.dumps({"argv": sys.argv[1:], "stdin": data, "cwd": os.getcwd()}))
cid = os.environ["CID"]
home = Path(os.environ["AGY_HOME"])
(home / "conversations").mkdir(parents=True, exist_ok=True)
(home / "conversations" / f"{cid}.db").write_text("note text")
(home / "brain" / cid).mkdir(parents=True, exist_ok=True)
(home / "brain" / cid / "t.jsonl").write_text("note text")
def out(event):
    print(json.dumps(event), flush=True)
mode = os.environ.get("MODE", "ok")
out({"event": "init", "conversation_id": cid, "init": {"model": "m"}})
if mode == "ok":
    for piece in ("Hel", "lo"):
        out({"event": "step_update", "step_update": {"conversation_id": cid, "text_delta": piece}})
    out({"event": "result", "result": {"conversation_id": cid, "status": "SUCCESS",
         "response": "Hello", "usage": {"input_tokens": 12, "output_tokens": 2}}})
elif mode == "json":
    out({"event": "step_update", "step_update": {"conversation_id": cid, "text_delta": "{\"a\""}})
    out({"event": "result", "result": {"conversation_id": cid, "status": "SUCCESS",
         "response": "{\"a\": 1}", "structured_output": {"a": 1}, "usage": {}}})
elif mode == "badmodel":
    out({"event": "result", "result": {"conversation_id": "", "status": "ERROR",
         "error": "invalid model selection: model x is not recognized as a known model"}})
elif mode == "error":
    out({"event": "result", "result": {"conversation_id": cid, "status": "ERROR", "error": "boom"}})
elif mode == "silent":
    print("jetski: something went wrong", file=sys.stderr)
elif mode == "slow":
    out({"event": "step_update", "step_update": {"conversation_id": cid, "text_delta": "a"}})
    time.sleep(30)
"""


@pytest.fixture
def agy(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> AntigravityCliProvider:
    program = tmp_path / "bin" / "agy"
    program.parent.mkdir()
    program.write_text(FAKE.replace("PYTHON", sys.executable))
    program.chmod(0o755)
    monkeypatch.setenv("AGY_LOG", str(tmp_path / "log.json"))
    monkeypatch.setenv("AGY_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("CID", CID)
    return AntigravityCliProvider(
        "gemini-flash-low",
        program=str(program),
        run_dir=tmp_path / "run",
        home=tmp_path / "home",
    )


def seen(tmp_path: Path) -> dict[str, object]:
    return json.loads((tmp_path / "log.json").read_text())


async def collect(provider: AntigravityCliProvider, **kw: object) -> list[object]:
    return [p async for p in provider.chat(MSGS, **kw)]  # type: ignore[arg-type]


async def test_streams_the_answer_fenced_in_and_forgets_it(
    agy: AntigravityCliProvider, tmp_path: Path
) -> None:
    pieces = await collect(agy)
    assert pieces[:2] == ["Hel", "lo"]
    finish = pieces[2]
    assert isinstance(finish, Finish) and finish.reason == "stop"
    assert (finish.prompt_tokens, finish.eval_tokens) == (12, 2)
    got = seen(tmp_path)
    argv = got["argv"]
    assert isinstance(argv, list)
    assert argv[argv.index("--agent") + 1] == "paper-pile"
    assert json.loads(argv[argv.index("--settings") + 1]) == {"toolPermission": "strict"}
    assert "--dangerously-skip-permissions" not in argv
    assert argv[-2:] == ["-p", ""]  # -p last: it eats the next argument
    assert argv[argv.index("--model") + 1] == "gemini-flash-low"
    assert got["cwd"] == str(tmp_path / "run")  # its own folder, never the vault
    agents = tmp_path / "run" / ".agents" / "agents"
    assert (agents / "paper-pile.md").read_text() == AGENTS["paper-pile"]
    sent = json.loads(str(got["stdin"]))
    assert sent["event"] == "user" and sent["message"]["role"] == "user"
    assert "be brief" in sent["message"]["content"] and "hi" in sent["message"]["content"]
    # the copy agy kept (it holds the notes) is gone
    assert not (tmp_path / "home" / "conversations" / f"{CID}.db").exists()
    assert not (tmp_path / "home" / "brain" / CID).exists()


async def test_a_json_answer_comes_whole_from_the_structured_output(
    agy: AntigravityCliProvider, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MODE", "json")
    schema = {"type": "object", "properties": {"a": {"type": "integer"}}}
    pieces = await collect(agy, options=GenerationOptions(schema=schema, temperature=0.1))
    assert pieces[0] == '{"a": 1}'  # not the streamed fragment
    argv = seen(tmp_path)["argv"]
    assert isinstance(argv, list)
    assert json.loads(argv[argv.index("--json-schema") + 1]) == schema
    assert argv[argv.index("--agent") + 1] == "paper-pile-json"  # the one with `finish`
    assert "--temperature" not in argv  # not something agy takes: dropped


@pytest.mark.parametrize(
    ("mode", "error"),
    [
        ("badmodel", ModelNotFoundError),
        ("error", ProviderError),
        ("silent", ProviderError),
    ],
)
async def test_failures_are_told_plainly(
    agy: AntigravityCliProvider, monkeypatch: pytest.MonkeyPatch, mode: str, error: type
) -> None:
    monkeypatch.setenv("MODE", mode)
    with pytest.raises(error) as caught:
        await collect(agy)
    assert "Antigravity CLI" in str(caught.value)
    if mode == "silent":
        assert "something went wrong" in str(caught.value)


async def test_stopping_the_answer_stops_agy(
    agy: AntigravityCliProvider, monkeypatch: pytest.MonkeyPatch
) -> None:
    import asyncio
    import time

    monkeypatch.setenv("MODE", "slow")
    stream = agy.chat(MSGS)
    assert await anext(stream) == "a"
    started = time.monotonic()
    await stream.aclose()  # what cancelling the task does
    assert time.monotonic() - started < 5
    await asyncio.sleep(0)


async def test_not_installed_says_so(tmp_path: Path) -> None:
    missing = AntigravityCliProvider(program=str(tmp_path / "nope"), run_dir=tmp_path)
    with pytest.raises(ProviderUnavailableError, match="not installed"):
        await collect(missing)
    health = await missing.health()
    assert not health.ok and "not installed" in health.message


async def test_models_and_health_from_agy_models(agy: AntigravityCliProvider) -> None:
    assert await agy.models() == ["gemini-flash-low", "claude-x"]
    health = await agy.health()
    assert health.ok and health.details["claude-x"] == "Claude X"
    assert await agy.context_length("gemini-flash-low") == 131072
    assert await agy.context_length("mystery") is None


def test_flatten_keeps_instructions_turns_and_the_request() -> None:
    assert flatten([ChatMessage("user", "just this")]) == "just this"
    text = flatten(
        [
            ChatMessage("system", "rules"),
            ChatMessage("user", "q1"),
            ChatMessage("assistant", "a1"),
            ChatMessage("user", "q2"),
        ]
    )
    assert text.index("rules") < text.index("User: q1") < text.index("Assistant: a1")
    assert text.endswith("<request>\nq2\n</request>")


def test_parse_models_skips_the_chatter() -> None:
    assert parse_models("Fetching available models...\na-1\tA One\n\nb\tB\n") == {
        "a-1": "A One",
        "b": "B",
    }


def test_chosen_in_settings_as_a_program_not_a_server() -> None:
    from paper_pile.core.settings import ALL, is_shown, sanitized

    provider = build_provider("antigravity", model="claude-x")
    assert isinstance(provider, AntigravityCliProvider)
    assert provider.local is False  # the consent card says notes leave the computer
    values = sanitized({"features": {"ai": True}, "ai": {"provider": "antigravity"}})
    values["features.ai"] = True
    for key in ("ai.host", "ai.api_key_env", "ai.preload"):
        assert not is_shown("AI", ALL[key], values, searching=True), key
    assert is_shown("AI", ALL["ai.model"], values, searching=True)
