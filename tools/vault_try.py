# ruff: noqa: E402
"""Hand check of the vault agent against a real model (not the eval — that is
``tools/ai_eval/vault/``, PLAN_vault_agent §8). Prints what each request becomes.

    uv run python tools/vault_try.py --model gemma4:12b "where are my social business notes"
    uv run python tools/vault_try.py --model gemma4:12b          # a few built-in requests
    uv run python tools/vault_try.py --model gemma4:12b --find   # + candidates and the judge,
                                                                 #   on a small built-in vault

Nothing is written anywhere but a temp folder.
"""

import argparse
import asyncio
import os
import sys
import tempfile
import time
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from paper_pile.core.ai.access import grant_now
from paper_pile.core.ai.engine import AiEngine
from paper_pile.core.ai.vault.candidates import Gatherer
from paper_pile.core.ai.vault.cards import CardMaker, CardStore, card_search, card_summaries
from paper_pile.core.ai.vault.meta import VaultMeta
from paper_pile.core.ai.vault.plan import make_plan
from paper_pile.core.ai.vault.run import VaultAgent, run_plan
from paper_pile.core.ai.vault.scope import ScopeResolver, describe, note_folders
from paper_pile.core.ai.vault.tools import VaultTools
from paper_pile.core.ai.vault.understand import RequestContext, VaultRequest, understand_request
from paper_pile.core.config import Config
from paper_pile.core.index import Index
from paper_pile.core.vault import Vault

SAMPLES = [
    "where are my social business notes? summarise all of them",
    "in Marketing, which notes talk about social media campaigns",
    "what did I write in my daily notes last week",
    "how many notes have no tags",
    "add a Sources section to every note in Research",
    "what is the capital of France",
]
FIND_SAMPLES = [
    "where are my social business notes?",
    "summarise my social business notes",
    "who lends without collateral in my notes, and to whom?",
    "list every client and their budget",
    "how many notes have no tags",
]
FOLDERS = ["Clients", "Projects", "Research", "Marketing", "Journal", "Meetings", "Ideas"]
TAGS = ["client", "idea", "marketing", "todo", "meeting"]

# a small vault with traps: on-topic notes without the words, notes that only share a word
MINI = {
    "Research/Yunus.md": "# Muhammad Yunus\nFounder of Grameen Bank. Microcredit for the "
    "poor; the seven principles of a social business. See [[Banker to the poor]].\n",
    "Research/Enterprise models.md": "# Enterprise models\nCompanies with a social mission "
    "that reinvest their profits instead of paying dividends.\n",
    "Ideas/Village solar.md": "#idea\n# Village solar lamps\nSell solar lamps to rural "
    "families at cost; every surplus goes into reaching the next village. No dividends.\n",
    "Reading/Banker to the poor.md": "# Banker to the Poor\nBook notes: lending without "
    "collateral, women borrowers, group responsibility.\n",
    "Journal/2026-11-02.md": "Met the NGO about the microfinance pilot in Rangpur.\n",
    "Personal/Weekend.md": "# Weekend\nA social evening with friends after the business "
    "dinner. Great food.\n",
    "Marketing/Instagram plan.md": "#marketing\n# Instagram plan\nSocial media posts three "
    "times a week; reels; influencer outreach.\n",
    "Clients/Acme.md": "#client\n# Acme\nBudget 10k, invoice monthly.\n",
    "Private/Diary.md": "---\nai: false\n---\nPrivate thoughts on social business.\n",
}


def show_request(found: VaultRequest) -> None:
    print(f"  needs_vault={found.needs_vault}")
    for n, s in enumerate(found.steps):
        dep = f" after {s.depends_on}" if s.depends_on >= 0 else ""
        print(f"  {n}. {s.action}{dep}  topic={s.topic!r}  meta={s.meta!r}")
        if s.terms:
            print(f"     terms: {', '.join(s.terms)}")
        scope = describe(s.scope)
        if scope or s.from_result:
            print(f"     scope: {scope} from_result={s.from_result!r}")
        print(f"     detail: {s.detail}")
    if found.question:
        print(f"  ASK: {found.question} {list(found.options)}")


async def find(ai: AiEngine, root: Path, request: str, cards: bool) -> None:
    """The fast path end to end on the small vault: understand → plan → run."""
    ix = Index(ai.vault)
    ix.sync()
    resolver = ScopeResolver(ix, ai.policy().may_read)
    tools = VaultTools(ix, resolver, ai.read_note)
    store = CardStore(root)
    maker = CardMaker(ai, store, ai.read_note, ix.hashes, ix.title)
    if cards:
        t = time.monotonic()
        made = await maker.ensure(ix.paths())
        print(f"\n  {len(made)} cards in {time.monotonic() - t:.1f} s")
    gatherer = Gatherer(tools, card_search(store, ix.hashes), card_summaries(store, ix.hashes))
    agent = VaultAgent(ai, tools, gatherer, maker, VaultMeta(ix, resolver))
    ctx = RequestContext(
        today=date.today(),
        folders=note_folders(r.path for r in resolver.readable()),
        tags=agent.tags(),
    )
    t = time.monotonic()
    found = await understand_request(ai, request, ctx)
    print(f"\n> {request}   (understood in {time.monotonic() - t:.1f} s)")
    if found is None or not found.needs_vault:
        print("  (no vault request)" if found else "  (no usable answer)")
        return
    show_request(found)
    plan = make_plan(found, resolver, None, request)
    if plan.choice is not None:
        print(f"  ASK: {plan.choice.question} {list(plan.choice.options)}")
        return
    t = time.monotonic()
    stages: list[str] = []
    result = await run_plan(
        agent, plan, request, on_progress=lambda i, s, d, n: stages.append(f"{i}:{s} {d}/{n}")
    )
    print(f"  ran in {time.monotonic() - t:.1f} s  ({', '.join(stages[-6:])})")
    if result.choice is not None:
        print(f"  ASK: {result.choice.question} {list(result.choice.options)}")
    for k, reply in enumerate(result.replies):
        print(f"  --- step {k} reply:")
        print("  " + reply.text.replace("\n", "\n  "))
        for src in reply.sources:
            print(f"     {src.label}  ({src.path}:{src.start}-{src.end})")
        if reply.unverified_note:
            print(f"     ! {reply.unverified_note}")
        for note in reply.notices:
            print(f"     · {note}")
        if reply.hints:
            print("     hints: " + " | ".join(h.label for h in reply.hints))


async def main(args: argparse.Namespace) -> int:
    os.environ["PAPER_PILE_AI"] = "1"
    work = Path(tempfile.mkdtemp(prefix="pp-vault-try-"))
    root = work / "v"
    root.mkdir()
    config = Config(global_path=work / "c.toml", vault=root)
    config.set("ai.provider", args.provider)
    config.set("ai.model", args.model)
    config.set("ai.preload", False)
    if args.find:
        vault = Vault(root)
        for rel, text in MINI.items():
            vault.create_note(rel, text)
        grant_now(root, work / "a")
    ai = AiEngine(Vault(root), config, access_dir=work / "a")
    if args.find:
        for request in args.requests or FIND_SAMPLES:
            await find(ai, root, request, args.cards)
        return 0
    ctx = RequestContext(today=date.today(), folders=FOLDERS, tags=TAGS)
    for request in args.requests or SAMPLES:
        t = time.monotonic()
        found = await understand_request(ai, request, ctx)
        print(f"\n> {request}   ({time.monotonic() - t:.1f} s)")
        if found is None:
            print("  (no usable answer)")
            continue
        show_request(found)
    return 0


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--model", required=True)
    p.add_argument("--provider", default="ollama")
    p.add_argument("--find", action="store_true", help="also gather and judge on a small vault")
    p.add_argument("--cards", action="store_true", help="with --find: make note cards first")
    p.add_argument("requests", nargs="*")
    raise SystemExit(asyncio.run(main(p.parse_args())))
