"""Every formula in tests/fixtures/tex_cases.json (LaTeX that notes and AI answers use a lot) must
typeset with the app's KaTeX setup (tools/editor_src/tex.js: macros, environment fallbacks,
mhchem). Needs Node and the editor's node_modules (dev-only); skipped on machines without them."""

import shutil
import subprocess
from pathlib import Path

import pytest

EDITOR_SRC = Path(__file__).parent.parent.parent / "tools" / "editor_src"


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
@pytest.mark.skipif(not (EDITOR_SRC / "node_modules").is_dir(), reason="run tools/build_editor.sh")
def test_common_latex_renders_with_the_app_katex_setup() -> None:
    result = subprocess.run(
        ["node", "check_tex.mjs"], cwd=EDITOR_SRC, capture_output=True, text=True, timeout=60
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "formulas render" in result.stdout
