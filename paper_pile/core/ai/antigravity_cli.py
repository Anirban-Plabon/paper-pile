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

``agy`` keeps a copy of every conversation under ``~/.gemini/antigravity-cli``; the app's
requests carry notes, so each one's files are deleted when its answer is in. It streams no
reasoning and takes no temperature, top-p or answer limit: those options are dropped.
"""

import asyncio
import contextlib
import json
import logging
import os
import re
import shutil
import signal
from collections.abc import AsyncIterator, Sequence
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
STREAM_LIMIT = 64 * 1024 * 1024  # one stdout line holds a whole answer
# the window the app fills with note context: the models take more, but a full million-token
# prompt per request would be slow and costly
WINDOWS = (("gemini", 131072), ("claude", 131072), ("gpt", 131072))
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
    ) -> None:
        self.model = model
        self.host = ""  # no address: a program on this computer
        self._program = program
        self._run_dir = run_dir or Path(platformdirs.user_state_dir("paper-pile")) / "agy"
        self._home = home or Path.home() / ".gemini" / "antigravity-cli"
        self._listed: dict[str, str] = {}

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
        """The empty folder agy runs in, with the app's agents in it."""
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
        proc = await asyncio.create_subprocess_exec(
            *self.command(program, name, schema),
            cwd=cwd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            start_new_session=True,  # cancelling stops agy and whatever it started
            limit=STREAM_LIMIT,
        )
        errors = asyncio.create_task(_read_all(proc.stderr))
        conversation = ""
        answered = False
        try:
            assert proc.stdin is not None and proc.stdout is not None
            proc.stdin.write((json.dumps(message) + "\n").encode("utf-8"))
            await proc.stdin.drain()
            proc.stdin.close()
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
            raise self._failed(stderr.strip().splitlines()[-1] if stderr.strip() else "", name)
        finally:
            await _stop(proc, grace=2.0 if answered else 0.0)  # it exits once it has answered
            errors.cancel()
            self._forget(conversation)

    def _forget(self, conversation: str) -> None:
        """Delete the copy agy kept of a request (it holds the user's notes)."""
        if not _ID.fullmatch(conversation):
            return
        for path in (
            self._home / "conversations" / f"{conversation}.db",
            self._home / "conversations" / f"{conversation}.db-wal",
            self._home / "conversations" / f"{conversation}.db-shm",
            self._home / "annotations" / f"{conversation}.pbtxt",
            self._home / "presence" / f"{conversation}.lock",
        ):
            with contextlib.suppress(OSError):
                path.unlink(missing_ok=True)
        brain = self._home / "brain" / conversation
        if brain.is_dir() and not brain.is_symlink():
            shutil.rmtree(brain, ignore_errors=True)

    # ---- state -------------------------------------------------------------------------------

    async def _listing(self) -> dict[str, str]:
        program = self.program()
        if program is None:
            raise ProviderUnavailableError(self._not_installed())
        proc = await asyncio.create_subprocess_exec(
            program,
            "models",
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


def _event(raw: bytes) -> dict[str, Any] | None:
    try:
        data = json.loads(raw)
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def _conversation_of(event: dict[str, Any]) -> str:
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
