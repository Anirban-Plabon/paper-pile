"""A deterministic stand-in for Ollama, for tests and for trying the UI without a model.

Selected by the environment variable ``PAPER_PILE_FAKE_AI=1``. It echoes the last user message
back word by word.
"""

import asyncio
from collections.abc import AsyncIterator, Sequence

from paper_pile.core.ai.provider import ChatMessage, GenerationOptions, Health


class FakeProvider:
    host = "fake://local"

    def __init__(self, delay: float = 0.02, reply: str | None = None) -> None:
        self.delay = delay
        self.reply = reply
        self.calls: list[list[ChatMessage]] = []
        self.up = True
        self.options: GenerationOptions | None = None

    async def chat(
        self,
        messages: Sequence[ChatMessage],
        *,
        model: str | None = None,
        options: GenerationOptions | None = None,
    ) -> AsyncIterator[str]:
        self.calls.append(list(messages))
        self.options = options
        last = next((m.content for m in reversed(messages) if m.role == "user"), "")
        text = self.reply if self.reply is not None else f"You said: {last.strip()[:200]}"
        for word in text.split(" "):
            await asyncio.sleep(self.delay)
            yield word + " "

    async def embed(self, texts: Sequence[str], *, model: str | None = None) -> list[list[float]]:
        return [[float(len(t))] for t in texts]

    async def models(self) -> list[str]:
        return ["fake-model", "fake-model-2"]

    async def health(self) -> Health:
        return (
            Health(True, "", ["fake-model", "fake-model-2"]) if self.up else Health(False, "down")
        )
