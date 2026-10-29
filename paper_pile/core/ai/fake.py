"""A deterministic stand-in for Ollama, for tests and for trying the UI without a model.

Selected by the environment variable ``PAPER_PILE_FAKE_AI=1``. It echoes the last user message
back word by word (without the notes sent in front of it).
"""

import asyncio
from collections.abc import AsyncIterator, Sequence

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

    def __init__(self, delay: float = 0.02, reply: str | None = None) -> None:
        self.delay = delay
        self.reply = reply
        self.calls: list[list[ChatMessage]] = []
        self.up = True
        self.options: GenerationOptions | None = None
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
        if self.fail_calls > 0:
            self.fail_calls -= 1
            raise ProviderError("the fake model failed")
        last = next((m.content for m in reversed(messages) if m.role == "user"), "")
        last = last.rsplit(DIVIDER, 1)[-1]
        text = self.reply if self.reply is not None else f"You said: {last.strip()[:200]}"
        if self.thinking:
            yield Reasoning(self.thinking)
        for n, word in enumerate(text.split(" ")):
            if self.fail_after is not None and n >= self.fail_after:
                raise ProviderError("the fake model stopped")
            await asyncio.sleep(self.delay)
            yield word + " "
        yield Finish(self.finish)

    async def models(self) -> list[str]:
        return ["fake-model", "fake-model-2"]

    async def context_length(self, model: str | None = None) -> int | None:
        return self.max_context

    async def health(self) -> Health:
        return (
            Health(True, "", ["fake-model", "fake-model-2"]) if self.up else Health(False, "down")
        )
