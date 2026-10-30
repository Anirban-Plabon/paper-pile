# ruff: noqa: E402
"""The AI edit eval against a real Ollama model (``docs/AI_EDITS.md`` §10, P26.15). Dev tool.

    uv run python tools/ai_eval/run.py --model gemma4:12b [--runs 3] [--case 05] [--host URL]

Every case (but the unit-only ones) runs ``--runs`` times on a fresh scratch vault through the
app's own pipeline; prints the pass rate per case and per failing check, the model calls and
the time; writes a JSON report to a scratch folder (never into the repo). The user's own
settings, vaults and AI access grants are not read or touched.
"""

import argparse
import asyncio
import json
import os
import sys
import tempfile
import time
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path

os.environ["PAPER_PILE_AI"] = "1"  # as `paper-pile --ai`
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ai_eval.cases import Case, load_cases, run_case, write_vault
from ai_eval.checks import run_checks
from paper_pile.core.ai.engine import AiEngine
from paper_pile.core.config import Config
from paper_pile.core.index import Index
from paper_pile.core.vault import Vault


@dataclass
class Run:
    passed: bool
    failed: list[tuple[str, str]]  # (check, detail)
    calls: int
    seconds: float
    after: str


async def one_run(case: Case, model: str, host: str, work: Path) -> Run:
    root = work / "vault"
    write_vault(case, root)
    vault = Vault(root)
    index = Index(vault)
    index.rebuild()
    config = Config(global_path=work / "config.toml", vault=root)
    config.set("ai.model", model)
    if host:
        config.set("ai.host", host)
    if case.num_ctx:
        config.set("ai.num_ctx", case.num_ctx)
    ai = AiEngine(vault, config, index, access_dir=work / "access")
    ai.allow()
    outcome = await run_case(case, ai)
    checks = run_checks(outcome)
    failed = [(name, detail) for name, ok, detail in checks if not ok]
    return Run(not failed, failed, outcome.calls, round(outcome.seconds, 1), outcome.after)


async def main(args: argparse.Namespace) -> int:
    cases = [c for c in load_cases() if not c.unit_only and c.name.startswith(args.case)]
    out_dir = Path(args.out or tempfile.mkdtemp(prefix="pp-ai-eval-"))
    out_dir.mkdir(parents=True, exist_ok=True)
    report: dict[str, list[dict[str, object]]] = {}
    began = time.monotonic()
    total = 0
    for case in cases:
        runs: list[Run] = []
        for n in range(args.runs):
            with tempfile.TemporaryDirectory(prefix="pp-ai-eval-") as tmp:
                runs.append(await one_run(case, args.model, args.host, Path(tmp)))
            mark = "pass" if runs[-1].passed else "FAIL"
            print(f"  {case.name} run {n + 1}: {mark}", flush=True)
        passed = sum(r.passed for r in runs)
        total += passed
        report[case.name] = [asdict(r) for r in runs]
        fails = Counter(name for r in runs for name, _detail in r.failed)
        calls = sum(r.calls for r in runs) / len(runs)
        secs = sum(r.seconds for r in runs) / len(runs)
        line = f"{case.name:32} {passed}/{len(runs)}  calls {calls:.1f}  {secs:.1f} s"
        print(line + (f"  {dict(fails)}" if fails else ""))
    count = len(cases) * args.runs
    print(f"\n{args.model}: {total}/{count} runs passed in {time.monotonic() - began:.0f} s")
    name = args.model.replace("/", "_").replace(":", "_")
    path = out_dir / f"report-{name}.json"
    data = {"model": args.model, "runs": args.runs, "cases": report}
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"report: {path}")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--model", required=True)
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--case", default="", help="only cases whose name starts with this")
    parser.add_argument("--host", default="", help="Ollama host (default: the app's default)")
    parser.add_argument("--out", default="", help="report folder (default: a scratch folder)")
    sys.exit(asyncio.run(main(parser.parse_args())))
