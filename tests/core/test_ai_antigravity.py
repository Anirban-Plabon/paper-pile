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
    if os.environ.get("AGY_STARTS"):
        with open(os.environ["AGY_STARTS"], "a") as f:
            f.write(json.dumps({"pid": os.getpid(), "t": time.time(), "cwd": os.getcwd(),
                                "home": os.environ["HOME"]}) + "\n")
    print("Fetching available models...")
    print("gemini-flash-low\tGemini Flash (Low)")
    print("claude-x\tClaude X")
    sys.exit(0)
if os.environ.get("AGY_STARTS"):
    with open(os.environ["AGY_STARTS"], "a") as f:
        f.write(json.dumps({"pid": os.getpid(), "t": time.time()}) + "\n")
data = sys.stdin.read()
cid = os.environ["CID"]
home = Path(os.environ["HOME"]) / ".gemini" / "antigravity-cli"  # where agy keeps its data
if not data.strip():  # stdin closed with no message (a process started ahead, never used)
    cid = cid[:-4] + "9999"
    (home / "conversations").mkdir(parents=True, exist_ok=True)
    (home / "conversations" / f"{cid}.db").write_text("")
    print(json.dumps({"event": "init", "conversation_id": cid, "init": {"model": "m"}}))
    sys.exit(0)
log.write_text(json.dumps({"argv": sys.argv[1:], "stdin": data, "cwd": os.getcwd(),
                          "home": os.environ["HOME"]}))
(home / "conversations").mkdir(parents=True, exist_ok=True)
(home / "conversations" / f"{cid}.db").write_text("note text")
(home / "brain" / cid).mkdir(parents=True, exist_ok=True)
(home / "brain" / cid / "t.jsonl").write_text("note text")
def out(event):
    print(json.dumps(event), flush=True)
mode = os.environ.get("MODE", "ok")
out({"event": "init", "conversation_id": cid, "init": {"model": "m"}})  # as agy 1.5 does
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
    (log.parent / "pid").write_text(str(os.getpid()))
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
    monkeypatch.setenv("CID", CID)
    return AntigravityCliProvider(
        "gemini-flash-low",
        program=str(program),
        run_dir=tmp_path / "run",
        home=tmp_path / "home",
        warm=False,  # the tests of the pool below turn it on
    )


def data(tmp_path: Path) -> Path:
    """Where the stand-in (like agy) keeps its data: under the HOME the app gives it."""
    return tmp_path / "home" / ".gemini" / "antigravity-cli"


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
    assert got["home"] == str(tmp_path / "home")  # its own HOME, never the user's ~/.gemini
    agents = tmp_path / "run" / ".agents" / "agents"
    assert (agents / "paper-pile.md").read_text() == AGENTS["paper-pile"]
    sent = json.loads(str(got["stdin"]))
    assert sent["event"] == "user" and sent["message"]["role"] == "user"
    assert "be brief" in sent["message"]["content"] and "hi" in sent["message"]["content"]
    # the copy agy kept (it holds the notes) is gone
    assert not (data(tmp_path) / "conversations" / f"{CID}.db").exists()
    assert not (data(tmp_path) / "brain" / CID).exists()


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
    agy: AntigravityCliProvider, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import asyncio
    import os
    import time

    monkeypatch.setenv("MODE", "slow")
    stream = agy.chat(MSGS)
    assert await anext(stream) == "a"
    started = time.monotonic()
    await stream.aclose()  # what cancelling the task does
    assert time.monotonic() - started < 5
    await asyncio.sleep(0)
    pid = int(json.loads((tmp_path / "pid").read_text()))
    with pytest.raises(ProcessLookupError):  # agy is gone now, not when the stream is freed
        os.kill(pid, 0)


async def test_not_installed_says_so(tmp_path: Path) -> None:
    missing = AntigravityCliProvider(program=str(tmp_path / "nope"), run_dir=tmp_path)
    with pytest.raises(ProviderUnavailableError, match="not installed"):
        await collect(missing)
    health = await missing.health()
    assert not health.ok and "not installed" in health.message


async def test_models_and_health_from_agy_models(
    agy: AntigravityCliProvider, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from paper_pile.core.ai import antigravity_cli

    monkeypatch.setattr(antigravity_cli, "_LISTED", {})
    monkeypatch.setenv("AGY_STARTS", str(tmp_path / "starts.jsonl"))
    assert await agy.models() == ["gemini-flash-low", "claude-x"]
    assert (await agy.health()).ok
    runs = starts(tmp_path)
    assert len(runs) == 1  # the 30 s health check reuses the listing
    assert runs[0]["cwd"] == str(tmp_path / "run") and runs[0]["home"] == str(tmp_path / "home")
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


# ---- started ahead (P28.7) ---------------------------------------------------------------------


@pytest.fixture
def warm(
    agy: AntigravityCliProvider, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> AntigravityCliProvider:
    monkeypatch.setenv("AGY_STARTS", str(tmp_path / "starts.jsonl"))
    agy._warm = True
    return agy


def starts(tmp_path: Path) -> list[dict[str, float]]:
    path = tmp_path / "starts.jsonl"
    return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []


async def wait_for(check: object, seconds: float = 5.0) -> None:
    import asyncio
    import time

    end = time.monotonic() + seconds
    while not check() and time.monotonic() < end:  # type: ignore[operator]
        await asyncio.sleep(0.02)


async def test_the_next_agy_is_started_ahead_and_used(
    warm: AntigravityCliProvider, tmp_path: Path
) -> None:
    import time

    from paper_pile.core.ai.antigravity_cli import POOL

    try:
        assert (await collect(warm))[:2] == ["Hel", "lo"]
        assert len(POOL) == 1  # the next one is waiting
        await wait_for(lambda: len(starts(tmp_path)) == 2)
        before = time.time()
        assert (await collect(warm))[:2] == ["Hel", "lo"]  # answered by the waiting one
        await wait_for(lambda: len(starts(tmp_path)) == 3)
        runs = starts(tmp_path)
        assert len(runs) == 3 and runs[1]["t"] < before  # started before it was asked
        assert seen(tmp_path)["argv"][-2:] == ["-p", ""]  # type: ignore[index]
        assert not (data(tmp_path) / "conversations" / f"{CID}.db").exists()
    finally:
        await POOL.close()
    # the unused one: stdin closed, it exited, and its (empty) conversation copy is gone
    assert len(POOL) == 0
    left = list((data(tmp_path) / "conversations").glob("*.db"))
    assert left == []


async def test_one_waiting_per_command_line_oldest_ended_and_idle_ended(
    warm: AntigravityCliProvider, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import asyncio

    from paper_pile.core.ai import antigravity_cli
    from paper_pile.core.ai.antigravity_cli import POOL

    monkeypatch.setattr(antigravity_cli, "WARM_KEYS", 2)
    monkeypatch.setenv("MODE", "json")
    try:
        for n in range(3):  # three schemas: three command lines
            schema = {"type": "object", "properties": {f"a{n}": {"type": "integer"}}}
            await collect(warm, options=GenerationOptions(schema=schema))
        assert len(POOL) == 2  # the oldest was ended
        await POOL.close()
        monkeypatch.setattr(antigravity_cli, "WARM_IDLE_S", 0.2)
        monkeypatch.setenv("MODE", "ok")
        await collect(warm)
        assert len(POOL) == 1
        await asyncio.sleep(0.4)
        assert len(POOL) == 0  # ended after the idle time
        await wait_for(lambda: not list((data(tmp_path) / "conversations").glob("*.db")))
        assert [f.name for f in (data(tmp_path) / "conversations").glob("*.db")] == []
    finally:
        await POOL.close()


async def test_a_waiting_agy_that_died_is_replaced(
    warm: AntigravityCliProvider, tmp_path: Path
) -> None:
    import os
    import signal

    from paper_pile.core.ai.antigravity_cli import POOL

    try:
        await collect(warm)
        waiting = next(iter(POOL._waiting.values()))
        os.kill(waiting.proc.pid, signal.SIGKILL)
        assert (await collect(warm))[:2] == ["Hel", "lo"]  # a new one answered
    finally:
        await POOL.close()


async def test_shutdown_ends_the_waiting_ones(warm: AntigravityCliProvider) -> None:
    from paper_pile.core.ai.antigravity_cli import POOL
    from paper_pile.core.ai.factory import shutdown_providers

    await collect(warm)
    assert len(POOL) == 1
    await shutdown_providers()
    assert len(POOL) == 0


# ---- its own home, wiped after the session (P28.8) ------------------------------------------


@pytest.fixture
def no_sessions() -> object:
    from paper_pile.core.ai import antigravity_cli

    antigravity_cli._SESSIONS.clear()
    yield
    antigravity_cli._SESSIONS.clear()


def fill_home(tmp_path: Path) -> Path:
    d = data(tmp_path)
    for name in ("conversations", "brain/x", "log", "cache", "builtin/skills", "bin"):
        (d / name).mkdir(parents=True, exist_ok=True)
    for name in (
        "conversation_summaries.db",
        "jetbox_summaries_proto.pb",
        "cache/conversation_metadata.json",
        "log/cli-1.log",
        "installation_id",
        "builtin/skills/k.md",
        "bin/tool",
    ):
        (d / name).write_text("x")
    return d


async def test_the_session_end_wipes_what_agy_kept_but_its_program(
    agy: AntigravityCliProvider, tmp_path: Path, no_sessions: object
) -> None:
    from paper_pile.core.ai.antigravity_cli import end_session

    await collect(agy)
    d = fill_home(tmp_path)
    await end_session()
    assert sorted(p.name for p in d.iterdir()) == ["bin", "builtin", "installation_id"]
    assert (d / "builtin" / "skills" / "k.md").exists()
    assert not list((tmp_path / "home" / ".paper-pile-users").iterdir())


async def test_another_app_using_the_home_keeps_it_and_a_crash_is_wiped_at_start(
    agy: AntigravityCliProvider, tmp_path: Path, no_sessions: object
) -> None:
    import subprocess

    from paper_pile.core.ai import antigravity_cli
    from paper_pile.core.ai.antigravity_cli import end_session

    other = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        users = tmp_path / "home" / ".paper-pile-users"
        users.mkdir(parents=True)
        (users / str(other.pid)).touch()  # another app process is using it
        d = fill_home(tmp_path)
        await collect(agy)
        assert (d / "conversation_summaries.db").exists()  # not wiped under the other one
        await end_session()
        assert (d / "conversation_summaries.db").exists()
    finally:
        other.kill()
        other.wait()
    antigravity_cli._SESSIONS.clear()
    await collect(agy)  # the other one is gone (as after a crash): wiped at the start
    assert not (d / "conversation_summaries.db").exists()
    assert not (users / str(other.pid)).exists()
    await end_session()


def test_never_wipes_the_real_home(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from paper_pile.core.ai import antigravity_cli

    fill_home(tmp_path)
    monkeypatch.setattr(antigravity_cli, "_real_home", lambda: (tmp_path / "home").resolve())
    antigravity_cli.wipe_data(tmp_path / "home")
    assert (data(tmp_path) / "conversation_summaries.db").exists()
