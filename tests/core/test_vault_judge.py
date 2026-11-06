"""Vault agent: the relevance judge (PLAN_vault_agent P30.17), with a scripted model."""

import asyncio
from typing import Any

from paper_pile.core.ai.provider import ProviderError
from paper_pile.core.ai.vault.candidates import Candidate
from paper_pile.core.ai.vault.judge import SCHEMA, card, judge, messages, parse, to_results


class Engine:
    def __init__(self, *replies: object) -> None:
        self.replies = list(replies)
        self.prompts: list[str] = []

    async def ask_json(self, msgs: Any, schema: Any, *, max_answer: int = 0) -> Any:
        assert schema is SCHEMA
        self.prompts.append(msgs[1].content)
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply


def cand(path: str, snippet: str = "text") -> Candidate:
    return Candidate(path, path.rsplit("/", 1)[-1][:-3], 1.0, {"search"}, "Intro", snippet)


def facts(path: str) -> tuple[list[str], list[str]]:
    return (["idea"], ["Intro", "Plan"]) if path.startswith("A") else ([], [])


def v(n: int, rel: str, reason: str = "r") -> dict[str, Any]:
    return {"n": n, "relevance": rel, "reason": reason}


def test_card_and_messages() -> None:
    text = card(3, cand("A/Yunus.md", "Micro   finance\nand more"), ["idea"], ["Intro", "Plan"])
    assert text.splitlines() == [
        "[3] Yunus — folder: A",
        "tags: #idea",
        "headings: Intro | Plan",
        "text (Intro): Micro finance and more",
    ]
    assert card(1, cand("Top.md", ""), [], []).splitlines() == ["[1] Top — folder: (top)"]
    with_card = cand("Top.md", "")
    with_card.summary = "A social  enterprise."
    assert card(1, with_card, [], []).splitlines()[1] == "about: A social enterprise."
    sys, user = messages("social business", [text])
    assert "yes" in sys.content and user.content.startswith("Request: social business")


def test_parse() -> None:
    got = parse({"verdicts": [v(1, "yes"), v(2, "nope"), v(9, "no"), v(1, "no"), "x"]}, 3)
    assert got == {1: ("yes", "r")}
    assert parse(None, 3) == {} and parse({"verdicts": "x"}, 3) == {}


def test_judge_batches_and_keeps_unjudged_as_maybe() -> None:
    cands = [cand(f"A/n{i}.md") for i in range(5)]
    engine = Engine(
        {"verdicts": [v(1, "yes", "about it"), v(2, "no")]},  # 3 left out → maybe
        {"verdicts": [v(1, "no"), v(2, "maybe", "in passing")]},
        ProviderError("down"),
    )
    seen: list[tuple[int, int]] = []
    out = asyncio.run(
        judge(engine, "q", cands, facts, batch=2, on_batch=lambda d, t: seen.append((d, t)))  # type: ignore[arg-type]
    )
    assert [(j.candidate.path, j.relevance) for j in out] == [
        ("A/n0.md", "yes"),
        ("A/n1.md", "no"),
        ("A/n2.md", "no"),
        ("A/n3.md", "maybe"),
        ("A/n4.md", "maybe"),  # its batch failed: kept, marked unsure
    ]
    assert seen == [(2, 5), (4, 5), (5, 5)]
    assert "[2] n1" in engine.prompts[0] and "[1] n2" in engine.prompts[1]


def test_to_results_orders_yes_then_maybe() -> None:
    cands = [cand("a.md"), cand("b.md"), cand("c.md")]
    engine = Engine({"verdicts": [v(1, "maybe"), v(2, "no"), v(3, "yes", "core")]})
    out = asyncio.run(judge(engine, "q", cands, facts))  # type: ignore[arg-type]
    rs = to_results("q", out)
    assert [(i.path, i.relevance, i.reason) for i in rs.items] == [
        ("c.md", "yes", "core"),
        ("a.md", "maybe", "r"),
    ]
    assert rs.items[0].heading == "Intro"
