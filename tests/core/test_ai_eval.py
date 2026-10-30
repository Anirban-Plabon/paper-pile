"""P26.14: the AI edit eval cases (AI_EDITS §10) in unit mode — the app's own pipeline with the
scripted replies in each case's ``fake.json`` (good and bad ones). The same cases and checks
run against a real model with ``tools/ai_eval/run.py``."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
from ai_eval.cases import Case, load_cases, run_case, write_vault  # noqa: E402
from ai_eval.checks import run_checks  # noqa: E402

from paper_pile.core.ai.engine import AiEngine  # noqa: E402
from paper_pile.core.ai.fake import FakeProvider  # noqa: E402
from paper_pile.core.config import Config  # noqa: E402
from paper_pile.core.index import Index  # noqa: E402
from paper_pile.core.vault import Vault  # noqa: E402

CASES = load_cases()


def test_the_cases_are_there() -> None:
    names = {c.name.split("-")[0] for c in CASES}
    assert {"01", "02", "03", "04", "05", "06", "07", "08", "09", "10", "12", "13", "15"} <= names


@pytest.mark.parametrize("case", CASES, ids=[c.name for c in CASES])
async def test_case(case: Case, tmp_path: Path) -> None:
    write_vault(case, tmp_path / "v")
    vault = Vault(tmp_path / "v")
    index = Index(vault)
    index.rebuild()
    fake = FakeProvider(delay=0, script=list(case.script))
    config = Config(vault=vault.root)
    if case.num_ctx:
        config.set("ai.num_ctx", case.num_ctx)
    ai = AiEngine(vault, config, index, provider_factory=lambda _c: fake)
    ai.allow()
    outcome = await run_case(case, ai)
    failed = [r for r in run_checks(outcome, unit=True) if not r[1]]
    assert not failed, f"{failed}\n--- after ---\n{outcome.after}"
    assert fake.script == [], "every scripted reply is used (the pipeline made the calls expected)"
