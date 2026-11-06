"""Vault agent: summaries and extracted tables (PLAN_vault_agent P30.22–P30.23)."""

import asyncio
from collections.abc import AsyncIterator
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from paper_pile.core.ai.access import says_private
from paper_pile.core.ai.vault import cards as cards_mod
from paper_pile.core.ai.vault import extract as extract_mod
from paper_pile.core.ai.vault.cards import CardMaker, CardStore
from paper_pile.core.ai.vault.extract import extract, markdown_table, parse_columns, parse_rows
from paper_pile.core.ai.vault.reply import Table
from paper_pile.core.ai.vault.results import ResultItem, ResultSet
from paper_pile.core.ai.vault.scope import ScopeResolver
from paper_pile.core.ai.vault.summarise import summarise_many, summarise_note
from paper_pile.core.ai.vault.tools import VaultTools
from paper_pile.core.index import Index
from paper_pile.core.vault import Vault


class Model:
    """Streams a reply naming the labels it saw; answers JSON by schema."""

    def __init__(self) -> None:
        self.streams: list[str] = []
        self.json_calls = 0

    async def stream(self, msgs: Any, *, think: bool | None = None) -> AsyncIterator[str]:
        body = msgs[1].content
        self.streams.append(body)
        if body.startswith("Partial summary"):
            yield "Merged: all points [1] [13]."
            return
        labels = [w for w in body.split() if w.startswith("[") and w.endswith("]")]
        yield "Summary " + " ".join(dict.fromkeys(labels)) + "."

    async def ask_json(self, msgs: Any, schema: Any, *, max_answer: int = 0) -> Any:
        self.json_calls += 1
        if schema is cards_mod.SCHEMA:
            title = msgs[1].content.splitlines()[0].removeprefix("Note: ")
            return {"summary": f"About {title}.", "terms": [title]}
        if schema is extract_mod.COLUMNS_SCHEMA:
            return {"columns": ["Client", "Budget"]}
        text = msgs[1].content
        if "budget" in text.split("<<<", 1)[1].lower():  # the note, not the request
            name = text.split("Note: ", 1)[1].splitlines()[0]
            return {"rows": [{"Client": name, "Budget": "10k"}]}
        return {"rows": []}


@pytest.fixture
def parts(tmp_path: Path) -> tuple[VaultTools, CardMaker, Model]:
    v = Vault(tmp_path)
    for i in range(15):
        v.create_note(
            f"Clients/c{i:02}.md", f"# c{i:02}\nbudget 10k\n" if i % 2 else f"# c{i:02}\nnothing\n"
        )
    v.create_note("Private/Secret.md", "---\nai: false\n---\n# Secret\nbudget\n")
    ix = Index(v)
    ix.sync()

    def read(rel: str) -> str | None:
        text = v.read_text(rel)
        return None if says_private(text) else text

    tools = VaultTools(ix, ScopeResolver(ix, lambda r: True), read, lambda: date(2026, 11, 6))
    model = Model()
    maker = CardMaker(model, CardStore(v.root), read, ix.hashes, ix.title)  # type: ignore[arg-type]
    return tools, maker, model


def results(paths: list[str]) -> ResultSet:
    return ResultSet("q", [ResultItem(p, p.rsplit("/", 1)[-1][:-3]) for p in paths])


def test_summarise_one_note(parts: tuple[VaultTools, CardMaker, Model]) -> None:
    tools, _, model = parts
    reply = asyncio.run(summarise_note(model, tools, "Clients/c01.md", "summarise it", results([])))  # type: ignore[arg-type]
    assert reply.text == "Summary [1]." and reply.sources[0].path == "Clients/c01.md"
    assert reply.checked is not None and reply.checked.used == [1]
    denied = asyncio.run(summarise_note(model, tools, "Private/Secret.md", "x", results([])))  # type: ignore[arg-type]
    assert denied.sources == [] and "No note" in denied.text


def test_summarise_many_one_call(parts: tuple[VaultTools, CardMaker, Model]) -> None:
    tools, maker, model = parts
    paths = ["Clients/c00.md", "Clients/c01.md", "Private/Secret.md"]
    reply = asyncio.run(summarise_many(model, maker, "summarise", results(paths)))  # type: ignore[arg-type]
    assert [s.path for s in reply.sources] == ["Clients/c00.md", "Clients/c01.md"]
    assert reply.sources[0].text == "About c00." and reply.sources[0].anchor == ""
    assert reply.text == "Summary [1] [2]." and len(model.streams) == 1
    assert reply.notices == ["Left out (could not be read): Secret"]
    calls = model.json_calls
    asyncio.run(summarise_many(model, maker, "again", results(paths)))  # type: ignore[arg-type]
    assert model.json_calls == calls  # cards reused: no new card calls


def test_summarise_many_merges_in_rounds(parts: tuple[VaultTools, CardMaker, Model]) -> None:
    tools, maker, model = parts
    paths = [f"Clients/c{i:02}.md" for i in range(15)]
    seen: list[tuple[str, int, int]] = []
    reply = asyncio.run(
        summarise_many(
            model,
            maker,
            "summarise",
            results(paths),
            group=6,
            on_progress=lambda s, d, t: seen.append((s, d, t)),
        )  # type: ignore[arg-type]
    )
    assert len(model.streams) == 4  # 3 groups + 1 merge
    assert "[13]" in model.streams[2] and model.streams[3].startswith("Partial summary 1:")
    assert reply.text == "Merged: all points [1] [13]."  # global labels survive the merge
    assert reply.checked is not None and reply.checked.used == [1, 13]
    assert ("merge", 4, 4) in seen and seen[0][0] == "cards"


def test_extract_table(parts: tuple[VaultTools, CardMaker, Model]) -> None:
    tools, _, model = parts
    paths = ["Clients/c00.md", "Clients/c01.md", "Clients/c03.md", "Private/Secret.md"]
    reply = asyncio.run(extract(model, tools, "every client and budget", results(paths)))  # type: ignore[arg-type]
    assert reply.table is not None and reply.table.columns == ["Client", "Budget"]
    assert reply.table.rows == [["c01", "10k"], ["c03", "10k"]]
    assert reply.table.sources == [1, 2] and [s.path for s in reply.sources] == [
        "Clients/c01.md",
        "Clients/c03.md",
    ]
    assert reply.text.splitlines()[0] == "| Client | Budget | Source |"
    assert reply.text.splitlines()[2] == "| c01 | 10k | [1] |"


def test_extract_parsers_and_markdown() -> None:
    assert parse_columns({"columns": [" A ", "A", "", 3, "B"]}) == ["A", "B"]
    assert parse_columns(None) == []
    rows = parse_rows({"rows": [{"A": "x", "B": None}, {"A": "", "B": ""}, "bad"]}, ["A", "B"])
    assert rows == [["x", ""]]
    table = Table(["A"], [["a|b"], [""]], [1, 2])
    assert markdown_table(table).splitlines()[2:] == ["| a\\|b | [1] |", "| — | [2] |"]
