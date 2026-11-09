"""Vault agent: understanding a message (P30.13 / P30.15) and planning it (P30.14).

The model is scripted here; how well a real model understands is the eval's job
(PLAN_vault_agent §8), these tests pin the parsing and the planning rules.
"""

import asyncio
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from paper_pile.core.ai.provider import ProviderError
from paper_pile.core.ai.vault.dates import DayRange
from paper_pile.core.ai.vault.plan import choose, make_plan
from paper_pile.core.ai.vault.results import ResultItem, ResultSet
from paper_pile.core.ai.vault.scope import ScopeResolver
from paper_pile.core.ai.vault.understand import (
    SCHEMA,
    RequestContext,
    VaultRequest,
    messages,
    parse,
    understand_request,
)
from paper_pile.core.index import Index
from paper_pile.core.vault import Vault

TODAY = date(2026, 11, 6)


def step(action: str = "locate", **kw: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "action": action,
        "meta": "",
        "folders": [],
        "tags": [],
        "notes": [],
        "linked_from": [],
        "links_to": [],
        "dates": {},
        "date_kind": "content",
        "from_result": "",
        "topic": "",
        "terms": [],
        "detail": "",
        "depends_on": -1,
    }
    base.update(kw)
    return base


def answer(*steps: dict[str, Any], question: str = "", options: list[str] | None = None) -> dict:
    return {
        "needs_vault": True,
        "steps": list(steps),
        "question": question,
        "options": options or [],
    }


# ---- schema and prompt -----------------------------------------------------------------------


def test_schema_requires_every_step_field() -> None:
    item = SCHEMA["properties"]["steps"]["items"]
    assert set(item["required"]) == set(item["properties"])  # constrained models skip optionals
    assert list(item["properties"])[:3] == ["action", "meta", "folders"]  # target before terms


def test_messages_carry_context() -> None:
    ctx = RequestContext(
        TODAY,
        folders=["Clients", "Journal"],
        tags=["idea"],
        open_note="Plan",
        last_result="Last result:\n1. A [a.md]",
        scoped=["", "Clients/"],
    )
    sys, user = messages("where is X", ctx)
    assert sys.role == "system" and "needs_vault" in sys.content
    text = user.content
    assert "2026-11-06 (Friday)" in text and "Folders: Clients, Journal" in text
    assert "#idea" in text and "Open note (active): Plan" in text and "1. A [a.md]" in text
    assert "the whole vault, folder Clients" in text and text.endswith("Message: where is X")


def test_rules_have_no_phrase_lists() -> None:
    """Rules describe kinds of request (CLAUDE.md): no quoted user phrasings to match."""
    rules = messages("x", RequestContext(TODAY))[0].content
    for phrase in ("social business", "where are my", "summarise all"):
        assert phrase not in rules


# ---- parse -----------------------------------------------------------------------------------


def test_parse_no_vault() -> None:
    assert parse({"needs_vault": False, "steps": [step()]}, TODAY) == VaultRequest(False)
    assert parse(None, TODAY) is None
    assert parse({"steps": []}, TODAY) is None


def test_parse_steps_scope_and_dependencies() -> None:
    req = parse(
        answer(
            step(
                topic="social business",
                terms=["social business", "microfinance", "", "microfinance"],
                folders=["Research/"],
                dates={"last": "month"},
            ),
            step("summarise", depends_on=0, from_result="all"),
            step("summarise", depends_on=5),  # not an earlier step
        ),
        TODAY,
    )
    assert req is not None and req.needs_vault and len(req.steps) == 3
    first, second, third = req.steps
    assert first.terms == ("social business", "microfinance")
    assert first.scope.folders == ("Research",)
    assert first.scope.dates == DayRange(date(2026, 10, 1), date(2026, 10, 31))
    assert second.depends_on == 0 and second.from_result == ""  # the step's notes, not the last
    assert third.depends_on == -1


@pytest.mark.parametrize(
    ("raw", "want"), [("all", "all"), ("ALL", "all"), ("2, 3", "2,3"), ("-1", ""), ("none", "")]
)
def test_parse_from_result(raw: str, want: str) -> None:
    req = parse(answer(step(from_result=raw)), TODAY)
    assert req is not None and req.steps[0].from_result == want


def test_parse_meta_only_on_meta_steps() -> None:
    req = parse(
        answer(step("edit", meta="count"), step("meta", meta="untagged"), step("meta", meta="x")),
        TODAY,
    )
    assert req is not None
    assert [s.meta for s in req.steps] == ["", "untagged", "count"]


def test_parse_drops_bad_steps_and_lone_options() -> None:
    req = parse(answer({"action": "explode"}, step(), question="Which?", options=["one"]), TODAY)
    assert req is not None and len(req.steps) == 1 and req.question == ""
    assert parse(answer({"action": "explode"}), TODAY) is None
    req = parse(answer(step(), question="Which?", options=["a", "b", "a"]), TODAY)
    assert req is not None and req.options == ("a", "b")


def test_understand_request_uses_json_and_survives_errors() -> None:
    class Engine:
        def __init__(self, result: object) -> None:
            self.result = result
            self.calls: list[tuple[Any, Any, int]] = []

        async def ask_json(self, msgs: Any, schema: Any, *, max_answer: int = 0) -> Any:
            self.calls.append((msgs, schema, max_answer))
            if isinstance(self.result, Exception):
                raise self.result
            return self.result

    ok = Engine(answer(step(topic="x")))
    found = asyncio.run(understand_request(ok, "find x", RequestContext(TODAY)))  # type: ignore[arg-type]
    assert found is not None and found.steps[0].topic == "x"
    assert ok.calls[0][1] is SCHEMA
    picky = Engine(answer(step(from_result="all")))
    no_last = asyncio.run(understand_request(picky, "x", RequestContext(TODAY)))  # type: ignore[arg-type]
    assert no_last is not None and no_last.steps[0].from_result == ""  # nothing to take from
    with_last = asyncio.run(
        understand_request(picky, "x", RequestContext(TODAY, last_result="Last result:\n1. A"))  # type: ignore[arg-type]
    )
    assert with_last is not None and with_last.steps[0].from_result == "all"
    down = Engine(ProviderError("down"))
    assert asyncio.run(understand_request(down, "x", RequestContext(TODAY))) is None  # type: ignore[arg-type]


# ---- plan ------------------------------------------------------------------------------------


@pytest.fixture
def resolver(tmp_path: Path) -> ScopeResolver:
    v = Vault(tmp_path)
    v.create_note("Pricing.md", "# Pricing\n")
    v.create_note("Clients/Pricing.md", "# Client pricing\n")
    v.create_note("Clients/Acme.md", "# Acme\n[[Pricing.md]]\n")
    v.create_note("Work/Clients/Old.md", "old\n")
    v.create_note("Ideas/Cafe.md", "cafe\n")
    v.create_note("Ideas/Secret.md", "---\nai: false\n---\nx\n")
    ix = Index(v)
    ix.sync()
    return ScopeResolver(ix, lambda rel: True)


def req(*steps: dict[str, Any], **kw: Any) -> VaultRequest:
    found = parse(answer(*steps, **kw), TODAY)
    assert found is not None
    return found


def test_plan_search_whole_vault(resolver: ScopeResolver) -> None:
    plan = make_plan(req(step(terms=["cafe"])), resolver, None)
    assert plan.ready and plan.steps[0].paths is None and plan.steps[0].search


def test_plan_scope_and_search_inside(resolver: ScopeResolver) -> None:
    plan = make_plan(req(step(folders=["Ideas"], terms=["cafe"])), resolver, None)
    assert plan.steps[0].paths == ["Ideas/Cafe.md"] and plan.steps[0].search


def test_plan_named_note_is_read_not_searched(resolver: ScopeResolver) -> None:
    plan = make_plan(req(step("summarise", notes=["Acme"])), resolver, None)
    assert plan.ready and plan.steps[0].paths == ["Clients/Acme.md"]
    assert not plan.steps[0].search


def test_plan_asks_for_ambiguous_note_then_resolves(resolver: ScopeResolver) -> None:
    plan = make_plan(req(step("summarise", notes=["pricing"])), resolver, None)
    assert plan.choice is not None and plan.choice.kind == "note"
    assert plan.choice.options == ("Clients/Pricing", "Pricing")
    assert "pricing" in plan.choice.question
    picked = choose(plan, "Clients/Pricing.md", resolver)
    assert picked.ready and picked.steps[0].paths == ["Clients/Pricing.md"]


def test_plan_asks_for_ambiguous_folder(resolver: ScopeResolver) -> None:
    plan = make_plan(req(step("summarise", folders=["clients/x"]), step()), resolver, None)
    assert plan.notices == ["Not found: clients/x"] and plan.ready
    plan = make_plan(req(step("summarise", folders=["Clients"])), resolver, None)
    assert plan.ready  # exact "Clients" beats "Work/Clients"
    plan = make_plan(req(step("summarise", folders=["clients "])), resolver, None)
    assert plan.ready and plan.steps[0].paths == ["Clients/Acme.md", "Clients/Pricing.md"]


def test_plan_private_note_is_missing_not_offered(resolver: ScopeResolver) -> None:
    plan = make_plan(req(step("summarise", notes=["Secret"])), resolver, None)
    assert plan.ready and plan.steps[0].paths == [] and plan.notices == ["Not found: Secret"]


def test_plan_model_question_first(resolver: ScopeResolver) -> None:
    plan = make_plan(
        req(step(notes=["pricing"]), question="Short or long?", options=["Short", "Long"]),
        resolver,
        None,
    )
    assert plan.choice is not None and plan.choice.kind == "open"
    assert choose(plan, "Short", resolver).ready


def test_plan_from_last_result_and_depends(resolver: ScopeResolver) -> None:
    last = ResultSet(
        "x",
        [
            ResultItem("Ideas/Cafe.md", "Cafe"),
            ResultItem("Clients/Acme.md", "Acme"),
            ResultItem("Ideas/Secret.md", "gone private"),
        ],
    )
    plan = make_plan(req(step("summarise", from_result="2,3")), resolver, last)
    assert plan.steps[0].paths == ["Clients/Acme.md"] and not plan.steps[0].search
    plan = make_plan(req(step(terms=["x"]), step("summarise", depends_on=0)), resolver, last)
    assert plan.steps[1].after == 0 and not plan.steps[1].search
