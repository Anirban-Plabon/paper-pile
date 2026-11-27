# ruff: noqa: E501  (embedded JavaScript and markdown samples)
"""Rendering QA: does every kind of note content render in the real editor? (dev tool)

Launches the native app offscreen on a throwaway vault (own config / state / cache), puts each
sample note into the real editor and checks what was drawn against what the Python parser (the
reference for export, print, chat and embeds) says the note holds:

  * every formula is typeset, none shows KaTeX's red error text, and the TeX source the editor
    typeset is the one Python reads (``|`` inside a table cell, ``>`` inside a quote);
  * every table is drawn as a table with Python's column and row count (a text line under a
    table that Python reads as a row is one in the editor too);
  * every ```mermaid block is drawn; no `$` delimiter is left showing outside code;
  * no widget throws (CodeMirror logs a crashed widget with console.error).

Then real paste events (HTML as the clipboard holds it) go through the app's Smart Paste path
and the same checks run on the note that results.

Usage:  uv run python tools/qa_render.py [--keep] [--all]
"""

import asyncio
import base64
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

import websockets

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from paper_pile.core.ai.access import Grant, save_grant  # noqa: E402
from paper_pile.core.parser import math_spans, parse  # noqa: E402

LOG: Path | None = None  # the app's --debug log (the Ask box's targets)

REPO = Path(__file__).resolve().parent.parent
PORT = int(os.environ.get("QA_PORT", "9341"))

# name -> (markdown, options). Options: "dollars": literal `$` may show; "known": an accepted
# difference between editor and Python (reported, not failed).
CASES: dict[str, tuple[str, dict[str, str | bool]]] = {
    # ---- inline math
    "inline: basic": ("Euler: $e^{i\\pi}+1=0$ and $a^2+b^2=c^2$.", {}),
    "inline: next to punctuation": ("($x$), $y$-th, $z$'s and $w$.", {}),
    "inline: dollar amounts stay text": ("It costs $5 and $10, or \\$20.", {"dollars": True}),
    "inline: escaped dollar inside": ("Price $\\$x + 1$ here", {}),
    "inline: html specials": ("$a<b>c \\& d$ and $x \\gt 0$", {}),
    "inline: in heading and bold": ("# About $\\alpha$\n\n**Note $x$:** text", {}),
    "inline: env inside inline math": ("See $\\begin{align} a &= b \\end{align}$ here", {}),
    "inline: double dollar in text": ("text $$x^2$$ more", {}),
    "inline: spans a line break": (
        "$a +\nb$ end",
        {
            "known": "the editor cannot draw an inline widget across a line break; it shows the source"
        },
    ),
    # ---- display math
    "block: multi-line": ("$$\n\\int_0^1 x\\,dx = \\frac12\n$$", {}),
    "block: same line": ("$$E = mc^2$$", {}),
    "block: right after a paragraph": ("Formula:\n$$\nx^2\n$$\nafter", {}),
    "block: in a list item": ("- item\n\n  $$\n  x = 1\n  $$\n- next", {}),
    "block: in a quote": ("> $$\n> x^2 + y^2\n> $$", {}),
    "block: in a callout": ("> **Note:** see\n>\n> $$\n> \\frac{a}{b}\n> = c\n> $$", {}),
    "block: in a nested quote": ("> > $$\n> > a\n> > $$", {}),
    "block: blank line inside is text": ("$$\na\n\nb\n$$", {"dollars": True}),
    "block: aligned and cases": (
        "$$\n\\begin{aligned} a &= b \\\\ c &= d \\end{aligned}\n$$\n\n$$\nf(x)=\\begin{cases}1 & x>0\\\\0&\\text{else}\\end{cases}\n$$",
        {},
    ),
    "block: matrices": ("$$\n\\begin{bmatrix}1&2\\\\[4pt]3&4\\end{bmatrix}\n$$", {}),
    "block: LaTeX KaTeX lacks": (
        "$$\n\\begin{equation} E = mc^2 \\label{eq:e} \\end{equation}\n$$\n\nBy $\\eqref{eq:e}$, $\\abs{x} \\le \\norm{v}$, $\\mathbbm{1}_A$.\n\n$$\n\\begin{multline} a + b \\\\ + c \\end{multline}\n$$\n\n$$\n\\begin{eqnarray} a &=& b \\end{eqnarray}\n$$",
        {},
    ),
    "block: chemistry": ("$$\\ce{2H2 + O2 -> 2H2O}$$ and $\\pu{5 m/s}$", {}),
    "block: unicode": ("$α + β ≤ γ$ and $\\text{für alle } x$ and $90°$", {}),
    # ---- tables
    "table: basic": ("| a | b |\n| --- | --- |\n| 1 | 2 |\n| 3 | 4 |", {}),
    "table: alignment": ("| l | c | r |\n| :-- | :-: | --: |\n| 1 | 2 | 3 |", {}),
    "table: escaped pipe": ("| op | x |\n| --- | --- |\n| a \\| b | 2 |", {}),
    "table: pipe in math and code": ("| f | c |\n| --- | --- |\n| $\\|x\\|$ | `a\\|b` |", {}),
    "table: math in cells": ("| f | v |\n| --- | --- |\n| $a_1$ | $\\frac{1}{2}$ |", {}),
    "table: wikilink alias": ("| n |\n| --- |\n| [[note\\|alias]] |", {}),
    "table: empty and wide cells": ("| a | 中文 |\n| --- | --- |\n|  | 字 |", {}),
    "table: header only": ("| a | b |\n| --- | --- |", {}),
    "table: ragged rows": ("| a | b | c |\n| --- | --- | --- |\n| 1 |\n| 1 | 2 | 3 | 4 |", {}),
    "table: right after a paragraph": ("Intro line\n| a | b |\n| --- | --- |\n| 1 | 2 |", {}),
    "table: text line under it": ("| a | b |\n| --- | --- |\n| 1 | 2 |\nnext line", {}),
    "table: in a list": ("- item\n\n  | a | b |\n  | --- | --- |\n  | 1 | 2 |", {}),
    "table: in a quote": ("> | a | b |\n> | --- | --- |\n> | 1 | 2 |", {}),
    "table: two in a row": ("| a |\n| --- |\n| 1 |\n\n| b | c |\n| --- | --- |\n| 2 | 3 |", {}),
    # ---- other blocks
    "code: dollars are not math": (
        "```bash\necho $HOME $$ \\(x\\)\n```\n\n~~~\n$a$\n~~~\n\n`$b$` inline",
        {"dollars": True},
    ),
    "mermaid: valid": ("```mermaid\ngraph TD\nA-->B\n```", {}),
    "mermaid: invalid": ("```mermaid\ngraph TD\nA-->\n```", {"bad_mermaid": True}),
    "lists: nested, tasks, numbers": (
        "- a\n  - b\n    - c\n- [ ] task\n- [x] done\n\n1. one\n2. two\n   1. sub",
        {},
    ),
    "misc: footnote, hr, setext, html": (
        "Text[^1]\n\n[^1]: note $x$\n\n---\n\nTitle\n=====\n\n<b>raw</b> &amp; <script>x</script>",
        {},
    ),
    "misc: callouts": ("> [!note]\n> body $x$\n\n> **Warning:** careful", {}),
    "misc: images and links": (
        "![remote](https://e.org/i.png) [link](https://e.org/a_(b)) <https://e.org>",
        {},
    ),
    "embed: note with math": ("![[mathnote]]", {"embed": True}),
}


def _katex(tex: str, display: bool = False) -> str:
    inner = (
        '<span class="katex"><span class="katex-mathml"><math><semantics><mi>x</mi>'
        f'<annotation encoding="application/x-tex">{tex}</annotation></semantics></math></span>'
        '<span class="katex-html" aria-hidden="true">VISUAL</span></span>'
    )
    return f'<span class="katex-display">{inner}</span>' if display else inner


CHAT_TABLE = (
    "<p>Here is the comparison:</p><table><thead><tr><th>Model</th><th>Score</th></tr></thead>"
    f"<tbody><tr><td>A</td><td>{_katex('|x|')}</td></tr><tr><td>B | C</td><td>2</td></tr></tbody></table>"
)
GDOCS_TABLE = (
    '<meta charset="utf-8"><b style="font-weight:normal;" id="docs-internal-guid-1"><div dir="ltr">'
    "<table><tbody><tr><td><p><span>Name</span></p></td><td><p><span>Age</span></p></td></tr>"
    "<tr><td><p><span>Bob</span></p></td><td><p><span>3</span></p></td></tr></tbody></table></div></b>"
)
# name -> (note text with ‸ where the caret is, clipboard html, plain text,
#          expected (tables, rows of the first table, formulas))
PASTES: dict[str, tuple[str, str, str, tuple[int, int, int]]] = {
    "paste: chat answer with a table mid-line": (
        "Intro ‸rest of line\nnext line",
        CHAT_TABLE,
        "",
        (1, 2, 1),
    ),
    "paste: table above a text line": ("‸\nnext line", CHAT_TABLE, "", (1, 2, 1)),
    "paste: Google Docs table": ("Before\n‸\nAfter", GDOCS_TABLE, "", (1, 1, 0)),
    "paste: inline formula mid-sentence": ("Let ‸ be.", _katex("a^2"), "", (0, 0, 1)),
    "paste: display math in a list item": (
        "‸",
        f"<ol><li><p>Step:</p>{_katex('x^2', True)}</li><li><p>Next</p></li></ol>",
        "",
        (0, 0, 1),
    ),
    "paste: chat plain text with \\[ \\]": (
        "‸",
        "",
        "Use \\(x^2\\) and\n\\[\n\\int f\n\\]",
        (0, 0, 2),
    ),
    "paste: code block after text": (
        "Run: ‸",
        "<pre><code class='language-sh'>ls $HOME</code></pre>",
        "",
        (0, 0, 0),
    ),
}

JS = r"""
window.qa = {
  view() { const c = document.querySelector('.pp-split .cm-content'); return c.cmTile?.root?.view ?? c.cmView.view; },
  set(text, caret) { const v = qa.view(); v.dispatch({changes: {from: 0, to: v.state.doc.length, insert: text}, selection: {anchor: caret}}); v.focus(); return v.state.doc.length; },
  text() { return qa.view().state.doc.toString(); },
  paste(html, text) {
    const dt = new DataTransfer();
    if (html) dt.setData('text/html', html);
    if (text) dt.setData('text/plain', text);
    qa.view().contentDOM.dispatchEvent(new ClipboardEvent('paste', {clipboardData: dt, bubbles: true, cancelable: true}));
  },
  errors: [],
  report() {
    const root = document.querySelector('.pp-split .cm-content');
    const katex = [...root.querySelectorAll('.katex')].filter(k => !k.parentElement.closest('.katex, .pp-embed'));
    const tex = katex.map(k => (k.querySelector('annotation') || {}).textContent ?? null);
    const bad = root.querySelectorAll('.katex-error, .katex [style*="#cc0000"], .katex [style*="rgb(204, 0, 0)"]').length;
    const tables = [...root.querySelectorAll('.pp-table-edit table')].map(t => ({
      cols: t.querySelector('tr') ? t.querySelector('tr').children.length : 0,
      rows: t.querySelectorAll('tbody tr').length,
    }));
    const mermaid = [...root.querySelectorAll('.pp-mermaid')].filter(m => m.querySelector('svg')).length;
    const renderErrors = root.querySelectorAll('.pp-render-error').length;
    // visible text outside code and outside drawn widgets
    let shown = '';
    for (const line of root.querySelectorAll('.cm-line')) {
      if (line.closest('.pp-table, .pp-math-block, .pp-embed') || /pp-codeblock|pp-fence|cm-codeblock/.test(line.className)) continue;
      const copy = line.cloneNode(true);
      copy.querySelectorAll('.katex, .pp-code, code, .cm-widgetBuffer').forEach(e => e.remove());
      shown += copy.textContent + '\n';
    }
    const embed = [...document.querySelectorAll('.pp-split .pp-embed-body')].map(b => ({
      katex: b.querySelectorAll('.katex').length, raw: b.querySelectorAll('.math:not([data-typeset])').length,
    }));
    return {tex, bad, tables, mermaid, renderErrors, shown, embed, errors: qa.errors.splice(0)};
  },
};
const origError = console.error;
console.error = (...a) => { qa.errors.push(a.map(String).join(' ').slice(0, 200)); origError(...a); };
window.addEventListener('error', e => qa.errors.push(String(e.message)));
'ok'
"""


class Cdp:
    def __init__(self, ws: websockets.ClientConnection) -> None:
        self.ws, self.n = ws, 0

    async def js(self, expr: str) -> object:
        self.n += 1
        params = {"expression": expr, "awaitPromise": True, "returnByValue": True}
        await self.ws.send(
            json.dumps({"id": self.n, "method": "Runtime.evaluate", "params": params})
        )
        while True:
            r = json.loads(await self.ws.recv())
            if r.get("id") == self.n:
                return r.get("result", {}).get("result", {}).get("value")

    async def call(self, method: str, **params: object) -> dict:
        self.n += 1
        await self.ws.send(json.dumps({"id": self.n, "method": method, "params": params}))
        while True:
            r = json.loads(await self.ws.recv())
            if r.get("id") == self.n:
                return r.get("result", {})

    async def click(self, x: float, y: float) -> None:
        for t in ("mousePressed", "mouseReleased"):
            await self.call(
                "Input.dispatchMouseEvent", type=t, x=x, y=y, button="left", clickCount=1
            )
        await asyncio.sleep(0.4)

    async def key(self, key: str, code: int) -> None:
        for t in ("rawKeyDown", "keyUp"):
            await self.call("Input.dispatchKeyEvent", type=t, key=key, windowsVirtualKeyCode=code)
        await asyncio.sleep(0.2)


CELL_NOTE = "caret\n\n| f | v |\n| --- | --- |\n| $x_1$ | $\\frac{a}{b}$ |\n\nend"
# the first body cell's centre, and what each body cell shows: RENDERED (KaTeX drawn), an open
# input, or its raw text
CELL_AT = "(() => { const r = document.querySelector('.pp-split .pp-table-edit tbody td').getBoundingClientRect(); return [r.left + r.width / 2, r.top + r.height / 2]; })()"
LINE_AT = "(() => { const r = document.querySelector('.pp-split .cm-line').getBoundingClientRect(); return [r.left + 30, r.top + r.height / 2]; })()"
CELLS = "[...document.querySelectorAll('.pp-split .pp-table-edit tbody td')].map(td => td.querySelector('input') ? 'INPUT' : td.querySelector('.katex') ? 'RENDERED' : td.textContent)"


SELECT_NOTE = "caret\n\nHello brave new world here\n\n| a | b |\n| --- | --- |\n| one two | 2 |\n| x \\| y | 4 |\n\nend"
POPUP_SHOWN = "(() => { const p = document.querySelector('.pp-askpop'); return !!p && p.getClientRects().length > 0 && getComputedStyle(p).display !== 'none'; })()"
MARKED = "document.querySelectorAll('.pp-split .pp-table-edit .pp-tsel').length"
ASKED_IN_CELL = "(() => { const m = document.querySelector('.pp-split .pp-table-asked'); return m ? m.textContent : null; })()"
# the Ask target's highlight: widths of its rectangles
BANDS = "[...document.querySelectorAll('.pp-split .pp-ai-band-layer .pp-ai-band')].map(b => Math.round(b.getBoundingClientRect().width))"


def word_width(word: str) -> str:
    return f"(() => {{ const v = qa.view(); const i = v.state.doc.toString().indexOf({json.dumps(word)}); return Math.round(v.coordsAtPos(i + {len(word)}).left - v.coordsAtPos(i).left); }})()"


def word_at(word: str) -> str:
    return f"(() => {{ const v = qa.view(); const c = v.coordsAtPos(v.state.doc.toString().indexOf({json.dumps(word)}) + 2); return [c.left, (c.top + c.bottom) / 2]; }})()"


def cell_at(i: int) -> str:
    return f"(() => {{ const r = document.querySelectorAll('.pp-split .pp-table-edit tbody td')[{i}].getBoundingClientRect(); return [r.left + 12, r.top + r.height / 2]; }})()"


def asked() -> list[str]:
    """What the Ask box was opened about so far (the app logs each target)."""
    if LOG is None or not LOG.exists():
        return []
    return [ln.split(": ", 2)[-1] for ln in LOG.read_text().splitlines() if "ask about" in ln]


async def select_checks(cdp: Cdp, results: list) -> None:
    """Selections open the Ask box about the right text: a double-clicked word, a line, a word in
    a table cell (its place in the note, across `\\|`), a block of cells (its rows)."""

    async def fresh() -> int:
        await cdp.js(f"qa.set({json.dumps(SELECT_NOTE)}, 0)")
        await asyncio.sleep(0.8)
        x, y = await cdp.js(word_at("caret"))
        await cdp.click(x, y)
        return len(asked())

    async def clicks(x: float, y: float, n: int) -> None:
        for k in range(1, n + 1):
            for t in ("mousePressed", "mouseReleased"):
                await cdp.call(
                    "Input.dispatchMouseEvent", type=t, x=x, y=y, button="left", clickCount=k
                )
        await asyncio.sleep(1.2)

    def check(
        name: str, before: int, want: str, extra: tuple[str, bool, str] | None = None
    ) -> None:
        got = asked()[before:]
        results.append(
            (
                name,
                "Ask box about the selection",
                bool(got) and got[-1] == repr(want),
                f"{got} want {want!r}",
            )
        )
        if extra:
            results.append((name, *extra))

    n = await fresh()
    await clicks(*(await cdp.js(word_at("brave"))), 2)
    check(
        "select: double-click a word",
        n,
        "brave",
        ("Ask box shown", bool(await cdp.js(POPUP_SHOWN)), ""),
    )
    bands, width = await cdp.js(BANDS), await cdp.js(word_width("brave"))
    ok = len(bands) == 1 and abs(bands[0] - width) <= 2
    results.append(
        (
            "select: double-click a word",
            "highlight is the word, not its line",
            ok,
            f"bands {bands}, word {width}px",
        )
    )
    n = await fresh()
    await clicks(*(await cdp.js(word_at("brave"))), 3)
    check("select: triple-click a line", n, "Hello brave new world here\n")
    n = await fresh()
    await clicks(*(await cdp.js(cell_at(0))), 1)
    await clicks(*(await cdp.js(cell_at(0))), 2)
    check(
        "select: double-click a word in a cell",
        n,
        "one",
        (
            "the word is highlighted in its cell",
            await cdp.js(ASKED_IN_CELL) == "one",
            str(await cdp.js(ASKED_IN_CELL)),
        ),
    )
    results.append(
        (
            "select: double-click a word in a cell",
            "no band over the table",
            await cdp.js(BANDS) == [],
            str(await cdp.js(BANDS)),
        )
    )
    n = await fresh()
    await clicks(*(await cdp.js(cell_at(2))), 1)  # `x \| y`: the input shows `x | y`
    await cdp.call(
        "Input.dispatchKeyEvent",
        type="rawKeyDown",
        key="Home",
        windowsVirtualKeyCode=36,
        modifiers=8,
    )
    await cdp.call(
        "Input.dispatchKeyEvent", type="keyUp", key="Home", windowsVirtualKeyCode=36, modifiers=8
    )
    await asyncio.sleep(1.2)
    check("select: cell text across an escaped pipe", n, "x \\| y")
    n = await fresh()
    a, b = await cdp.js(cell_at(0)), await cdp.js(cell_at(3))
    await cdp.call(
        "Input.dispatchMouseEvent", type="mousePressed", x=a[0], y=a[1], button="left", clickCount=1
    )
    for k in range(1, 6):
        await cdp.call(
            "Input.dispatchMouseEvent",
            type="mouseMoved",
            x=a[0] + (b[0] - a[0]) * k / 5,
            y=a[1] + (b[1] - a[1]) * k / 5,
            button="left",
        )
    await cdp.call(
        "Input.dispatchMouseEvent",
        type="mouseReleased",
        x=b[0],
        y=b[1],
        button="left",
        clickCount=1,
    )
    await asyncio.sleep(1.2)
    check(
        "select: drag a block of cells",
        n,
        "| one two | 2 |\n| x \\| y | 4 |",
        ("block stays painted", await cdp.js(MARKED) == 4, str(await cdp.js(MARKED))),
    )
    box = await cdp.js(
        "(() => { const i = document.querySelector('.pp-askpop textarea'); if (!i) return null; const r = i.getBoundingClientRect(); return [r.left + 10, r.top + r.height / 2]; })()"
    )
    if box:
        await cdp.click(*box)
        await asyncio.sleep(0.6)
    results.append(
        (
            "select: drag a block of cells",
            "box stays when clicked into",
            bool(box) and bool(await cdp.js(POPUP_SHOWN)),
            str(box),
        )
    )
    # text → whole table → text (user 2026-11-27): with the Ask box open the band shows the table too
    await fresh()
    await drag(cdp, await cdp.js(word_at("Hello")), await cdp.js(word_at("end")))
    r = await cdp.js(BAND_OVER_TABLE)
    results.append(
        (
            "select: text across a whole table",
            "Ask band covers the table",
            bool(await cdp.js(POPUP_SHOWN)) and bool(r.get("covered")) and not r.get("overlap"),
            repr(r),
        )
    )
    if os.environ.get("QA_SHOTS"):
        shot = await cdp.call("Page.captureScreenshot", format="png")
        Path(os.environ["QA_SHOTS"], "ask-across-table.png").write_bytes(
            base64.b64decode(shot["data"])
        )


# the Ask band over a selection that runs across a whole table: the table's box, and whether the
# band's rectangles cover it with no gap and no overlap (two layers tint twice)
BAND_OVER_TABLE = r"""(() => {
  const t = document.querySelector('.pp-split .pp-table-edit');
  const bands = [...document.querySelectorAll('.pp-split .pp-ai-band-layer .pp-ai-band')].map((b) => b.getBoundingClientRect()).sort((a, b) => a.top - b.top);
  if (!t) return {table: false};
  const r = t.getBoundingClientRect();
  let at = r.top, overlap = false;
  for (let i = 0; i < bands.length; i++) {
    const b = bands[i];
    if (i && b.top < bands[i - 1].bottom - 0.5 && b.left < bands[i - 1].right && b.right > bands[i - 1].left) overlap = true;
    if (b.top <= at + 0.5 && b.bottom > at) at = b.bottom;
  }
  return {table: true, bands: bands.length, covered: at >= r.bottom - 0.5, overlap};
})()"""


async def drag(cdp: Cdp, a: list, b: list) -> None:
    await cdp.call(
        "Input.dispatchMouseEvent", type="mousePressed", x=a[0], y=a[1], button="left", clickCount=1
    )
    for k in range(1, 9):
        x, y = a[0] + (b[0] - a[0]) * k / 8, a[1] + (b[1] - a[1]) * k / 8
        await cdp.call("Input.dispatchMouseEvent", type="mouseMoved", x=x, y=y, button="left")
    await cdp.call(
        "Input.dispatchMouseEvent",
        type="mouseReleased",
        x=b[0],
        y=b[1],
        button="left",
        clickCount=1,
    )
    await asyncio.sleep(1.5)


ALIGN_NOTE = "Para one\n\n| a | b |\n| --- | --- |\n| 1 | 2 |\n\nend"
EDITOR_API = "(() => { for (const el of document.querySelectorAll('.pp-split [id^=c]')) { if (!el.querySelector('.cm-editor')) continue; const c = getElement(parseInt(el.id.slice(1))); if (c && c.alignBlocks) return c; } return null; })()"
# the table against the text box: [left gap, right gap, centre offset] in px, and its cells' alignment
TABLE_PLACE = r"""(() => {
  const root = document.querySelector('.pp-split .cm-content');
  const para = [...root.querySelectorAll('.cm-line')].find(l => l.textContent === 'Para one');
  const line = para.getBoundingClientRect(), cs = getComputedStyle(para);
  const L = line.left + parseFloat(cs.paddingLeft), R = line.right - parseFloat(cs.paddingRight);
  const wrap = root.querySelector('.pp-table-edit'); const g = wrap.querySelector('table').getBoundingClientRect();
  return {gaps: [Math.round(g.left - L), Math.round(R - g.right), Math.round((g.left + g.right) / 2 - (L + R) / 2)],
          cells: [...new Set([...wrap.querySelectorAll('th, td')].map(c => getComputedStyle(c).textAlign))]};
})()"""


async def align_checks(cdp: Cdp, results: list) -> None:
    """Note and block alignment place the table like the text (its centre / right edge) and its
    cells follow; the table's right-click menu aligns the table as a block (one undo step)."""

    async def place(setup: str) -> dict:
        await cdp.js(f"qa.set({json.dumps(ALIGN_NOTE)}, 0)")
        await cdp.js(f"{EDITOR_API}.setAlignment({{}}, true)")
        await asyncio.sleep(0.6)
        if setup:
            await cdp.js(setup)
            await asyncio.sleep(0.8)
        return await cdp.js(TABLE_PLACE)

    t0, t1 = ALIGN_NOTE.index("| a"), ALIGN_NOTE.index("| 2 |") + 5
    for name, setup, want in (
        (
            "note centre",
            f"{EDITOR_API}.setAlignment({{'qa.md': {{note: 'center'}}}}, true)",
            "center",
        ),
        ("note right", f"{EDITOR_API}.setAlignment({{'qa.md': {{note: 'right'}}}}, true)", "right"),
        ("block right on the table", f"{EDITOR_API}.alignBlocks('right', {t0}, {t1})", "right"),
    ):
        got = await place(setup)
        gap = got["gaps"][2] if want == "center" else got["gaps"][1]
        results.append((f"align: {name}", "table placed like the text", abs(gap) <= 1, str(got)))
        results.append(
            (f"align: {name}", "cells follow", got["cells"] == [want], str(got["cells"]))
        )
    await place("")
    x, y = await cdp.js(
        "(() => { const r = document.querySelector('.pp-split .pp-table-edit td').getBoundingClientRect(); return [r.left + 10, r.top + r.height / 2]; })()"
    )
    for t in ("mousePressed", "mouseReleased"):
        await cdp.call("Input.dispatchMouseEvent", type=t, x=x, y=y, button="right", clickCount=1)
    await asyncio.sleep(0.5)
    item = await cdp.js(
        "(() => { const i = [...document.querySelectorAll('.pp-tmenu-item')].find(i => i.textContent === 'Align table center'); if (!i) return null; const r = i.getBoundingClientRect(); return [r.left + 10, r.top + r.height / 2]; })()"
    )
    if item:
        await cdp.click(*item)
        await asyncio.sleep(1.2)
    got = await cdp.js(TABLE_PLACE)
    ok = bool(item) and abs(got["gaps"][2]) <= 1 and got["cells"] == ["center"]
    results.append(
        ("align: menu 'Align table center'", "table centred, cells follow", ok, str(got))
    )
    await cdp.js("qa.view().focus()")
    for t in ("rawKeyDown", "keyUp"):
        await cdp.call(
            "Input.dispatchKeyEvent",
            type=t,
            key="z",
            code="KeyZ",
            windowsVirtualKeyCode=90,
            modifiers=2,
        )
    await asyncio.sleep(0.8)
    got = await cdp.js(TABLE_PLACE)
    results.append(
        (
            "align: menu 'Align table center'",
            "Ctrl+Z puts it back",
            got["gaps"][0] <= 8 and got["cells"] != ["center"],
            str(got),
        )
    )


# switch the theme and read the selected tab's background on each of the next frames
THEME_FRAMES = r"""(async (theme) => {
  const tab = document.querySelector('.pp-tab-active'); const out = [];
  window.ppTheme.apply({...window.__pp_theme, theme});
  for (let i = 0; i < 12; i++) { out.push(getComputedStyle(tab).backgroundColor); await new Promise(r => requestAnimationFrame(r)); }
  return out;
})(%s)"""


async def theme_checks(cdp: Cdp, results: list) -> None:
    """A light / dark switch lands at once: no tab, row or button fades through in-between
    colours (user 2026-11-19: the selected tab showed as a grey box), and the hover fades are
    back afterwards."""
    for theme in ("dark", "light", "dark", "light"):
        frames = await cdp.js(THEME_FRAMES % json.dumps(theme))
        results.append(
            (
                f"theme: switch to {theme}",
                "selected tab never in between",
                len(set(frames)) == 1,
                str(frames[:4]),
            )
        )
    await asyncio.sleep(0.3)
    back = await cdp.js(
        "!document.documentElement.classList.contains('pp-theme-switch') && getComputedStyle(document.querySelector('.pp-tab-active')).transitionDuration !== '0s'"
    )
    results.append(("theme: after the switch", "hover fades on again", bool(back), str(back)))
    await cdp.js("window.ppTheme.apply(window.__pp_theme)")


async def cell_checks(cdp: Cdp, results: list) -> None:
    """Click a math cell (it opens for editing), leave it every way: it must render again."""

    async def open_cell() -> object:
        await cdp.js(f"qa.set({json.dumps(CELL_NOTE)}, 0)")
        await asyncio.sleep(0.8)
        x, y = await cdp.js(CELL_AT)
        await cdp.click(x, y)
        return await cdp.js(CELLS)

    async def leave(how: str) -> None:
        if how == "click on text":
            x, y = await cdp.js(LINE_AT)
            await cdp.click(x, y)
        elif how == "Esc":
            await cdp.key("Escape", 27)
        elif how == "Tab":
            await cdp.key("Tab", 9)
            await cdp.key("Escape", 27)
        await asyncio.sleep(1.2)

    for how in ("click on text", "Esc", "Tab"):
        name = f"table cell: click, leave by {how}"
        opened = await open_cell()
        results.append((name, "click opens the cell", opened == ["INPUT", "RENDERED"], str(opened)))
        await leave(how)
        shown = await cdp.js(CELLS)
        results.append((name, "math rendered again", shown == ["RENDERED", "RENDERED"], str(shown)))
    name = "table cell: edit the formula, leave"
    await open_cell()
    await cdp.js(
        "(() => { const i = document.querySelector('.pp-table-input'); i.value = '$y^2$'; i.dispatchEvent(new Event('input')); })()"
    )
    await asyncio.sleep(1.5)  # past the idle commit: Python answers while the cell is still open
    await leave("click on text")
    shown = await cdp.js(CELLS)
    text = str(await cdp.js("qa.text()"))
    results.append(
        (
            name,
            "new formula saved and rendered",
            "$y^2$" in text and shown == ["RENDERED", "RENDERED"],
            f"{shown} {text!r}",
        )
    )
    got = await cdp.js("qa.report()")
    results.append((name, "no widget crashed", not got["errors"], "; ".join(got["errors"])[:200]))


def expected(text: str) -> dict:
    """What Python reads in ``text``: formulas, tables (columns, body rows), mermaid blocks."""
    inline, block = math_spans(text)
    tables, cols, rows, in_table = [], 0, 0, False
    mermaid = 0
    for tok in parse(text):
        if tok.type == "table_open":
            in_table, cols, rows, head = True, 0, 0, True
        elif tok.type == "thead_close":
            head = False
        elif in_table and tok.type == "th_open" and head:
            cols += 1
        elif in_table and tok.type == "tr_open" and not head:
            rows += 1
        elif tok.type == "table_close":
            in_table = False
            tables.append({"cols": cols, "rows": rows})
        elif tok.type == "fence" and tok.info.strip() == "mermaid":
            mermaid += 1
    return {"tex": inline + block, "tables": tables, "mermaid": mermaid}


def norm(tex: str | None) -> str:
    return " ".join((tex or "").split())


def compare(name: str, text: str, got: dict, opts: dict, results: list) -> None:
    want = expected(text)
    known = opts.get("known")

    def check(what: str, ok: bool, detail: str) -> None:
        if not ok and known:
            results.append((name, what, None, f"KNOWN: {known} ({detail})"))
        else:
            results.append((name, what, ok, detail))

    check("no KaTeX error text", got["bad"] == 0, f"{got['bad']} formula(s) in red")
    check(
        "every formula typeset",
        len(got["tex"]) == len(want["tex"]),
        f"editor {len(got['tex'])}, Python {len(want['tex'])}",
    )
    simple = [norm(t) for t in want["tex"] if "\\begin" not in t]
    drawn = [norm(t) for t in got["tex"] if t is not None and "\\begin" not in t]
    check(
        "same TeX as Python", sorted(simple) == sorted(drawn), f"editor {drawn} vs Python {simple}"
    )
    check(
        "tables as Python reads them",
        got["tables"] == want["tables"],
        f"editor {got['tables']}, Python {want['tables']}",
    )
    if not opts.get("bad_mermaid"):
        check(
            "diagrams drawn",
            got["mermaid"] == want["mermaid"] and got["renderErrors"] == 0,
            f"svg {got['mermaid']}/{want['mermaid']}, errors {got['renderErrors']}",
        )
    if not opts.get("dollars"):
        check("no $ left showing", "$" not in got["shown"], repr(got["shown"].strip())[:120])
    if opts.get("embed"):
        e = got["embed"]
        check(
            "embedded note's math typeset",
            bool(e) and e[0]["katex"] >= 2 and e[0]["raw"] == 0,
            str(e),
        )
    check("no widget crashed", not got["errors"], "; ".join(got["errors"])[:200])


async def run(port: int) -> list:
    tabs = json.load(urllib.request.urlopen(f"http://127.0.0.1:{port}/json"))
    async with websockets.connect(tabs[0]["webSocketDebuggerUrl"], max_size=None) as ws:
        cdp = Cdp(ws)
        await cdp.js(JS)
        results: list = []
        for name, (md, opts) in CASES.items():
            text = f"caret\n\n{md}\n\nend"  # the caret on the first line reveals nothing
            await cdp.js(f"qa.set({json.dumps(text)}, 0)")
            await asyncio.sleep(2.0 if "mermaid" in md or "![[" in md else 0.7)
            got = await cdp.js("qa.report()")
            compare(name, text, got, opts, results)
        for name, (template, html, plain, (n_tables, n_rows, n_tex)) in PASTES.items():
            caret = template.index("‸")
            note = template.replace("‸", "")
            await cdp.js(f"qa.set({json.dumps(note)}, {caret})")
            await asyncio.sleep(0.4)
            await cdp.js(f"qa.paste({json.dumps(html)}, {json.dumps(plain)})")
            await asyncio.sleep(1.5)
            text = await cdp.js("qa.text()")
            await cdp.js(
                f"qa.view().dispatch({{selection: {{anchor: {len(str(text))}}}}})"
            )  # caret away
            await asyncio.sleep(0.6)
            got = await cdp.js("qa.report()")
            want = expected(str(text))
            rows = want["tables"][0]["rows"] if want["tables"] else 0
            ok = (len(want["tables"]), rows, len(want["tex"])) == (n_tables, n_rows, n_tex)
            results.append(
                (
                    name,
                    "pasted note reads as intended",
                    ok,
                    f"tables/rows/formulas {(len(want['tables']), rows, len(want['tex']))}, want {(n_tables, n_rows, n_tex)}: {text!r}"[
                        :300
                    ],
                )
            )
            compare(name, str(text), got, {"dollars": "$HOME" in str(text)}, results)
        await cell_checks(cdp, results)
        await select_checks(cdp, results)
        await align_checks(cdp, results)
        await theme_checks(cdp, results)
        return results


def main() -> int:
    keep = "--keep" in sys.argv
    work = Path(tempfile.mkdtemp(prefix="pp-qa-render-"))
    vault = work / "vault"
    (vault / ".paper-pile").mkdir(parents=True)
    (vault / "qa.md").write_text("start\n")
    (vault / "mathnote.md").write_text("# Math\n\nInline $a^2$ and\n\n$$\n\\frac{1}{2}\n$$\n")
    (vault / ".paper-pile" / "session.json").write_text(
        json.dumps({"tabs": ["qa.md"], "active": "qa.md"})
    )
    save_grant(vault, Grant("2026-10-30T12:00"), work / "xdg" / "paper-pile")
    global LOG
    LOG = work / "app.log"
    env = {
        **os.environ,
        "PAPER_PILE_FAKE_AI": "1",  # the AI on (Ask box) with the app's scripted backend
        "QT_QPA_PLATFORM": "offscreen",
        "XDG_CONFIG_HOME": str(work / "xdg"),
        "XDG_STATE_HOME": str(work / "state"),  # or the user's "last vault" points here
        "XDG_CACHE_HOME": str(work / "cache"),
        "QTWEBENGINE_CHROMIUM_FLAGS": f"--remote-debugging-port={PORT}",
    }
    app = subprocess.Popen(
        ["uv", "run", "paper-pile", "--ai", "--debug", str(vault)],
        cwd=REPO,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=LOG.open("w"),
        start_new_session=True,
    )
    try:
        for _ in range(60):
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{PORT}/json", timeout=1)
                break
            except OSError:
                time.sleep(1)
        time.sleep(8)
        results = asyncio.run(run(PORT))
    finally:
        os.killpg(app.pid, 15)
        if not keep:
            shutil.rmtree(work, ignore_errors=True)
    failed = [r for r in results if r[2] is False]
    known = [r for r in results if r[2] is None]
    for name, check, ok, detail in results:
        if ok and "--all" not in sys.argv:
            continue
        mark = "PASS" if ok else ("KNOWN" if ok is None else "FAIL")
        print(f"{mark:5} {name:42} {check:32} {'' if ok else detail}")
    print(
        f"\n{len(results) - len(failed) - len(known)} passed, {len(failed)} failed, {len(known)} known"
    )
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
