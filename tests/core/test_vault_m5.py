"""Vault agent M5 pieces: the memory file (P30.28), the plan card data (P30.27) and routing
compare / open-ended steps to the loop (P30.26)."""

import asyncio
from collections.abc import AsyncIterator
from datetime import date
from pathlib import Path
from typing import Any

from paper_pile.core.ai.access import says_private
from paper_pile.core.ai.vault import loop as loop_mod
from paper_pile.core.ai.vault.candidates import Gatherer
from paper_pile.core.ai.vault.cards import CardMaker, CardStore
from paper_pile.core.ai.vault.dates import DayRange
from paper_pile.core.ai.vault.memory import MAX_CHARS, load_memory, memory_path
from paper_pile.core.ai.vault.meta import VaultMeta
from paper_pile.core.ai.vault.plan import (
    Plan,
    PlannedStep,
    card_lines,
    drop_step,
    needs_card,
    without_repeats,
)
from paper_pile.core.ai.vault.run import VaultAgent, run_plan
from paper_pile.core.ai.vault.scope import Scope, ScopeResolver
from paper_pile.core.ai.vault.tools import VaultTools
from paper_pile.core.ai.vault.understand import RequestContext, Step, messages
from paper_pile.core.index import Index
from paper_pile.core.vault import Vault

# ---- repeated answers --------------------------------------------------------------------------


def test_without_repeats() -> None:
    steps = [
        Step("compare", "pricing"),
        Step("answer", depends_on=0),  # the same answer again: dropped
        Step("summarise", depends_on=1),  # moves to what the dropped step depended on
        Step("answer", depends_on=2),  # an answer from a summary's notes: kept
    ]
    kept = without_repeats(steps)
    assert [(s.action, s.depends_on) for s in kept] == [
        ("compare", -1),
        ("summarise", 0),
        ("answer", 1),
    ]
    locate_then_answer = [Step("locate", "x"), Step("answer", depends_on=0)]
    assert len(without_repeats(locate_then_answer)) == 2


# ---- memory file -------------------------------------------------------------------------------


def test_memory_file(tmp_path: Path) -> None:
    assert load_memory(tmp_path) == ""
    path = memory_path(tmp_path)
    path.parent.mkdir(parents=True)
    path.write_text("  Daily notes live in Journal/.\n\n", encoding="utf-8")
    assert load_memory(tmp_path) == "Daily notes live in Journal/."
    path.write_text("x" * (MAX_CHARS + 50), encoding="utf-8")
    long = load_memory(tmp_path)
    assert long.endswith("\n…") and len(long) <= MAX_CHARS + 2
    path.write_bytes(b"\xff\xfe\x00bad")
    assert load_memory(tmp_path) == ""


def test_memory_goes_with_the_request() -> None:
    ctx = RequestContext(date(2026, 11, 6), memory="One note per client.")
    assert (
        "About this vault (written by the user):\nOne note per client."
        in messages("x", ctx)[1].content
    )


# ---- plan card ---------------------------------------------------------------------------------


def plan(*steps: PlannedStep) -> Plan:
    return Plan(list(steps))


def test_needs_card() -> None:
    read = PlannedStep(Step("locate", "x", ("x",)), search=True)
    assert not needs_card(plan(read))
    assert needs_card(plan(read, read))
    assert needs_card(plan(PlannedStep(Step("edit", "x"))))


def test_card_lines() -> None:
    october = DayRange(date(2026, 10, 1), date(2026, 10, 31))
    lines = card_lines(
        plan(
            PlannedStep(
                Step("extract", "client budgets", ("budget",), Scope(folders=("Clients",))),
                ["a.md"],
                True,
            ),
            PlannedStep(Step("edit", detail="add a Budget section"), after=0),
            PlannedStep(
                Step("summarise", scope=Scope(tags=("idea",), dates=october)), ["b.md", "c.md"]
            ),
            PlannedStep(Step("meta", meta="count")),
        )
    )
    assert lines == [
        "1. Make a table from notes about client budgets in Clients",
        "2. Change the notes of step 1: add a Budget section",
        "3. Summarise tagged #idea dated 2026-10-01 to 2026-10-31 (2 notes)",
        "4. Count / list the whole vault",
    ]


def test_drop_step_renumbers_dependencies() -> None:
    a = PlannedStep(Step("locate", "a"))
    b = PlannedStep(Step("summarise"), after=0)
    c = PlannedStep(Step("edit"), after=1)
    dropped = drop_step(plan(a, b, c), 0)
    assert [p.step.action for p in dropped.steps] == ["summarise", "edit"]
    assert [p.after for p in dropped.steps] == [-1, 0]
    assert drop_step(plan(a), 5).steps == [a]


# ---- routing -----------------------------------------------------------------------------------


class Model:
    def __init__(self) -> None:
        self.actions = [
            {"tool": "read", "note": "Plans/2025.md", "section": ""},
            {"tool": "final"},
        ]

    async def ask_json(self, msgs: Any, schema: Any, *, max_answer: int = 0) -> Any:
        assert schema is loop_mod.SCHEMA
        return self.actions.pop(0)

    async def stream(self, msgs: Any, *, think: bool | None = None) -> AsyncIterator[str]:
        yield "It was 10 [1]."


def test_compare_goes_to_the_loop(tmp_path: Path) -> None:
    v = Vault(tmp_path)
    v.create_note("Plans/2025.md", "# 2025\nprice 10\n")
    ix = Index(v)
    ix.sync()

    def read(rel: str) -> str | None:
        text = v.read_text(rel)
        return None if says_private(text) else text

    resolver = ScopeResolver(ix, lambda r: True)
    tools = VaultTools(ix, resolver, read, lambda: date(2026, 11, 6))
    model = Model()
    agent = VaultAgent(
        model,  # type: ignore[arg-type]
        tools,
        Gatherer(tools),
        CardMaker(model, CardStore(v.root), read, ix.hashes, ix.title),  # type: ignore[arg-type]
        VaultMeta(ix, resolver),
        memory="Plans are yearly.",
    )
    stages: list[str] = []
    out = asyncio.run(
        run_plan(
            agent,
            plan(PlannedStep(Step("compare", "price", detail="how did the price change"))),
            "m",
            on_progress=lambda i, s, d, t: stages.append(s),
        )
    )
    assert (
        out.replies[0].text == "It was 10 [1]."
        and out.replies[0].sources[0].path == "Plans/2025.md"
    )
    assert stages == ["loop: read(note='Plans/2025.md')"]
    assert out.last is not None and out.last.paths == ["Plans/2025.md"]
    stopped = asyncio.run(
        run_plan(agent, plan(PlannedStep(Step("compare"))), "m", stop=lambda: True)
    )
    assert stopped.stopped and stopped.replies == []
