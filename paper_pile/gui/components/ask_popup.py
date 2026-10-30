"""The Ask box under a selection (PLAN §4.27).

A settled selection opens a box like the chat's composer (without ``+``) under it, with *Move to
chat* beside it. A question grows it into a small floating chat about the text; a request to
rewrite it dissolves the box at once and the AI's version replaces the text when it is complete.
``/`` lists the AI commands (PLAN §4.28) and Delete. ``static/askpop.js`` places the
box, drags the mini chat and reports keys and clicks outside it; what a message does is decided
in core (``core/ai/selection_ask.py``) and the editor pane applies the result.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import Awaitable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal

from nicegui import Client, background_tasks, ui

from paper_pile.core.ai.access import AccessDeniedError
from paper_pile.core.ai.ask_route import route
from paper_pile.core.ai.commands import AiCommand, ai_command
from paper_pile.core.ai.edit_run import Again, EditEnd
from paper_pile.core.ai.edits import FINISHED, EditTooLongError
from paper_pile.core.ai.options import Option, suggest_options
from paper_pile.core.ai.provider import ProviderError
from paper_pile.core.ai.selection_ask import DELETE, AskTurn, Role, box_commands
from paper_pile.core.commands import CommandContext
from paper_pile.core.parser import render_chat_html
from paper_pile.gui.components.ai_access import confirm_access
from paper_pile.gui.components.chat import RENDER_EVERY_S, THINKING
from paper_pile.gui.components.options_box import OptionsBox
from paper_pile.gui.icons import ico, line_icon, set_icon
from paper_pile.gui.tips import tip

if TYPE_CHECKING:
    from paper_pile.gui.components.editor_pane import EditorPane

log = logging.getLogger("paper_pile.gui.ask_popup")

PLACEHOLDER = "Ask about this, or / for commands"
CARET_PLACEHOLDER = "What should it write?"
Mode = Literal["closed", "box", "chat", "gone"]  # gone: dissolved while a rewrite runs
QUIET_S = 1.0  # after a rewrite / delete: the selection its edit settles again opens no box


@dataclass(frozen=True, slots=True)
class AskTarget:
    """The selected text the box is about: its tab, note and JavaScript offsets when chosen."""

    tab_id: int
    path: str
    text: str
    start: int
    end: int
    whole: bool = False  # nothing selected: the note's body (a command from the palette)


@dataclass(slots=True)
class _Entry:
    """One message in the mini chat: what was sent (``text``), what is shown, how it ended."""

    role: Role
    text: str
    shown: str = ""
    command: str = ""  # a / command's title, shown before the user's words in the accent colour
    finished: bool = False
    error: str = ""
    options: tuple[Option, ...] = ()  # the AI's options: for ``command_id`` run without words,
    command_id: str = ""  # or the user's messy request rewritten as clearer ones
    options_title: str = ""
    translate: bool = False  # a Translate answer: Replace / Insert below / Copy under it
    actions: tuple[Action, ...] = ()  # buttons under a change that ended without a diff
    again: _Asked | None = None  # what those buttons run again


Action = Literal["again", "anyway", "change"]
ACTION_LABELS: dict[Action, str] = {
    "again": "Try again",
    "anyway": "Add it anyway",
    "change": "Change request",
}


@dataclass(frozen=True, slots=True)
class _Asked:
    """A change request as the user made it: the command, their words, the command's title
    ("" for a typed request), and whether the AI could answer with options."""

    command_id: str
    words: str
    title: str
    offer: bool
    groups: tuple[str, ...] = ()


class AskPopup:
    def __init__(self, pane: EditorPane) -> None:
        self._pane = pane
        self._client: Client = ui.context.client
        self._target: AskTarget | None = None
        self._entries: list[_Entry] = []
        self._task: asyncio.Task[None] | None = None
        self._rewriting = False
        self._streaming = False  # an answer is coming into the mini chat
        self._quiet_until = 0.0
        self._caret: asyncio.Future[str | None] | None = None  # Ask… at the caret: the question
        self._command: tuple[str, str] | None = None  # the / command picked: (id, title)
        self._mode: Mode = "closed"
        self._rect: dict[str, Any] = {}  # where the box was placed (to bring it back there)
        self._answering: _Asked | None = None  # the AI asked a question: the next message answers
        self._build()
        ui.on("pp_askpop_send", lambda _e: self._enter())
        ui.on("pp_askpop_pick", lambda e: self._pick(str(e.args.get("id", ""))))
        ui.on("pp_askpop_close", lambda e: self._outside(bool(e.args.get("key"))))
        ui.on("pp_askpop_unchip", lambda _e: self._set_command(None))

    # ---- drawing --------------------------------------------------------------------------

    def _build(self) -> None:
        # in <body>: a fixed box inside the editor pane would be clipped by the panes beside it
        with ui.teleport("body"):
            self._root = ui.element("div").classes("pp-askpop")
        with self._root:
            with ui.row().classes("pp-askpop-head items-center no-wrap"):  # the mini chat's
                line_icon("sparkles", "s").classes("pp-askpop-head-icon")
                ui.label("Ask AI").classes("pp-askpop-title")
                close = ui.button(icon=ico("x"), on_click=self.close, color=None)
                close.props("flat dense").classes("pp-icon-btn pp-i-s pp-askpop-close")
                tip(close, "Close (Esc)")
            self._log = ui.column().classes("pp-askpop-log")
            self._cmds = ui.column().classes("pp-askpop-cmds")
            self._cmds.set_visibility(False)
            # the composer's card and row (static/chat.js fits the text box), Move to chat beside
            with ui.row().classes("pp-askpop-bottom items-end no-wrap"):
                with (
                    ui.column().classes("pp-chat-card pp-askpop-card"),
                    ui.row().classes("pp-chat-row pp-askpop-row items-end no-wrap w-full"),
                ):
                    # the picked / command, in the accent colour (Backspace in an empty box: gone)
                    self._chip = ui.label("").classes("pp-chat-plus pp-askpop-chip")
                    self._chip.set_visibility(False)
                    self._input = (
                        ui.textarea(placeholder=PLACEHOLDER)
                        .props("borderless dense autogrow input-style='max-height: 160px'")
                        .classes("pp-chat-input pp-askpop-input")
                    )
                    self._input.on_value_change(lambda e: self._typed(e.value or ""))
                    self._send = ui.button(
                        icon=ico("arrow-up"), on_click=self._send_or_stop, color=None
                    )
                    self._send.props("round unelevated dense").classes("pp-chat-send")
                # a chat bubble with an arrow (the app's own icon, tools/editor_src/build_icons.mjs)
                chat = ui.button(icon=ico("message-square-arrow-right"), color=None)
                chat.on("click", self._move_to_chat)
                chat.props("round flat dense").classes("pp-askpop-to-chat")
                tip(chat, "Move to chat")
        self._set_mode("closed")

    def _set_mode(self, mode: Mode) -> None:
        self._mode = mode
        others = " ".join(f"pp-askpop-{m}" for m in ("box", "chat", "gone") if m != mode)
        self._root.classes(remove=others)
        if mode != "closed":
            self._root.classes(add=f"pp-askpop-{mode}")
        self._root.set_visibility(mode != "closed")

    def _js(self, code: str) -> None:
        self._client.run_javascript(code)

    # ---- opening and closing --------------------------------------------------------------

    async def ask_at_caret(self, rect: dict[str, float]) -> str | None:
        """The Ask… command: the box at the caret (in place of a dialog); the question, or None
        when it was closed. The answer is written at the caret (``EditorPane._run_stream``)."""
        if self._rewriting:
            return None
        self.close()
        self._caret = asyncio.get_running_loop().create_future()
        self._show_hint()
        self._set_mode("box")
        self._js(f"window.ppAskPlace && window.ppAskPlace({json.dumps(rect)})")
        try:
            return await self._caret
        finally:
            self._caret = None
            self._show_hint()

    def on_selection(self, args: dict[str, Any]) -> None:
        """The editor reported a settled selection (or that it was cleared)."""
        if args.get("docId") != self._pane.tabs.active or self._rewriting or self._caret:
            return
        if time.monotonic() < self._quiet_until:
            return
        if args.get("clear"):
            whole = self._target is not None and self._target.whole  # not about a selection
            if self._mode == "box" and not (self._input.value or "").strip() and not whole:
                self.close()
            return
        path = self._pane.ask_path()
        engine = self._pane.ai_engine
        if path is None or engine is None:
            return
        if self._mode == "chat":
            self.close()  # the mini chat was about the text selected before
        self._target = AskTarget(
            int(args["docId"]), path, str(args["text"]), int(args["from"]), int(args["to"])
        )
        self._pane.mark_ask_target(self._target)
        self._render_commands()
        self._set_mode("box")
        self._rect = dict(args.get("rect") or {})
        self._js(f"window.ppAskPlace && window.ppAskPlace({json.dumps(self._rect)})")
        if args.get("command"):  # picked in the editor's own slash menu: as if picked here
            self._pick(str(args["command"]))

    def open_whole(self, target: AskTarget, rect: dict[str, Any], command_id: str) -> None:
        """The box at the caret with ``command_id`` picked, the whole note as its text (an AI
        command from the palette or the slash menu with nothing selected, PLAN §4.28)."""
        if self._rewriting:
            return
        self.close()
        self._target = target
        self._rect = dict(rect)
        self._render_commands()
        self._set_mode("box")
        self._js(f"window.ppAskPlace && window.ppAskPlace({json.dumps(self._rect)})")
        self._pick(command_id)

    def close(self) -> None:
        """×, Esc, a click outside: the box goes (an answer still coming is stopped; a rewrite
        running is not: the "AI is writing…" notice's Stop stops it)."""
        if self._rewriting:
            return
        if self._task is not None and self._task is not asyncio.current_task():
            self._task.cancel()
        if self._caret is not None and not self._caret.done():
            self._caret.set_result(None)
        self._target = None
        self._entries = []
        self._answering = None
        self._log.clear()
        self._input.set_value("")
        self._set_command(None)
        self._pane.mark_ask_target(None)
        self._set_mode("closed")

    def _outside(self, key: bool) -> None:
        """Esc (``key``: the caret goes back to the note) or a mouse-down outside the box."""
        if self._mode in ("box", "chat"):
            self.close()
            if key:
                self._pane.focus_note()

    def _stop(self) -> None:
        if self._task is not None:
            self._task.cancel()

    # ---- what the user sends --------------------------------------------------------------

    def _typed(self, value: str) -> None:
        self._render_commands(value)
        self._send_ready()

    def _send_ready(self) -> None:
        """Send turns full accent (white arrow) once there is something to send, as the chat's."""
        ready = bool((self._input.value or "").strip()) or self._command is not None
        self._send.classes(
            add="pp-chat-send-ready" if ready else "", remove="" if ready else "pp-chat-send-ready"
        )

    def _enter(self) -> None:
        if self._task is None:
            self._spawn(self._send_text())

    async def _send_or_stop(self) -> None:
        if self._task is not None:
            self._stop()
        else:
            await self._send_text()

    async def _send_text(self) -> None:
        text = (self._input.value or "").strip()
        if self._caret is not None:  # Ask… at the caret: hand the question over
            if text and not self._caret.done():
                self._caret.set_result(text)
                self.close()
                self._pane.focus_note()  # the answer is written there
            return
        if self._target is None or self._task is not None:
            return
        if self._answering is not None and text and self._command is None:
            asked, self._answering = self._answering, None
            self._input.set_value("")
            words = f"{asked.words}\nAnswer: {text}".strip()
            self._start(self._rewrite(asked.command_id, words, asked.title, offer=False))
            return
        if self._command is not None:  # the picked command, with what the user added to it
            command_id, title = self._command
            self._input.set_value("")
            self._set_command(None)
            self._run_command(command_id, title, text)
            return
        if not text:
            return
        if text.startswith("/"):
            found = self._commands(text[1:])
            if found:
                self._pick(found[0][0])
                return
        self._start(self._route(text))

    async def _route(self, text: str) -> None:
        """A typed message changes the text or asks about it (``ask_route``: clear first words
        decide, else the model). The words stay in the box until it is decided."""
        target, engine = self._target, self._pane.ai_engine
        if target is None or engine is None:
            return
        if not await confirm_access(engine, self._root):
            return
        found = await route(engine, text, target.text)
        if self._target is not target:  # the box was closed meanwhile
            return
        self._input.set_value("")
        if found == "edit":
            await self._rewrite("ai-rewrite", text)
        else:
            await self._ask(text, text)

    def _pick(self, command_id: str) -> None:
        """A command from the ``/`` list: shown in the box; Enter runs it (with any words the
        user adds after it)."""
        found = {c[0]: c[1] for c in self._commands("")}
        if self._target is None or self._task is not None or command_id not in found:
            return
        self._input.set_value("")
        self._set_command((command_id, found[command_id]))
        self._js("window.ppAskFocus && window.ppAskFocus()")

    def _set_command(self, command: tuple[str, str] | None) -> None:
        self._command = command
        self._chip.set_text(f"/{command[1]}" if command else "")
        self._chip.set_visibility(command is not None)
        self._show_hint()
        self._render_commands()
        self._send_ready()

    def _show_hint(self) -> None:
        hint = "Add details" if self._command else CARET_PLACEHOLDER if self._caret else PLACEHOLDER
        self._input.props(f'placeholder="{hint}"')
        self._js(  # fit the box to the new placeholder (static/chat.js)
            "document.querySelectorAll('.pp-askpop textarea')"
            ".forEach(a => window.ppChatFit && window.ppChatFit(a))"
        )

    def _run_command(self, command_id: str, title: str, extra: str) -> None:
        target = self._target
        if target is None:
            return
        if command_id == DELETE:
            self._start(self._delete())
            return
        cmd = ai_command(command_id)  # the words added after it are its instruction (§4.28)
        if cmd is None:
            return
        if not extra.strip():  # no words: the AI suggests options first (PLAN §4.28)
            self._start(self._offer(cmd))
        elif cmd.kind == "change":
            self._start(self._rewrite(cmd.id, extra, title))
        elif cmd.kind == "answer":  # written into the note under the text (PLAN §4.28)
            self._start(self._write(cmd.id, extra))
        else:  # Translate: shown here; the user pushes it into the note (AI_EDITS §7)
            self._start(self._ask(cmd.instruction(extra), extra, title, translate=True))

    def _move_to_chat(self) -> None:
        """*Move to chat*: the selection goes to the chat box; once the box holds answers, the
        whole conversation moves to the chat (and is saved there). From Ask… at the caret: the
        question is asked in the chat instead."""
        if self._caret is not None:
            question = (self._input.value or "").strip()
            path = self._pane.ask_path()
            self.close()
            if path is not None:
                self._pane.ask_chat(path, question, bool(question))
            return
        target = self._target
        if target is None or self._streaming:
            return
        turns = [
            AskTurn(e.role, f"/{e.command} {e.shown}".strip() if e.command else e.shown or e.text)
            for e in self._entries
            if e.text.strip() and not e.error
        ]
        has_answer = any(t.role == "assistant" for t in turns)
        self.close()
        self._pane.add_selection_to_chat(target, turns if has_answer else ())

    def _start(self, work: Awaitable[None]) -> None:
        async def run() -> None:
            try:
                await work
            except asyncio.CancelledError:
                pass
            except Exception:
                log.exception("the Ask box failed")
                with self._root:
                    ui.notify("Something went wrong; see the log.", type="negative")
            finally:
                self._task = None
                set_icon(self._send, "arrow-up")

        self._task = background_tasks.create(run())
        set_icon(self._send, "square")

    def _spawn(self, work: Awaitable[None]) -> None:
        background_tasks.create(work)  # type: ignore[arg-type]

    # ---- a rewrite or a delete: the box dissolves at once ----------------------------------

    async def _rewrite(
        self,
        command_id: str,
        words: str,
        title: str = "",
        *,
        offer: bool = True,
        how: Again = "again",
        groups: tuple[str, ...] = (),
    ) -> None:
        """A change (PLAN §4.29): the box goes, the text pulses while the AI works, and the
        result is shown as a diff in the note. When there is no diff the box comes back with
        why: the AI's clearer requests as options (a messy request; ``offer``: it may), its
        question, or the reason nothing changed with Try again / Change request (PLAN §4.28).
        ``how``: started by one of those buttons."""
        target = self._target
        if target is None:
            return
        self._rewriting = True
        self._set_mode("gone")
        self._pane.focus_note()
        self._pane.mark_ask_target(target, busy=True)  # the text pulses until it is replaced
        try:
            end = await self._pane.edit_selection(
                target, command_id, words, options=offer, how=how, groups=groups
            )
        finally:
            self._rewriting = False
            self._quiet_until = time.monotonic() + QUIET_S
            self.close()
        if end.kind != "proposal":
            self._show_end(target, end, _Asked(command_id, words, title, offer, groups))

    def _show_end(self, target: AskTarget, end: EditEnd, asked: _Asked) -> None:
        """The mini chat back at the text with how the change ended."""
        self._reopen(target, _Entry("user", "", asked.words, asked.title))
        if end.kind == "options":
            reply = _Entry(
                "assistant",
                "",
                options=tuple(Option(o) for o in end.options),
                command_id=asked.command_id,
                options_title="Which of these do you mean? Pick one or more:",
            )
        else:
            actions: tuple[Action, ...] = ("change",)
            if end.kind == "already":
                actions = ("anyway", "change")
            elif end.retry and end.kind != "question":
                actions = ("again", "change")
            if end.kind == "question":
                self._answering = asked  # the next message answers it
            failed = end.kind == "failed"
            reply = _Entry(
                "assistant",
                "" if failed else end.message,
                finished=True,
                error=end.message if failed else "",
                actions=actions,
                again=asked,
            )
        self._entries.append(reply)
        self._render_log()

    def _act(self, entry: _Entry, action: Action) -> None:
        """A button under a change that ended without a diff."""
        asked = entry.again
        if asked is None or self._task is not None or entry not in self._entries:
            return
        entry.actions = ()
        self._answering = None
        if action == "change":  # the request back in the box, to edit and send again
            self._render_log()
            command = ai_command(asked.command_id)
            self._set_command((asked.command_id, asked.title) if asked.title and command else None)
            self._input.set_value(asked.words)
            self._send_ready()
            self._js("window.ppAskFocus && window.ppAskFocus()")
            return
        how: Again = "anyway" if action == "anyway" else "again"
        offer = asked.offer and action == "again"
        self._start(
            self._rewrite(
                asked.command_id,
                asked.words,
                asked.title,
                offer=offer,
                how=how,
                groups=asked.groups,
            )
        )

    def _reopen(self, target: AskTarget, first: _Entry) -> None:
        """The mini chat back at ``target`` (where the box was), starting with ``first``."""
        self._target = target
        self._entries = [first]
        self._answering = None
        if not target.whole:  # a tint over the whole note would say nothing
            self._pane.mark_ask_target(target)
        self._set_mode("chat")
        self._js(f"window.ppAskPlace && window.ppAskPlace({json.dumps(self._rect)})")

    async def _write(self, command_id: str, words: str) -> None:
        """An answer command: the box goes and the answer is written into the note under the
        text (the editor's "AI is writing…" notice has Stop)."""
        target = self._target
        if target is None:
            return
        self.close()
        self._quiet_until = time.monotonic() + QUIET_S
        self._pane.focus_note()
        await self._pane.write_answer(target, command_id, words)

    async def _delete(self) -> None:
        target = self._target
        if target is None:
            return
        self.close()
        self._quiet_until = time.monotonic() + QUIET_S
        await self._pane.delete_selection(target)
        self._pane.focus_note()

    # ---- a command without words: the AI's options ----------------------------------------

    async def _offer(self, cmd: AiCommand) -> None:
        """The mini chat opens with the AI's options for ``cmd`` on the text; Apply runs the
        command with the ticked ones as its words."""
        target, engine = self._target, self._pane.ai_engine
        if target is None or engine is None:
            return
        if not await confirm_access(engine, self._root):
            return
        found = await self._pane.ask_target_text(target, live=False)
        if found is None:
            with self._root:
                ui.notify("The text changed; select it again.", type="negative")
            return
        self._entries.append(_Entry("user", "", "", cmd.title))
        reply = _Entry("assistant", "", command_id=cmd.id)
        self._entries.append(reply)
        self._set_mode("chat")
        self._streaming = True
        self._render_log()
        try:
            options = await suggest_options(
                engine, cmd, path=target.path, note=found[0], target=target.text
            )
            reply.options = tuple(options)
        except AccessDeniedError as exc:
            reply.error = str(exc)
        finally:
            self._streaming = False
            if self._mode == "chat":
                self._render_log()

    def _apply_options(self, entry: _Entry, instruction: str, groups: tuple[str, ...]) -> None:
        """Apply in the options box: the offer leaves the mini chat and the command runs with
        ``instruction`` as its words (as if typed after it)."""
        cmd = ai_command(entry.command_id)
        if cmd is None or self._task is not None or entry not in self._entries:
            return
        at = self._entries.index(entry)
        del self._entries[max(0, at - 1) : at + 1]  # the offer and the command that asked for it
        if cmd.kind == "change":  # options picked: the AI does not offer options again
            # a typed request's options (no command chip) stay without the command's title
            title = cmd.title if any(e.command for e in self._entries[:at]) else ""
            self._start(self._rewrite(cmd.id, instruction, title, offer=False, groups=groups))
        elif cmd.kind == "answer":
            self._start(self._write(cmd.id, instruction))
        else:
            task = cmd.instruction(instruction)
            self._start(self._ask(task, instruction, cmd.title, translate=True))

    # ---- a question: the mini chat --------------------------------------------------------

    async def _ask(
        self, task: str, shown: str, command: str = "", *, translate: bool = False
    ) -> None:
        target, engine = self._target, self._pane.ai_engine
        if target is None or engine is None:
            return
        if not await confirm_access(engine, self._root):
            self._input.set_value(shown if shown == task else "")
            return
        found = await self._pane.ask_target_text(target, live=False)
        if found is None:
            with self._root:
                ui.notify("The text changed; select it again.", type="negative")
            return
        note_text = found[0]
        turns = [AskTurn(e.role, e.text) for e in self._entries if not e.error and e.text]
        self._entries.append(_Entry("user", task, shown, command))
        reply = _Entry("assistant", "", translate=translate)
        self._entries.append(reply)
        self._set_mode("chat")
        self._streaming = True
        body = self._render_log()
        finish: list[str] = []
        try:
            messages = await engine.selection_messages(
                path=target.path,
                text=note_text,
                selected=target.text,
                turns=[*turns, AskTurn("user", task)],
            )
            last = 0.0
            think = False if translate else None  # a translation needs no reasoning first
            async for piece in engine.stream(messages, on_finish=finish.append, think=think):
                reply.text += piece
                now = time.monotonic()
                if body is not None and now - last >= RENDER_EVERY_S:
                    last = now
                    body.set_content(render_chat_html(reply.text))
                    self._scroll_down()
            reply.finished = finish[-1:] == [FINISHED]
            if not reply.finished and reply.text:
                reply.text += "\n\n*(cut off)*"
        except asyncio.CancelledError:
            if reply.text:
                reply.text += "\n\n*(stopped)*"
            else:
                reply.error = "Stopped."
            raise
        except (ProviderError, AccessDeniedError, EditTooLongError) as exc:
            reply.error = str(exc)
        finally:
            self._streaming = False
            if self._mode == "chat":
                self._render_log()

    def _render_log(self) -> ui.html | None:
        """Draw the mini chat; returns the body of the answer still coming, if any."""
        self._log.clear()
        live: ui.html | None = None
        with self._log:
            for entry in self._entries:
                if entry.role == "user":
                    with (
                        ui.column().classes("pp-msg pp-msg-user"),
                        ui.element("div").classes("pp-msg-text"),
                    ):
                        if entry.command:
                            ui.label(f"/{entry.command}").classes("pp-askpop-msg-cmd")
                        if entry.shown or not entry.command:
                            ui.label(entry.shown or entry.text).classes("pp-askpop-msg-words")
                    continue
                classes = "pp-msg pp-msg-ai" + (" pp-msg-error" if entry.error else "")
                if entry.options:
                    with ui.column().classes(classes):
                        OptionsBox(
                            entry.options,
                            lambda i, g, e=entry: self._apply_options(e, i, g),
                            title=entry.options_title,
                        )
                    continue
                with ui.column().classes(classes):
                    waiting = not entry.text and not entry.error and self._streaming
                    content = THINKING if waiting else render_chat_html(entry.error or entry.text)
                    body = ui.html(content, sanitize=False).classes("pp-msg-body")
                    if entry is self._entries[-1] and self._streaming:
                        live = body
                    if entry.translate and entry.finished and not self._streaming:
                        self._push_buttons(entry)
                    if entry.actions:
                        with ui.row().classes("pp-ai-actions items-center"):
                            for action in entry.actions:
                                button = ui.button(
                                    ACTION_LABELS[action],
                                    on_click=lambda _e, a=action, en=entry: self._act(en, a),
                                    color=None,
                                )
                                main = " pp-ai-action-main" if action != "change" else ""
                                button.props("flat no-caps dense")
                                button.classes("pp-ai-action" + main)
                    self._js(
                        "window.ppTypeset && window.ppTypeset("
                        f"document.getElementById('c{body.id}'))"
                    )
        self._scroll_down()
        return live

    def _push_buttons(self, entry: _Entry) -> None:
        """Under a Translate answer: Replace (a selection only), Insert below, Copy; Read-only
        leaves only Copy."""
        target = self._target
        pushes = [] if self._pane.ai_readonly() or target is None else ["insert"]
        if pushes and target is not None and not target.whole:
            pushes.insert(0, "replace")
        labels = {"replace": "Replace", "insert": "Insert below", "copy": "Copy"}
        with ui.row().classes("pp-ai-actions items-center"):
            for i, push in enumerate([*pushes, "copy"]):
                button = ui.button(
                    labels[push],
                    on_click=lambda _e, p=push, en=entry: self._push(en, p),
                    color=None,
                )
                main = " pp-ai-action-main" if i == 0 and push != "copy" else ""
                button.props("flat no-caps dense").classes(f"pp-ai-action pp-ai-push-{push}{main}")

    def _push(self, entry: _Entry, push: str) -> None:
        target = self._target
        if target is None or self._task is not None:
            return
        if push == "copy":
            text = json.dumps(entry.text)
            self._js(f"navigator.clipboard && navigator.clipboard.writeText({text})")
            with self._root:
                ui.notify("Copied", timeout=1200, position="bottom")
            return
        self.close()
        self._quiet_until = time.monotonic() + QUIET_S
        if push == "replace":
            self._spawn(self._pane.replace_with_answer(target, entry.text))
        else:
            self._spawn(self._pane.insert_answer_below(target, entry.text))

    def _scroll_down(self) -> None:
        self._js(f"window.ppChatScroll && window.ppChatScroll('c{self._log.id}')")

    # ---- the / list -----------------------------------------------------------------------

    def _commands(self, query: str) -> list[tuple[str, str, str, str]]:
        """``(id, title, subtitle, icon)`` of the ``/`` entries matching ``query``."""
        target = self._target
        if target is None:
            return []
        ctx = CommandContext(target.path, target.text, 0, selection=(0, len(target.text)))
        found = box_commands(query, ctx)
        if target.whole:  # Delete is for a selection, never the whole note
            found = [c for c in found if c.id != DELETE]
        return [(c.id, c.title, c.subtitle, c.icon) for c in found]

    def _render_commands(self, value: str = "") -> None:
        shown = (
            self._command is None
            and value.startswith("/")
            and "\n" not in value
            and " " not in value.rstrip()
        )
        hits = self._commands(value[1:]) if shown else []
        if not hits and not self._cmds.default_slot.children:
            return  # nothing listed before or now: no redraw per keystroke
        self._cmds.clear()
        with self._cmds:
            for i, (command_id, title, subtitle, icon) in enumerate(hits):
                row = ui.row().classes(
                    "pp-askpop-cmd items-center no-wrap"
                    + (" pp-askpop-cmd-active" if i == 0 else "")
                )
                row.props(f'data-id="{command_id}"')
                with row:
                    if icon:
                        line_icon(icon, "s")
                    ui.label(title).classes("pp-askpop-cmd-title")
                    if subtitle:
                        ui.label(subtitle).classes("pp-muted pp-askpop-cmd-sub")
                row.on("mousedown.prevent", lambda _e, c=command_id: self._pick(c))
        self._cmds.set_visibility(bool(hits))
