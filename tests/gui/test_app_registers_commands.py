"""The app's own imports register the built-in slash commands (a removed import once dropped
them all, while every test that imports ``commands_builtin`` itself still passed)."""

import subprocess
import sys


def test_the_app_registers_the_slash_commands() -> None:
    code = (
        "import paper_pile.gui.app\n"
        "from paper_pile.core.commands import REGISTRY\n"
        "ids = set(REGISTRY._commands)\n"
        "assert {'h1', 'table', 'ai-rewrite', 'ai-tone', 'ai-translate'} <= ids, sorted(ids)\n"
    )
    done = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert done.returncode == 0, done.stderr[-2000:]
