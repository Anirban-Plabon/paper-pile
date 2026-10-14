import logging

import pytest

from paper_pile.core.events import EventBus


def test_publish_calls_subscribers_with_payload() -> None:
    bus = EventBus()
    got: list[dict[str, object]] = []
    bus.subscribe("note.saved", lambda **kw: got.append(kw))
    bus.publish("note.saved", path="a.md")
    assert got == [{"path": "a.md"}]


def test_topics_are_isolated() -> None:
    bus = EventBus()
    got: list[str] = []
    bus.subscribe("a", lambda **kw: got.append("a"))
    bus.publish("b")
    assert got == []


def test_unsubscribe() -> None:
    bus = EventBus()
    got: list[int] = []
    off = bus.subscribe("t", lambda **kw: got.append(1))
    bus.publish("t")
    off()
    off()  # idempotent
    bus.publish("t")
    assert got == [1]


def test_failing_handler_is_logged_and_does_not_block_others(
    caplog: pytest.LogCaptureFixture,
) -> None:
    bus = EventBus()
    got: list[int] = []

    def bad(**kw: object) -> None:
        raise RuntimeError("boom")

    bus.subscribe("t", bad)
    bus.subscribe("t", lambda **kw: got.append(1))
    with caplog.at_level(logging.ERROR, logger="paper_pile.events"):
        bus.publish("t")
    assert got == [1]
    assert "failed" in caplog.text
