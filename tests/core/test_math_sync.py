"""The editor's math grammar (Lezer, tools/editor_src/math.js) must agree with the Python
reference parser on tests/fixtures/math_cases.json. Needs Node and the editor's node_modules
(dev-only); skipped on machines without them."""

import shutil
import subprocess
from pathlib import Path

import pytest

EDITOR_SRC = Path(__file__).parent.parent.parent / "tools" / "editor_src"


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
@pytest.mark.skipif(not (EDITOR_SRC / "node_modules").is_dir(), reason="run tools/build_editor.sh")
def test_editor_grammar_agrees_with_python_parser() -> None:
    result = subprocess.run(
        ["node", "check_math.mjs"], cwd=EDITOR_SRC, capture_output=True, text=True, timeout=60
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "agree" in result.stdout
