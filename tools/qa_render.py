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
from paper_pile.core.parser import math_spans, parse  # noqa: E402

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
    env = {
        **os.environ,
        "QT_QPA_PLATFORM": "offscreen",
        "XDG_CONFIG_HOME": str(work / "xdg"),
        "XDG_STATE_HOME": str(work / "state"),  # or the user's "last vault" points here
        "XDG_CACHE_HOME": str(work / "cache"),
        "QTWEBENGINE_CHROMIUM_FLAGS": f"--remote-debugging-port={PORT}",
    }
    app = subprocess.Popen(
        ["uv", "run", "paper-pile", str(vault)],
        cwd=REPO,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
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
