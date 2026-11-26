"""The markdown pair rules (static/pairs.js: ** ` ~ == brackets, wrapping a selection) shared by the
editor, the chat boxes and table cells: tests/js/pairs_cases.mjs. Needs Node; skipped without it."""

import shutil
import subprocess
from pathlib import Path

import pytest

CASES = Path(__file__).parent.parent / "js" / "pairs_cases.mjs"


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_pair_rules() -> None:
    result = subprocess.run(["node", str(CASES)], capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "pair cases pass" in result.stdout
