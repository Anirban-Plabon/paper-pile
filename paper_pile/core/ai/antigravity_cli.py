"""``AntigravityCliProvider``: Google's Antigravity CLI (``agy``) run headless as the AI backend
(PLAN §4.30). There is no server: every request starts ``agy -p`` with the conversation on stdin
(``--input-format stream-json``) and reads its answer as it streams (``--output-format
stream-json``). The CLI's own sign-in is used; the app never sees a key.

``agy`` is a coding agent that can write files and run commands, so it is fenced in three ways
(checked by hand, TRACKER P28.6): it runs in the app's own empty folder (never the vault), as
an agent written there: the app's instructions as its system prompt and no tools (only
``finish`` for a JSON answer, which ``--json-schema`` needs) — and with
``toolPermission: strict``, which denies every write and command even if the agent asked.
``--dangerously-skip-permissions`` is never passed.

**Its own home** (TRACKER P28.8): agy keeps far more than the conversation — titles and
summaries (``conversation_summaries.db``, ``jetbox_summaries_proto.pb``,
``cache/conversation_metadata.json``), whole model answers in its logs. So the app's agy runs
with ``HOME`` set to the app's own folder (``<state>/paper-pile/agy-home``): nothing of the
app's requests reaches the user's own ``~/.gemini``, and the user's agy settings, permissions,
MCP servers and memories never reach the app's requests — the app's own memory (chats, the
vault memory file) is the only one. Each request's conversation files are deleted when its
answer is in, and everything but agy's program files is wiped when the session ends
(:func:`end_session`, the app's shutdown) or at the next start after a crash. It streams no
reasoning and takes no temperature, top-p or answer limit: those options are dropped.

**Started ahead** (TRACKER P28.7): ``agy`` spends ~5–8 s starting (sign-in, agent, model)
before it reads stdin, and only ~2–3 s on a short answer. So after each request the next
``agy`` with the same arguments is started at once and left waiting (:class:`WarmPool`, one
per agent / model / schema, at most :data:`WARM_KEYS`, ended after :data:`WARM_IDLE_S`).
Every request still gets its own process and conversation (one process serving several
messages would put them in one conversation); a waiting one has seen no note, and it exits
by itself when its stdin closes, so it never outlives the app.
"""

import asyncio
import atexit
import contextlib
import json
import logging
import os
import re
import shutil
import signal
import time
from collections.abc import AsyncGenerator, AsyncIterator, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import platformdirs

from paper_pile.core.ai.provider import (
    ChatMessage,
    Finish,
    GenerationOptions,
    Health,
    ModelNotFoundError,
    ProviderError,
    ProviderUnavailableError,
)

log = logging.getLogger("paper_pile.ai")

LABEL = "Antigravity CLI"
PROGRAM = "agy"
AGENT = "paper-pile"  # text answers: no tools at all
JSON_AGENT = "paper-pile-json"  # JSON answers: only `finish`, which --json-schema needs
LIST_TIMEOUT_S = 30.0
LIST_KEEP_S = 600.0  # a model listing is reused this long (models change rarely)
STREAM_LIMIT = 64 * 1024 * 1024  # one stdout line holds a whole answer
# the window the app fills with note context: the models take more, but a full million-token
# prompt per request would be slow and costly
WINDOWS = (("gemini", 131072), ("claude", 131072), ("gpt", 131072))
KEEP = frozenset(  # what a session's wipe leaves in agy's data folder: its program files
    {"bin", "builtin", "installation_id", "updater", "jetski_state.pbtxt", "last_check.timestamp"}
)
USERS = ".paper-pile-users"  # one file per app process using an agy home (named by its pid)
WARM_KEYS = 3  # processes kept waiting (~260 MB each): one per agent / model / schema
WARM_IDLE_S = 300.0  # a waiting process unused this long is ended
_ID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")


def agent_file(name: str, tools: Sequence[str]) -> str:
    """The agent agy runs as: the app's system prompt and only ``tools``."""
    listed = "".join(f"\n  - {t}" for t in tools) if tools else " []"
    return f"""---
name: {name}
description: The writing assistant of the paper-pile note app. Answers in text only.
tools:{listed}
subagent: false
mainAgent: true
commandExecutionPolicy: off
---

# System Prompt
You are the AI inside a markdown note app. Each message holds the app's instructions and the
user's request. Follow the instructions exactly and answer with the requested text only. You
have no tools: never read, write, search or run anything.
"""


# a text agent with `finish` sometimes calls it first, and agy streams its "{}" as answer text
AGENTS = {AGENT: agent_file(AGENT, []), JSON_AGENT: agent_file(JSON_AGENT, ["finish"])}


def flatten(messages: Sequence[ChatMessage]) -> str:
    """The conversation as one message (the CLI takes one per turn): the app's instructions,
    the turns before, then the request."""
    system = "\n\n".join(m.content for m in messages if m.role == "system")
    turns = [m for m in messages if m.role != "system"]
    last = turns.pop() if turns and turns[-1].role == "user" else None
    parts: list[str] = []
    if system:
        parts.append(f"<instructions>\n{system}\n</instructions>")
    if turns:
        said = "\n\n".join(
            f"{'User' if m.role == 'user' else 'Assistant'}: {m.content}" for m in turns
        )
        parts.append(f"<conversation>\n{said}\n</conversation>")
    if last is not None:
        parts.append(last.content if not parts else f"<request>\n{last.content}\n</request>")
    return "\n\n".join(parts)


def parse_models(text: str) -> dict[str, str]:
    """``agy models`` output (``id<TAB>name`` per line) as id -> name."""
    out: dict[str, str] = {}
    for line in text.splitlines():
        ident, _, name = line.partition("\t")
        if name and ident.strip() and " " not in ident.strip():
            out[ident.strip()] = name.strip()
    return out


def data_dir(agy_home: Path) -> Path:
    """Where agy keeps its data when ``HOME`` is ``agy_home``."""
    return agy_home / ".gemini" / "antigravity-cli"


def default_home() -> Path:
    return Path(platformdirs.user_state_dir("paper-pile")) / "agy-home"


def _real_home() -> Path:
    import pwd

    return Path(pwd.getpwuid(os.getuid()).pw_dir).resolve()


def wipe_data(agy_home: Path) -> None:
    """Delete everything agy kept under ``agy_home`` but its program files (:data:`KEEP`).
    Never the user's real home: there, their own agy's data lives."""
    if agy_home.resolve() == _real_home():
        log.error("refusing to wipe agy data in the real home %s", agy_home)
        return
    data = data_dir(agy_home)
    if not data.is_dir():
        return
    for entry in data.iterdir():
        if entry.name in KEEP:
            continue
        with contextlib.suppress(OSError):
            if entry.is_dir() and not entry.is_symlink():
                shutil.rmtree(entry, ignore_errors=True)
            else:
                entry.unlink(missing_ok=True)


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _others(agy_home: Path) -> list[int]:
    """Other live app processes using ``agy_home`` (stale pid files are removed)."""
    out: list[int] = []
    for entry in (agy_home / USERS).glob("*"):
        pid = int(entry.name) if entry.name.isdigit() else -1
        if pid == os.getpid():
            continue
        if pid > 0 and _alive(pid):
            out.append(pid)
        else:
            with contextlib.suppress(OSError):
                entry.unlink()
    return out


_SESSIONS: set[Path] = set()  # agy homes this process has used
_LISTED: dict[tuple[str, str], tuple[float, dict[str, str]]] = {}  # (program, home) -> listing


def begin_session(agy_home: Path) -> None:
    """This process starts using ``agy_home``: what a crashed session left is wiped first,
    unless another app process is using it now."""
    if agy_home in _SESSIONS:
        return
    users = agy_home / USERS
    users.mkdir(parents=True, exist_ok=True)
    if not _others(agy_home):
        wipe_data(agy_home)
    (users / str(os.getpid())).touch()
    _SESSIONS.add(agy_home)


async def end_session() -> None:
    """The session ends (the app's shutdown, a tool's end): the processes started ahead are
    ended, then each agy home this process used is wiped — by the last app process using it."""
    await POOL.close()
    for agy_home in list(_SESSIONS):
        _SESSIONS.discard(agy_home)
        with contextlib.suppress(OSError):
            (agy_home / USERS / str(os.getpid())).unlink()
        if not _others(agy_home):
            wipe_data(agy_home)


def _leave_sessions() -> None:
    """At exit without :func:`end_session` (no cleanup can be awaited): the processes are
    killed and this process's pid files removed; the next start wipes what is left."""
    POOL.kill_all()
    for agy_home in _SESSIONS:
        with contextlib.suppress(OSError):
            (agy_home / USERS / str(os.getpid())).unlink()


def forget(home: Path, conversation: str) -> None:
    """Delete the copy agy kept of a conversation under ``home`` (it may hold the user's
    notes)."""
    if not _ID.fullmatch(conversation):
        return
    for path in (
        home / "conversations" / f"{conversation}.db",
        home / "conversations" / f"{conversation}.db-wal",
        home / "conversations" / f"{conversation}.db-shm",
        home / "annotations" / f"{conversation}.pbtxt",
        home / "presence" / f"{conversation}.lock",
    ):
        with contextlib.suppress(OSError):
            path.unlink(missing_ok=True)
    brain = home / "brain" / conversation
    if brain.is_dir() and not brain.is_symlink():
        shutil.rmtree(brain, ignore_errors=True)


@dataclass(slots=True)
class Started:
    """One ``agy`` process with its stderr being read (so it never blocks on a full pipe)."""

    proc: asyncio.subprocess.Process
    errors: "asyncio.Task[str]"
    home: Path
    loop: asyncio.AbstractEventLoop
    timer: asyncio.TimerHandle | None = None


async def launch(cmd: Sequence[str], cwd: Path, agy_home: Path) -> Started:
    """Start agy with ``HOME`` = ``agy_home`` (the app's own; see the module doc)."""
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        cwd=cwd,
        env={**os.environ, "HOME": str(agy_home)},
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        start_new_session=True,  # cancelling stops agy and whatever it started
        limit=STREAM_LIMIT,
    )
    loop = asyncio.get_running_loop()
    return Started(proc, asyncio.create_task(_read_all(proc.stderr)), data_dir(agy_home), loop)


async def discard(started: Started) -> None:
    """End a process that will not answer (unused, or dead before it could): its stdin is
    closed (agy then exits by itself), what it printed gives its conversation, whose copy is
    deleted."""
    if started.timer is not None:
        started.timer.cancel()
    proc = started.proc
    with contextlib.suppress(Exception):
        if proc.stdin is not None:
            proc.stdin.close()
    out = b""
    with contextlib.suppress(Exception):
        if proc.stdout is not None:
            out = await asyncio.wait_for(proc.stdout.read(), 5.0)
    await _stop(proc, grace=1.0)
    started.errors.cancel()
    for raw in out.splitlines():
        conversation = _conversation_of(_event(raw) or {})
        if conversation:
            forget(started.home, conversation)
            break


def _kill(started: Started) -> None:
    """End a process from outside its event loop (exit, a finished loop): no cleanup can be
    awaited there — it has seen no note, so only an empty conversation may stay."""
    if started.timer is not None:
        started.timer.cancel()
    if started.proc.returncode is None:
        with contextlib.suppress(ProcessLookupError, PermissionError):
            os.killpg(started.proc.pid, signal.SIGTERM)


class WarmPool:
    """``agy`` processes started ahead, waiting on stdin: one per command line (agent, model,
    schema), the least recently used ended past :data:`WARM_KEYS`, each ended after
    :data:`WARM_IDLE_S` unused. Shared by every provider (the app builds one per window and
    again when the settings change)."""

    def __init__(self) -> None:
        self._waiting: dict[tuple[str, ...], Started] = {}
        self._tasks: set[asyncio.Task[None]] = set()

    def __len__(self) -> int:
        return len(self._waiting)

    def take(self, key: tuple[str, ...]) -> Started | None:
        started = self._waiting.pop(key, None)
        if started is None:
            return None
        if started.timer is not None:
            started.timer.cancel()
        if started.loop is not _running_loop() or started.proc.returncode is not None:
            self._end(started)  # from another (finished) loop, or it died while waiting
            return None
        return started

    async def fill(
        self, key: tuple[str, ...], cmd: Sequence[str], cwd: Path, agy_home: Path
    ) -> None:
        """Start the next process for ``key`` now, so its start-up runs while this one
        answers (nothing when one is already waiting)."""
        if key in self._waiting:
            return
        try:
            started = await launch(cmd, cwd, agy_home)
        except OSError:
            log.info("could not start agy ahead", exc_info=True)
            return
        started.timer = started.loop.call_later(WARM_IDLE_S, self._expire, key, started)
        self._waiting[key] = started
        while len(self._waiting) > WARM_KEYS:  # dicts keep insertion order: oldest first
            self._end(self._waiting.pop(next(iter(self._waiting))))

    def _expire(self, key: tuple[str, ...], started: Started) -> None:
        if self._waiting.get(key) is started:
            del self._waiting[key]
            self._end(started)

    def _end(self, started: Started) -> None:
        if started.loop is _running_loop() and not started.loop.is_closed():
            task = started.loop.create_task(discard(started))
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)
        else:
            _kill(started)

    async def close(self) -> None:
        """End every waiting process (and wait for their copies to be deleted)."""
        waiting, self._waiting = list(self._waiting.values()), {}
        for started in waiting:
            self._end(started)
        if self._tasks:
            await asyncio.gather(*list(self._tasks), return_exceptions=True)

    def kill_all(self) -> None:
        waiting, self._waiting = list(self._waiting.values()), {}
        for started in waiting:
            _kill(started)


def _running_loop() -> asyncio.AbstractEventLoop | None:
    try:
        return asyncio.get_running_loop()
    except RuntimeError:
        return None


POOL = WarmPool()
atexit.register(_leave_sessions)


class _Ended(Exception):
    """agy ended without an answer event (``stderr``: its last line of errors)."""

    def __init__(self, stderr: str) -> None:
        super().__init__(stderr)
        self.stderr = stderr


class AntigravityCliProvider:
    label = LABEL
    local = False  # the CLI sends the request to Google's servers
    sizes_window = False

    def __init__(
        self,
        model: str = "",
        *,
        program: str = "",
        run_dir: Path | None = None,
        home: Path | None = None,
        warm: bool = True,
    ) -> None:
        self.model = model
        self.host = ""  # no address: a program on this computer
        self._program = program
        self._run_dir = run_dir or Path(platformdirs.user_state_dir("paper-pile")) / "agy"
        self._agy_home = home or default_home()  # the HOME agy runs with: the app's own
        self._home = data_dir(self._agy_home)  # where that agy keeps its data
        self._listed: dict[str, str] = {}
        self._warm = warm  # start the next agy ahead (WarmPool)

    def missing_model(self, model: str) -> str:
        return "pick one that `agy models` lists"

    # ---- running agy -------------------------------------------------------------------------

    def program(self) -> str | None:
        found = shutil.which(self._program or PROGRAM)
        if found:
            return found
        fallback = Path.home() / ".local" / "bin" / PROGRAM  # the installer's place
        return str(fallback) if not self._program and os.access(fallback, os.X_OK) else None

    def _prepare(self) -> Path:
        """The empty folder agy runs in, with the app's agents in it (and this process's
        session in the app's agy home begun)."""
        begin_session(self._agy_home)
        folder = self._run_dir / ".agents" / "agents"
        for name, text in AGENTS.items():
            agent = folder / f"{name}.md"
            if not agent.is_file() or agent.read_text(encoding="utf-8") != text:
                folder.mkdir(parents=True, exist_ok=True)
                agent.write_text(text, encoding="utf-8")
        return self._run_dir

    def command(self, program: str, model: str, schema: Any = None) -> list[str]:
        agent = AGENT if schema is None else JSON_AGENT
        cmd = [program, "--agent", agent, "--disable-slash-commands"]
        cmd += ["--settings", json.dumps({"toolPermission": "strict"})]
        if model:
            cmd += ["--model", model]
        if schema is not None:
            cmd += ["--json-schema", json.dumps(schema)]
        # -p last: it takes the next argument as its prompt (empty: the prompt is on stdin)
        return [*cmd, "--input-format", "stream-json", "--output-format", "stream-json", "-p", ""]

    async def chat(
        self,
        messages: Sequence[ChatMessage],
        *,
        model: str | None = None,
        options: GenerationOptions | None = None,
    ) -> AsyncIterator[str | Finish]:
        program = self.program()
        if program is None:
            raise ProviderUnavailableError(self._not_installed())
        name = model or self.model
        schema = dict(options.schema) if options is not None and options.schema else None
        try:
            cwd = self._prepare()
        except OSError as exc:
            raise ProviderError(f"{LABEL}: cannot prepare its folder ({exc}).") from exc
        message = {"event": "user", "message": {"role": "user", "content": flatten(messages)}}
        payload = (json.dumps(message) + "\n").encode("utf-8")
        cmd = self.command(program, name, schema)
        key = (str(cwd), *cmd)
        started = POOL.take(key) if self._warm else None
        pooled = started is not None
        if started is None:
            started = await self._launch(cmd, cwd)
        if self._warm:
            await POOL.fill(key, cmd, cwd, self._agy_home)  # the next request's agy starts now
        try:  # aclosing: a stopped answer must stop agy now, not when the generator is freed
            async with contextlib.aclosing(self._read(started, payload, schema, name)) as answer:
                async for piece in answer:
                    yield piece
        except _Ended as ended:
            if not pooled:
                raise self._failed(ended.stderr, name) from None
            # the one started ahead had ended while it waited: once more with a new one
            log.info("the agy started ahead had ended (%s); starting a new one", ended.stderr)
            started = await self._launch(cmd, cwd)
            try:
                async with contextlib.aclosing(
                    self._read(started, payload, schema, name)
                ) as answer:
                    async for piece in answer:
                        yield piece
            except _Ended as again:
                raise self._failed(again.stderr, name) from None

    async def _launch(self, cmd: Sequence[str], cwd: Path) -> Started:
        try:
            return await launch(cmd, cwd, self._agy_home)
        except OSError as exc:
            raise ProviderUnavailableError(f"{LABEL} could not be started ({exc}).") from exc

    async def _read(
        self, started: Started, payload: bytes, schema: Any, name: str
    ) -> AsyncGenerator[str | Finish]:
        """Send the request to ``started`` and yield its answer; :class:`_Ended` when it ended
        without answering at all (no answer event: died, or its pipe was closed)."""
        proc, errors = started.proc, started.errors
        conversation = ""
        answered = False
        try:
            # it may have ended already: what it printed (stdout / stderr) then says why
            with contextlib.suppress(BrokenPipeError, ConnectionResetError):
                await _write(started, payload)
            assert proc.stdout is not None
            async for raw in proc.stdout:
                event = _event(raw)
                if event is None:
                    continue
                conversation = conversation or _conversation_of(event)
                if event.get("event") == "step_update":
                    delta = (event.get("step_update") or {}).get("text_delta")
                    if delta and schema is None:  # a JSON answer comes whole, at the end
                        yield str(delta)
                elif event.get("event") == "result":
                    result = event.get("result") or {}
                    if result.get("status") != "SUCCESS":
                        raise self._failed(str(result.get("error") or ""), name)
                    if schema is not None:
                        found = result.get("structured_output")
                        yield (
                            json.dumps(found)
                            if found is not None
                            else str(result.get("response") or "")
                        )
                    usage = result.get("usage") or {}
                    answered = True
                    yield Finish("stop", usage.get("input_tokens"), usage.get("output_tokens"))
                    return
            await proc.wait()
            stderr = await errors
            raise _Ended(stderr.strip().splitlines()[-1] if stderr.strip() else "")
        finally:
            await _stop(proc, grace=2.0 if answered else 0.0)  # it exits once it has answered
            errors.cancel()
            self._forget(conversation)

    def _forget(self, conversation: str) -> None:
        """Delete the copy agy kept of a request (it holds the user's notes)."""
        forget(self._home, conversation)

    # ---- state -------------------------------------------------------------------------------

    async def _listing(self) -> dict[str, str]:
        """``agy models``, kept for :data:`LIST_KEEP_S`: the chat checks the AI's health every
        30 s, and each run is a whole agy start (seconds, a process, a log file)."""
        program = self.program()
        if program is None:
            raise ProviderUnavailableError(self._not_installed())
        key = (program, str(self._agy_home))
        kept = _LISTED.get(key)
        if kept is not None and time.monotonic() - kept[0] < LIST_KEEP_S:
            self._listed = dict(kept[1])
            return dict(kept[1])
        try:
            cwd = self._prepare()  # its own folder and home, never the app's working folder
        except OSError as exc:
            raise ProviderUnavailableError(f"{LABEL}: cannot prepare its folder ({exc}).") from exc
        proc = await asyncio.create_subprocess_exec(
            program,
            "models",
            cwd=cwd,
            env={**os.environ, "HOME": str(self._agy_home)},  # the app's own (module doc)
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            start_new_session=True,
        )
        try:
            out, _ = await asyncio.wait_for(proc.communicate(), LIST_TIMEOUT_S)
        except TimeoutError as exc:
            raise ProviderUnavailableError(f"{LABEL} did not answer (agy models).") from exc
        finally:
            await _stop(proc)
        text = out.decode("utf-8", "replace")
        listed = parse_models(text)
        if not listed:
            last = text.strip().splitlines()[-1] if text.strip() else "no models"
            raise ProviderUnavailableError(
                f"{LABEL} lists no models ({last}) — run `agy` once in a terminal to sign in."
            )
        self._listed = listed
        _LISTED[key] = (time.monotonic(), dict(listed))  # only a good listing is kept
        return listed

    async def models(self) -> list[str]:
        return list(await self._listing())

    async def context_length(self, model: str | None = None) -> int | None:
        name = (model or self.model).lower()
        return next((n for prefix, n in WINDOWS if name.startswith(prefix)), None)

    async def memory_use(self, model: str, num_ctx: int) -> tuple[int, int] | None:
        return None

    async def preload(self, model: str, options: GenerationOptions) -> bool:
        return False

    async def health(self) -> Health:
        try:
            listed = await self._listing()
        except ProviderError as exc:
            return Health(False, str(exc))
        return Health(True, "", list(listed), dict(listed))

    # ---- errors ------------------------------------------------------------------------------

    def _not_installed(self) -> str:
        return (
            f"{LABEL} (agy) is not installed or not on the PATH — install it, then run `agy` "
            "once in a terminal to sign in."
        )

    def _failed(self, error: str, model: str) -> ProviderError:
        text = error.strip() or "it stopped without an answer"
        if "not recognized as a known model" in text:
            return ModelNotFoundError(
                f"The model “{model}” is not in {LABEL} — {self.missing_model(model)}."
            )
        if any(w in text.lower() for w in ("auth", "sign in", "login", "credential")):
            return ProviderUnavailableError(
                f"{LABEL} is not signed in — run `agy` once in a terminal. ({text.splitlines()[0]})"
            )
        return ProviderError(f"{LABEL} said: {text.splitlines()[0]}")


async def _write(started: Started, payload: bytes) -> None:
    stdin = started.proc.stdin
    assert stdin is not None
    stdin.write(payload)
    await stdin.drain()
    stdin.close()


def _event(raw: bytes) -> dict[str, Any] | None:
    try:
        data = json.loads(raw)
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def _conversation_of(event: dict[str, Any]) -> str:
    if event.get("conversation_id"):  # agy 1.5's init event has it at the top level
        return str(event["conversation_id"])
    for key in ("init", "step_update", "result"):
        body = event.get(key)
        if isinstance(body, dict) and body.get("conversation_id"):
            return str(body["conversation_id"])
    return ""


async def _read_all(stream: asyncio.StreamReader | None) -> str:
    if stream is None:
        return ""
    return (await stream.read()).decode("utf-8", "replace")


async def _stop(proc: asyncio.subprocess.Process, grace: float = 0.0) -> None:
    """End ``proc`` and its children (it runs in its own process group), after ``grace``
    seconds for it to exit by itself."""
    if proc.returncode is None and grace > 0:
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(proc.wait(), grace)
    if proc.returncode is None:
        with contextlib.suppress(ProcessLookupError, PermissionError):
            os.killpg(proc.pid, signal.SIGTERM)
        try:
            await asyncio.wait_for(proc.wait(), 3.0)
        except TimeoutError:
            with contextlib.suppress(ProcessLookupError, PermissionError):
                os.killpg(proc.pid, signal.SIGKILL)
            await proc.wait()
