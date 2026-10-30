"""A deterministic stand-in for Ollama, for tests and for trying the UI without a model.

Selected by the environment variable ``PAPER_PILE_FAKE_AI=1``. It echoes the last user message
back word by word (without the notes sent in front of it). Tests can script its answers instead:
``script`` is a list of replies used one per call, or a function of the messages.
"""

import asyncio
from collections.abc import AsyncIterator, Callable, Sequence

from paper_pile.core.ai.context import DIVIDER
from paper_pile.core.ai.provider import (
    ChatMessage,
    Finish,
    GenerationOptions,
    Health,
    ProviderError,
    Reasoning,
)


class FakeProvider:
    host = "fake://local"

    def __init__(
        self,
        delay: float = 0.02,
        reply: str | None = None,
        script: list[str] | Callable[[list[ChatMessage]], str] | None = None,
    ) -> None:
        self.delay = delay
        self.reply = reply
        self.script = script
        self.calls: list[list[ChatMessage]] = []
        self.up = True
        self.options: GenerationOptions | None = None  # the last call's
        self.options_seen: list[GenerationOptions | None] = []
        self.max_context: int | None = 8192  # what context_length reports
        self.thinking = ""  # reasoning streamed before the answer (a thinking model)
        self.finish = "stop"  # why the answer ends ("length": cut at the answer limit)
        self.fail_after: int | None = None  # raise ProviderError after this many words
        self.fail_calls = 0  # make the next this many calls fail at once

    async def chat(
        self,
        messages: Sequence[ChatMessage],
        *,
        model: str | None = None,
        options: GenerationOptions | None = None,
    ) -> AsyncIterator[str | Reasoning | Finish]:
        self.calls.append(list(messages))
        self.options = options
        self.options_seen.append(options)
        if self.fail_calls > 0:
            self.fail_calls -= 1
            raise ProviderError("the fake model failed")
        text = self._answer(list(messages))
        if self.thinking:
            yield Reasoning(self.thinking)
        words = text.split(" ")
        for n, word in enumerate(words):
            if self.fail_after is not None and n >= self.fail_after:
                raise ProviderError("the fake model stopped")
            await asyncio.sleep(self.delay)
            # a scripted reply comes back exactly; the echo keeps its old trailing space
            yield word + (" " if n < len(words) - 1 or self.script is None else "")
        yield Finish(self.finish)

    def _answer(self, messages: list[ChatMessage]) -> str:
        if callable(self.script):
            return self.script(messages)
        if self.script is not None:
            if not self.script:
                raise ProviderError("the fake model's script has no more replies")
            return self.script.pop(0)
        if self.reply is not None:
            return self.reply
        last = next((m.content for m in reversed(messages) if m.role == "user"), "")
        return f"You said: {last.rsplit(DIVIDER, 1)[-1].strip()[:200]}"

    async def models(self) -> list[str]:
        return ["fake-model", "fake-model-2"]

    async def context_length(self, model: str | None = None) -> int | None:
        return self.max_context

    async def health(self) -> Health:
        return (
            Health(True, "", ["fake-model", "fake-model-2"]) if self.up else Health(False, "down")
        )
