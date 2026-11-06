"""Vault agent: note cards cache (PLAN_vault_agent P30.18), with a scripted model."""

import asyncio
import sqlite3
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from paper_pile.core.ai.access import says_private
from paper_pile.core.ai.provider import ProviderError
from paper_pile.core.ai.vault.candidates import Gatherer
from paper_pile.core.ai.vault.cards import (
    CARDS_DB,
    SCHEMA,
    Card,
    CardMaker,
    CardStore,
    card_search,
    card_summaries,
    parse,
)
from paper_pile.core.ai.vault.scope import ScopeResolver
from paper_pile.core.ai.vault.tools import VaultTools
from paper_pile.core.index import Index
from paper_pile.core.vault import Vault


class Engine:
    def __init__(self, fail: tuple[str, ...] = ()) -> None:
        self.fail = fail
        self.made: list[str] = []

    async def ask_json(self, msgs: Any, schema: Any, *, max_answer: int = 0) -> Any:
        assert schema is SCHEMA
        title = msgs[1].content.splitlines()[0].removeprefix("Note: ")
        if title in self.fail:
            raise ProviderError("down")
        self.made.append(title)
        if "solar" in title.lower():
            return {
                "summary": "A social enterprise selling lamps at cost.",
                "terms": ["social enterprise"],
            }
        return {"summary": f"About {title}.", "terms": [title, "", title]}


@pytest.fixture
def vault(tmp_path: Path) -> Vault:
    v = Vault(tmp_path)
    v.create_note(
        "Ideas/Village solar.md", "# Village solar\nLamps sold at cost; surplus reinvested.\n"
    )
    v.create_note("Clients/Acme.md", "# Acme\nbudget\n")
    v.create_note("Personal/Secret.md", "---\nai: false\n---\n# Secret\nx\n")
    return v


@pytest.fixture
def parts(vault: Vault) -> tuple[Index, CardStore, CardMaker, Engine]:
    ix = Index(vault)
    ix.sync()
    store = CardStore(vault.root)
    engine = Engine()

    def read(rel: str) -> str | None:
        text = vault.read_text(rel)
        return None if says_private(text) else text

    maker = CardMaker(engine, store, read, ix.hashes, ix.title)  # type: ignore[arg-type]
    return ix, store, maker, engine


def test_parse() -> None:
    assert parse({"summary": "  A  note. ", "terms": ["x", " x ", 3, "y"]}) == (
        "A note.",
        ("x", "y"),
    )
    assert parse({"summary": "", "terms": []}) is None
    assert parse(None) is None


def test_store_roundtrip_and_hash(vault: Vault) -> None:
    store = CardStore(vault.root)
    store.put(Card("a.md", "h1", "About a.", ("alpha", "beta")))
    assert store.get("a.md", "h1") == Card("a.md", "h1", "About a.", ("alpha", "beta"))
    assert store.get("a.md", "h2") is None  # stale: made from another text
    store.put(Card("a.md", "h2", "New.", ()))
    assert store.get("a.md", "h1") is None and store.get("a.md", "h2") is not None
    store.rename("a.md", "b.md")
    assert store.get("b.md", "h2") is not None
    assert store.prune({"zz.md"}) == 1 and store.get("b.md", "h2") is None


def test_store_rebuilt_when_unreadable_or_old(vault: Vault) -> None:
    store = CardStore(vault.root)
    store.put(Card("a.md", "h", "s", ()))
    store.close()
    db = sqlite3.connect(vault.root / ".paper-pile" / CARDS_DB)
    db.execute("UPDATE meta SET value='0' WHERE key='version'")
    db.commit()
    db.close()
    assert CardStore(vault.root).get("a.md", "h") is None  # a new card prompt: cards made again


def test_maker_lazy_cached_private_and_failures(
    parts: tuple[Index, CardStore, CardMaker, Engine],
) -> None:
    ix, store, maker, engine = parts
    paths = ["Ideas/Village solar.md", "Clients/Acme.md", "Personal/Secret.md"]
    seen: list[tuple[int, int]] = []
    cards = asyncio.run(maker.ensure(paths, lambda d, t: seen.append((d, t))))
    assert set(cards) == {"Ideas/Village solar.md", "Clients/Acme.md"}  # no card for private
    assert cards["Clients/Acme.md"].terms == ("Acme",)
    assert seen[-1] == (3, 3)
    made = len(engine.made)
    again = asyncio.run(maker.ensure(paths))
    assert set(again) == set(cards) and len(engine.made) == made  # cached: no model call
    assert maker.current(["Clients/Acme.md"]).keys() == {"Clients/Acme.md"}
    engine.fail = ("Village solar",)
    store.remove("Ideas/Village solar.md")
    assert "Ideas/Village solar.md" not in asyncio.run(maker.ensure(paths))


def test_card_is_stale_after_an_edit(
    parts: tuple[Index, CardStore, CardMaker, Engine], vault: Vault
) -> None:
    ix, store, maker, engine = parts
    asyncio.run(maker.ensure(["Clients/Acme.md"]))
    vault.write_text("Clients/Acme.md", "# Acme\nnew budget\n")
    ix.update_note("Clients/Acme.md")
    assert maker.current(["Clients/Acme.md"]) == {}


def test_cards_as_candidate_source(
    parts: tuple[Index, CardStore, CardMaker, Engine], vault: Vault
) -> None:
    ix, store, maker, engine = parts
    asyncio.run(maker.ensure(["Ideas/Village solar.md", "Clients/Acme.md"]))
    store.put(
        Card("Personal/Secret.md", ix.hashes()["Personal/Secret.md"], "social enterprise", ())
    )
    resolver = ScopeResolver(ix, lambda r: True)
    tools = VaultTools(ix, resolver, lambda r: vault.read_text(r), lambda: date(2026, 11, 6))
    gatherer = Gatherer(tools, card_search(store, ix.hashes), card_summaries(store, ix.hashes))
    found = gatherer.gather(["social enterprise"])
    paths = {c.path: c for c in found.items}
    assert paths["Ideas/Village solar.md"].sources == {"card"}  # the note never says it
    assert paths["Ideas/Village solar.md"].summary.startswith("A social enterprise")
    assert gatherer.from_paths(["Clients/Acme.md"]).items[0].summary == "About Acme."
    assert "Personal/Secret.md" not in paths  # a stray card of a private note is never used
