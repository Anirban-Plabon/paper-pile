# ruff: noqa: E402
"""Hand check of the vault agent's understanding step against a real model (not the eval —
that is ``tools/ai_eval/vault/``, PLAN_vault_agent §8). Prints what each request becomes.

    uv run python tools/vault_try.py --model gemma4:12b "where are my social business notes"
    uv run python tools/vault_try.py --model gemma4:12b          # a few built-in requests

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

from paper_pile.core.ai.engine import AiEngine
from paper_pile.core.ai.vault.scope import describe
from paper_pile.core.ai.vault.understand import RequestContext, understand_request
from paper_pile.core.config import Config
from paper_pile.core.vault import Vault

SAMPLES = [
    "where are my social business notes? summarise all of them",
    "in Marketing, which notes talk about social media campaigns",
    "what did I write in my daily notes last week",
    "how many notes have no tags",
    "add a Sources section to every note in Research",
    "what is the capital of France",
]
FOLDERS = ["Clients", "Projects", "Research", "Marketing", "Journal", "Meetings", "Ideas"]
TAGS = ["client", "idea", "marketing", "todo", "meeting"]


async def main(args: argparse.Namespace) -> int:
    os.environ["PAPER_PILE_AI"] = "1"
    work = Path(tempfile.mkdtemp(prefix="pp-vault-try-"))
    (work / "v").mkdir()
    config = Config(global_path=work / "c.toml", vault=work / "v")
    config.set("ai.provider", args.provider)
    config.set("ai.model", args.model)
    config.set("ai.preload", False)
    ai = AiEngine(Vault(work / "v"), config, access_dir=work / "a")
    ctx = RequestContext(today=date.today(), folders=FOLDERS, tags=TAGS)
    for request in args.requests or SAMPLES:
        t = time.monotonic()
        found = await understand_request(ai, request, ctx)
        print(f"\n> {request}   ({time.monotonic() - t:.1f} s)")
        if found is None:
            print("  (no usable answer)")
            continue
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
    return 0


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--model", required=True)
    p.add_argument("--provider", default="ollama")
    p.add_argument("requests", nargs="*")
    raise SystemExit(asyncio.run(main(p.parse_args())))
