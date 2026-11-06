"""How a vault-agent answer is drawn in the chat (PLAN_vault_agent §7, §7.1): its ``[n]``
citations as pills (hover: the note § section; click: open it at the cited lines, Ctrl+click:
in split view — ``static/chat.js`` sends the click, ``chat.py`` opens). Pure functions over the
rendered HTML and the turn's saved ``vault`` payload; no NiceGUI here.
"""

import html
import re
from collections.abc import Sequence
from typing import Any

_LABELS = re.compile(r"\[(\d+(?:\s*,\s*\d+)*)\]")
PREVIEW = 220  # characters of the cited text in a pill's hover
_CODE = re.compile(r"(<pre\b.*?</pre>|<code\b.*?</code>|<[^>]+>)", re.DOTALL | re.IGNORECASE)


def cite_tip(row: dict[str, Any]) -> str:
    """The hover text of a pill: the note, its section, the start of the cited text."""
    where = str(row.get("title") or row.get("path") or "")
    if row.get("heading"):
        where += f" § {row['heading']}"
    text = " ".join(str(row.get("excerpt") or row.get("anchor") or "").split())
    if text:
        where += f" — “{text[:PREVIEW]}{'…' if len(text) > PREVIEW else ''}”"
    return where


def cite_pills(rendered: str, cites: Sequence[dict[str, Any]], turn: int) -> str:
    """``rendered`` (the answer's HTML) with every ``[n]`` that names a saved citation as a
    pill; labels inside code, tags and unknown numbers stay as they are."""
    rows = {int(c["n"]): c for c in cites if isinstance(c, dict) and isinstance(c.get("n"), int)}
    if not rows:
        return rendered

    def pills(m: re.Match[str]) -> str:
        nums = [int(n) for n in m.group(1).replace(" ", "").split(",")]
        if not all(n in rows for n in nums):
            return m.group(0)
        out = []
        for n in nums:
            tip = html.escape(cite_tip(rows[n]), quote=True)
            out.append(
                f'<a class="pp-cite" href="#" data-turn="{turn}" data-n="{n}" '
                f'data-tip="{tip}">{n}</a>'
            )
        return "".join(out)

    parts = _CODE.split(rendered)
    for i, part in enumerate(parts):
        if i % 2 == 0:  # text between tags (code blocks and tags are the odd parts)
            parts[i] = _LABELS.sub(pills, part)
    return "".join(parts)
