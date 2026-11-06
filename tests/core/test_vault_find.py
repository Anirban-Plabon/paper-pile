"""Vault agent: the second search round and the find stage (PLAN_vault_agent P30.16–P30.19),
with a scripted model that answers by schema."""

import asyncio
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from paper_pile.core.ai.access import says_private
from paper_pile.core.ai.vault import expand, judge
from paper_pile.core.ai.vault.candidates import Candidate, Gatherer
from paper_pile.core.ai.vault.expand import more_terms
from paper_pile.core.ai.vault.find import Budgets, big_job, find_notes
from paper_pile.core.ai.vault.judge import Judged
from paper_pile.core.ai.vault.plan import PlannedStep
from paper_pile.core.ai.vault.scope import ScopeResolver
from paper_pile.core.ai.vault.tools import VaultTools
from paper_pile.core.ai.vault.understand import Step
from paper_pile.core.index import Index
from paper_pile.core.vault import Vault


class Engine:
    """Judges every card "yes" when its text holds one of ``on_topic``; gives ``extra`` terms."""

    def __init__(self, on_topic: tuple[str, ...], extra: list[str]) -> None:
        self.on_topic = on_topic
        self.extra = extra
        self.calls: list[str] = []

    async def ask_json(self, msgs: Any, schema: Any, *, max_answer: int = 0) -> Any:
        if schema is expand.SCHEMA:
            self.calls.append("expand")
            return {"terms": self.extra}
        assert schema is judge.SCHEMA
        self.calls.append("judge")
        cards = msgs[1].content.split("\n\n")[2:]
        verdicts = []
        for n, text in enumerate(cards, 1):
            hit = any(w in text.lower() for w in self.on_topic)
            verdicts.append({"n": n, "relevance": "yes" if hit else "no", "reason": "r"})
        return {"verdicts": verdicts}


@pytest.fixture
def gatherer(tmp_path: Path) -> Gatherer:
    v = Vault(tmp_path)
    v.create_note("Research/Yunus.md", "# Yunus\nsocial business and microcredit\n")
    v.create_note("Research/Enterprise.md", "# Models\ncompanies with a social mission\n")
    v.create_note("Personal/Weekend.md", "a social evening after a business dinner\n")
    v.create_note("Clients/Acme.md", "# Acme\nbudget\n")
    ix = Index(v)
    ix.sync()

    def read(rel: str) -> str | None:
        text = v.read_text(rel)
        return None if says_private(text) else text

    tools = VaultTools(ix, ScopeResolver(ix, lambda r: True), read, lambda: date(2026, 11, 6))
    return Gatherer(tools)


def facts(path: str) -> tuple[list[str], list[str]]:
    return [], []


def planned(
    terms: tuple[str, ...], paths: list[str] | None = None, search: bool = True
) -> PlannedStep:
    step = Step("locate", topic="social business", terms=terms)
    return PlannedStep(step, paths=paths, search=search)


def test_more_terms_needs_a_sure_note() -> None:
    eng = Engine((), ["microcredit", "Social business", "  ", "grameen"])
    cand = Candidate("a.md", "A", snippet="microcredit")
    assert asyncio.run(more_terms(eng, "t", [Judged(cand, "maybe", "")], ["x"])) == []  # type: ignore[arg-type]
    got = asyncio.run(more_terms(eng, "t", [Judged(cand, "yes", "")], ["social business"]))  # type: ignore[arg-type]
    assert got == ["microcredit", "grameen"]  # already searched and empty terms left out


def test_find_two_rounds(gatherer: Gatherer) -> None:
    eng = Engine(("microcredit", "mission"), ["social mission"])
    seen: list[str] = []
    found = asyncio.run(
        find_notes(
            eng,  # type: ignore[arg-type]
            gatherer,
            "where are my social business notes",
            planned(("social business",)),
            facts,
            on_progress=lambda s, d, t: seen.append(s),
        )
    )
    assert found.rounds == 2 and "social mission" in found.terms
    assert found.results.paths == ["Research/Yunus.md", "Research/Enterprise.md"]
    assert "Personal/Weekend.md" not in found.results.paths  # judged no
    assert eng.calls == ["judge", "expand", "judge"]
    assert "search" in seen and "judge" in seen


def test_find_no_second_round_when_off_or_nothing_sure(gatherer: Gatherer) -> None:
    eng = Engine(("nothing-matches",), ["x"])
    found = asyncio.run(
        find_notes(eng, gatherer, "q", planned(("social",)), facts)  # type: ignore[arg-type]
    )
    assert found.rounds == 1 and found.results.paths == [] and "expand" not in eng.calls
    eng = Engine(("microcredit",), ["mission"])
    found = asyncio.run(
        find_notes(
            eng,  # type: ignore[arg-type]
            gatherer,
            "q",
            planned(("social business",)),
            facts,
            budgets=Budgets(second_round=False),
        )
    )
    assert found.rounds == 1 and found.results.paths == ["Research/Yunus.md"]


def test_find_fixed_notes_are_not_judged(gatherer: Gatherer) -> None:
    eng = Engine((), [])
    found = asyncio.run(
        find_notes(
            eng,  # type: ignore[arg-type]
            gatherer,
            "q",
            planned((), ["Clients/Acme.md"], search=False),
            facts,
        )
    )
    assert found.results.paths == ["Clients/Acme.md"] and eng.calls == []
    every = asyncio.run(find_notes(eng, gatherer, "q", planned((), None, False), facts))  # type: ignore[arg-type]
    assert len(every.results) == 4


def test_find_cap_reported(gatherer: Gatherer) -> None:
    eng = Engine(("social",), [])
    found = asyncio.run(
        find_notes(
            eng,  # type: ignore[arg-type]
            gatherer,
            "q",
            planned(("social",)),
            facts,
            budgets=Budgets(candidates=1, second_round=False),
        )
    )
    assert found.capped and found.total > 1 and len(found.judged) == 1


def test_find_inside_scope(gatherer: Gatherer) -> None:
    eng = Engine(("social",), [])
    found = asyncio.run(
        find_notes(
            eng,  # type: ignore[arg-type]
            gatherer,
            "q",
            planned(("social",), ["Personal/Weekend.md"]),
            facts,
            budgets=Budgets(second_round=False),
        )
    )
    assert found.results.paths == ["Personal/Weekend.md"]


def test_big_job_question(gatherer: Gatherer) -> None:
    eng = Engine(("social",), [])
    small = Budgets(candidates=1, second_round=False)
    found = asyncio.run(
        find_notes(eng, gatherer, "q", planned(("social",)), facts, budgets=small)  # type: ignore[arg-type]
    )
    ask = big_job(found, small)
    assert ask is not None and ask.kind == "budget" and ask.values == ("best", "narrow")
    assert f"{found.total} notes match" in ask.question and "best 1" in ask.options[0]
    within = asyncio.run(
        find_notes(
            eng, gatherer, "q", planned(("social",)), facts, budgets=Budgets(second_round=False)
        )  # type: ignore[arg-type]
    )
    assert big_job(within) is None
