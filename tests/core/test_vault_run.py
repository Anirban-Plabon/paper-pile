"""Vault agent: guessed scopes, hints and the fast-path runner (PLAN_vault_agent P30.20–P30.24)
with a scripted model that answers every call by its schema."""

import asyncio
from collections.abc import AsyncIterator
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from paper_pile.core.ai.access import says_private
from paper_pile.core.ai.vault import cards as cards_mod
from paper_pile.core.ai.vault import expand as expand_mod
from paper_pile.core.ai.vault import judge as judge_mod
from paper_pile.core.ai.vault.candidates import Gatherer
from paper_pile.core.ai.vault.cards import CardMaker, CardStore
from paper_pile.core.ai.vault.find import Budgets
from paper_pile.core.ai.vault.hints import hints, near_names
from paper_pile.core.ai.vault.meta import VaultMeta
from paper_pile.core.ai.vault.plan import PlannedStep, make_plan, mentioned, unguessed
from paper_pile.core.ai.vault.results import ResultItem, ResultSet
from paper_pile.core.ai.vault.run import VaultAgent, meta_text, run_plan
from paper_pile.core.ai.vault.scope import Scope, ScopeResolver
from paper_pile.core.ai.vault.tools import VaultTools
from paper_pile.core.ai.vault.understand import Step, VaultRequest
from paper_pile.core.index import Index
from paper_pile.core.vault import Vault


class Model:
    """Judges a card "yes" when it mentions ``topic``; streams a reply citing [1]."""

    def __init__(self, topic: str = "microcredit") -> None:
        self.topic = topic
        self.streamed: list[str] = []

    async def stream(self, msgs: Any, *, think: bool | None = None) -> AsyncIterator[str]:
        self.streamed.append(msgs[1].content)
        yield "Answer from the notes [1]."

    async def ask_json(self, msgs: Any, schema: Any, *, max_answer: int = 0) -> Any:
        body = msgs[1].content
        if schema is judge_mod.SCHEMA:
            cards = body.split("\n\n")[2:]
            return {
                "verdicts": [
                    {"n": n, "relevance": "yes" if self.topic in c.lower() else "no", "reason": "r"}
                    for n, c in enumerate(cards, 1)
                ]
            }
        if schema is expand_mod.SCHEMA:
            return {"terms": []}
        if schema is cards_mod.SCHEMA:
            return {"summary": "A card.", "terms": []}
        raise AssertionError(f"unexpected schema {schema}")


@pytest.fixture
def agent(tmp_path: Path) -> VaultAgent:
    v = Vault(tmp_path)
    v.create_note("Research/Yunus.md", "# Yunus\nmicrocredit for the poor\n")
    v.create_note("Research/Bank.md", "# Bank\nmicrocredit groups\n")
    v.create_note("Marketing/Plan.md", "#marketing\n# Plan\nsocial posts\n")
    v.create_note("Journal/2026-11-02.md", "#idea microcredit pilot\n")
    v.create_note("Ideas/Other.md", "nothing\n")
    ix = Index(v)
    ix.sync()

    def read(rel: str) -> str | None:
        text = v.read_text(rel)
        return None if says_private(text) else text

    resolver = ScopeResolver(ix, lambda r: True)
    tools = VaultTools(ix, resolver, read, lambda: date(2026, 11, 6))
    model = Model()
    maker = CardMaker(model, CardStore(v.root), read, ix.hashes, ix.title)  # type: ignore[arg-type]
    return VaultAgent(model, tools, Gatherer(tools), maker, VaultMeta(ix, resolver))  # type: ignore[arg-type]


def request(*steps: Step) -> VaultRequest:
    return VaultRequest(True, steps)


# ---- guessed scopes ----------------------------------------------------------------------------


def test_mentioned() -> None:
    assert mentioned("Clients", "list every client and their budget")
    assert mentioned("Work/Marketing", "in marketing, which notes")
    assert not mentioned("Marketing", "where are my social business notes")
    assert not mentioned("Journal", "what did I write in my daily notes")


def test_unguessed_drops_guesses_only_for_topic_searches() -> None:
    guess = Step(
        "summarise",
        "social business",
        ("social business",),
        Scope(folders=("Marketing",), tags=("marketing",)),
    )
    dropped = unguessed(guess, "summarise my social business notes")
    assert dropped.scope.folders == () and dropped.scope.tags == ()
    said = unguessed(guess, "summarise the social business notes in Marketing")
    assert said.scope.folders == ("Marketing",) and said.scope.tags == ("marketing",)
    forced = unguessed(guess, "summarise my social business notes", forced=["Marketing"])
    assert forced.scope.folders == ("Marketing",)
    kind = Step("summarise", "daily notes", (), Scope(folders=("Journal",)))
    assert unguessed(kind, "what did I write in my daily notes").scope.folders == ("Journal",)


# ---- hints -------------------------------------------------------------------------------------


def test_near_names() -> None:
    assert near_names(["marketng", "x"], ["marketing", "client"]) == ["marketing"]
    assert near_names(["client"], ["Clients", "Ideas"]) == ["Clients"]


def test_hints(agent: VaultAgent) -> None:
    step = Step("locate", "microcredit", ("microcredit",))
    found = ResultSet(
        "q",
        [
            ResultItem("Research/Yunus.md", "Yunus"),
            ResultItem("Research/Bank.md", "Bank"),
            ResultItem("Journal/2026-11-02.md", "J"),
            ResultItem("Ideas/Other.md", "O"),
            ResultItem("Marketing/Plan.md", "P", relevance="maybe"),
        ],
    )
    labels = [h.label for h in hints(PlannedStep(step), found, agent.tools.resolver)]
    assert labels == [
        "1 more might be related",
        "Only Research (2)",
        "Summarise all",
        "Make a table",
        "Open all",
    ]
    empty = hints(
        PlannedStep(Step("locate", "marketng", ("marketng",)), paths=["Ideas/Other.md"]),
        ResultSet("q"),
        agent.tools.resolver,
        ["marketing"],
    )
    assert [(h.kind, h.value) for h in empty] == [
        ("scope", ""),
        ("near", "#marketing"),
        ("near", "Marketing"),
    ]


# ---- runner ------------------------------------------------------------------------------------


def test_run_locate_then_summarise_its_notes(agent: VaultAgent) -> None:
    req = request(
        Step("locate", "microcredit", ("microcredit",), detail="where are my microcredit notes"),
        Step("summarise", "microcredit", depends_on=0, detail="summarise them"),
    )
    plan = make_plan(
        req, agent.tools.resolver, None, "where are my microcredit notes, summarise them"
    )
    stages: list[str] = []
    out = asyncio.run(
        run_plan(agent, plan, "m", on_progress=lambda i, s, d, t: stages.append(f"{i}:{s}"))
    )
    assert out.choice is None and len(out.replies) == 2
    first, second = out.replies
    assert first.text.startswith("Found 3 notes.")
    assert set(first.results.paths) == {
        "Research/Yunus.md",
        "Research/Bank.md",
        "Journal/2026-11-02.md",
    }
    assert second.text == "Answer from the notes [1]." and len(second.sources) == 3  # its notes
    assert out.last is not None and set(out.last.paths) == set(first.results.paths)
    assert "0:judge" in stages and "1:cards" in stages


def test_run_meta_answer_and_not_yet(agent: VaultAgent) -> None:
    req = request(
        Step("meta", meta="count"),
        Step("answer", "microcredit", ("microcredit",), detail="who gets microcredit?"),
        Step("edit", "x", ("x",)),
    )
    plan = make_plan(req, agent.tools.resolver, None, "m")
    out = asyncio.run(run_plan(agent, plan, "m"))
    assert out.replies[0].text.startswith("5 notes")
    assert out.replies[1].sources and out.replies[1].checked is not None
    assert out.replies[2].text == "No notes found."  # an edit with nothing to change


def test_run_empty_and_big_job(agent: VaultAgent) -> None:
    plan = make_plan(
        request(Step("summarise", "quantum", ("quantum",))), agent.tools.resolver, None, "m"
    )
    out = asyncio.run(run_plan(agent, plan, "m"))
    assert out.replies[0].text == "No notes found." and out.last is None
    agent.budgets = Budgets(candidates=1)
    plan = make_plan(
        request(Step("locate", "microcredit", ("microcredit",))), agent.tools.resolver, None, "m"
    )
    stopped = asyncio.run(run_plan(agent, plan, "m"))
    assert stopped.choice is not None and stopped.choice.kind == "budget" and stopped.replies == []
    went_on = asyncio.run(run_plan(agent, plan, "m", use_best=True))
    assert went_on.choice is None and len(went_on.replies) == 1


def test_meta_text() -> None:
    from paper_pile.core.ai.vault.meta import MetaResult

    assert meta_text(MetaResult("count", 3, ["notes", "words"], [[3, 40]])) == "3 notes (40 words)."
    many = meta_text(MetaResult("recent", 5, ["path"], [["a.md"], ["b.md"]]))
    assert many.startswith("5 in all, the first 2:") and "| a.md |" in many
    assert meta_text(MetaResult("untagged", 0, ["path"], [])) == "None (untagged)."
