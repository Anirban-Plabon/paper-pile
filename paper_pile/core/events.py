"""Simple pub/sub so core can notify any UI without importing it."""

import logging
from collections import defaultdict
from collections.abc import Callable
from typing import Any

log = logging.getLogger("paper_pile.events")

Handler = Callable[..., None]


class EventBus:
    """Synchronous topic-based event bus.

    Handler exceptions are logged and never propagate to the publisher.
    """

    def __init__(self) -> None:
        self._handlers: dict[str, list[Handler]] = defaultdict(list)

    def subscribe(self, topic: str, handler: Handler) -> Callable[[], None]:
        """Register ``handler`` for ``topic``; returns an unsubscribe callable."""
        self._handlers[topic].append(handler)

        def unsubscribe() -> None:
            if handler in self._handlers[topic]:
                self._handlers[topic].remove(handler)

        return unsubscribe

    def publish(self, topic: str, **payload: Any) -> None:
        """Call every handler of ``topic`` with ``payload`` as keyword arguments."""
        for handler in list(self._handlers.get(topic, ())):
            try:
                handler(**payload)
            except Exception:
                log.exception("handler for %r failed", topic)
