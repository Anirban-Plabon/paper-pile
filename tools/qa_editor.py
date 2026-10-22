# ruff: noqa: E501  (embedded JavaScript)
"""Editor QA: where can the caret go around block widgets? (dev tool, not part of the app)

Launches the native app offscreen on a throwaway vault, drives the real editor over CDP and prints
one line per check. Usage:  uv run python tools/qa_editor.py [--keep]

Each scenario puts a note text into the editor, then:
  * walks the caret down from the first line and up from the last with the arrow keys and
    records which lines it can stand on;
  * clicks below the end of the note and types, to see where text lands;
  * types at the very start of the note (Ctrl+Home).
"""

import asyncio
import base64
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

import websockets

REPO = Path(__file__).resolve().parent.parent
PORT = int(os.environ.get("QA_PORT", "9339"))
PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d4948445200000001000000010806000000"
    "1f15c4890000000d49444154789c6360f8cf00000301010018dd8db00000000049454e44ae426082"
)

BLOCKS = {
    "table": "| a | b |\n| --- | --- |\n| 1 | 2 |",
    "image": "![pic](.qa.assets/p.png)",
    "embed": "![[other]]",
    "math": "$$\nx^2\n$$",
    "mermaid": "```mermaid\ngraph TD\nA-->B\n```",
    "code": "```python\nx = 1\n```",
    "callout": "> **Note:** hello",
    "quote": "> quoted",
    "divider": "---",
    "h1": "# Heading",
    "todo": "- [ ] task",
    "pagebreak": "---/",
    "pagebreak (html)": '<div style="page-break-after: always;"></div>',
}

JS_HELPERS = r"""
window.qa = {
  view() { const c = document.querySelector('.pp-split .cm-content'); return c.cmTile?.root?.view ?? c.cmView.view; },
  set(text) { const v = qa.view(); v.dispatch({changes: {from: 0, to: v.state.doc.length, insert: text}, selection: {anchor: 0}}); v.focus(); return v.state.doc.length; },
  line() { const v = qa.view(); return v.state.doc.lineAt(v.state.selection.main.head).number; },
  text() { return qa.view().state.doc.toString(); },
  lines() { return qa.view().state.doc.lines; },
  bottom() { const v = qa.view(); const s = document.querySelector('.pp-split .cm-scroller').getBoundingClientRect(); const r = document.querySelector('.pp-split .cm-content').getBoundingClientRect(); const lastBottom = v.documentTop + v.lineBlockAt(v.state.doc.length).bottom; return [Math.round(r.left + 60), Math.round(Math.min(lastBottom + 40, s.bottom - 25))]; },
};
'ok'
"""


class Cdp:
    def __init__(self, ws: websockets.ClientConnection) -> None:
        self.ws, self.n = ws, 0

    async def call(self, method: str, **params: object) -> dict:
        self.n += 1
        await self.ws.send(json.dumps({"id": self.n, "method": method, "params": params}))
        while True:
            r = json.loads(await self.ws.recv())
            if r.get("id") == self.n:
                return r.get("result", {})

    async def js(self, expr: str) -> object:
        r = await self.call(
            "Runtime.evaluate", expression=expr, awaitPromise=True, returnByValue=True
        )
        return r.get("result", {}).get("value")

    async def key(self, key: str, code: int, ctrl: bool = False) -> None:
        for t in ("rawKeyDown", "keyUp"):
            await self.call(
                "Input.dispatchKeyEvent",
                type=t,
                key=key,
                windowsVirtualKeyCode=code,
                modifiers=2 if ctrl else 0,
            )
        await asyncio.sleep(0.05)

    async def type(self, text: str) -> None:
        await self.call("Input.insertText", text=text)
        await asyncio.sleep(0.15)

    async def click(self, x: float, y: float) -> None:
        for t in ("mousePressed", "mouseReleased"):
            await self.call(
                "Input.dispatchMouseEvent", type=t, x=x, y=y, button="left", clickCount=1
            )
        await asyncio.sleep(0.25)


async def walk(cdp: Cdp, direction: str, steps: int) -> list[int]:
    seen = [await cdp.js("qa.line()")]
    for _ in range(steps):
        await cdp.key(direction, 40 if direction == "ArrowDown" else 38)
        await asyncio.sleep(0.08)
        seen.append(await cdp.js("qa.line()"))
    return seen


def own_line(text: str, marker: str) -> bool:
    return any(line.strip() == marker for line in text.split("\n"))


async def scenario(
    cdp: Cdp, name: str, text: str, results: list[tuple[str, str, bool, str]]
) -> None:
    await cdp.js(f"qa.set({json.dumps(text)})")
    await asyncio.sleep(0.6)
    await asyncio.sleep(1.0 if "![[" in text or "mermaid" in text else 0)  # late-drawn blocks
    n = await cdp.js("qa.lines()")
    drift = await cdp.js(
        "(() => { const v = qa.view(); let worst = 0;"
        " for (const el of document.querySelectorAll('.pp-split .cm-content > :not(.cm-line)')) {"
        "   const r = el.getBoundingClientRect(); if (!r.height) continue;"
        "   const b = v.lineBlockAt(v.posAtDOM(el)); const top = v.documentTop + b.top, bottom = v.documentTop + b.bottom;"
        "   worst = Math.max(worst, top - r.top, r.bottom - bottom); }"
        " return Math.round(worst); })()"
    )
    results.append(
        (name, "drawn blocks fit the space the editor gave them", drift <= 2, f"{drift}px over")
    )
    lines = text.split("\n")
    blank = [i + 1 for i, line in enumerate(lines) if not line.strip()]
    down = await walk(cdp, "ArrowDown", n + 2)
    up = await walk(cdp, "ArrowUp", n + 2)
    reached = set(down) | set(up)
    results.append(
        (
            name,
            "arrows reach every blank line",
            all(b in reached for b in blank),
            f"blank={blank} down={down} up={up}",
        )
    )
    results.append(
        (name, "arrows reach first and last line", 1 in reached and n in reached, f"lines={n}")
    )
    # click below the end of the note, then type
    await cdp.js(f"qa.set({json.dumps(text)})")
    await asyncio.sleep(1.5 if "![[" in text else 0.5)
    await cdp.js(
        "(() => { const s = document.querySelector('.pp-split .cm-scroller'); s.scrollTop = s.scrollHeight; })()"
    )
    await asyncio.sleep(1.5 if "![[" in text else 0.4)  # embeds load (and grow) a moment later
    x, y = await cdp.js("qa.bottom()")
    await cdp.click(x, y)
    await cdp.type("ZEND")
    await asyncio.sleep(0.4)
    after = await cdp.js("qa.text()")
    ends_with_block = not re.fullmatch(r"[a-z ]+", lines[-1])  # a plain word ends it: text
    ok = own_line(after, "ZEND") if ends_with_block else after.rstrip().endswith("ZEND")
    ok = ok and after.rstrip().endswith("ZEND") and after.startswith(text.rstrip("\n"))
    results.append((name, "click below the end, type: lands after it", ok, repr(after[-70:])))
    # a new line above the first block: Ctrl+Home, Enter, ArrowUp, type
    await cdp.js(f"qa.set({json.dumps(text)})")
    await asyncio.sleep(0.5)
    await cdp.key("Home", 36, ctrl=True)
    await cdp.key("Enter", 13)
    await cdp.key("ArrowUp", 38)
    await cdp.type("ZTOP")
    await asyncio.sleep(0.4)
    after = await cdp.js("qa.text()")
    ok = after.startswith("ZTOP\n") and text in after
    results.append((name, "line above the first block", ok, repr(after[:70])))


async def run(port: int) -> list[tuple[str, str, bool, str]]:
    tabs = json.load(urllib.request.urlopen(f"http://127.0.0.1:{port}/json"))
    async with websockets.connect(tabs[0]["webSocketDebuggerUrl"], max_size=None) as ws:
        cdp = Cdp(ws)
        await cdp.js(JS_HELPERS)
        results: list[tuple[str, str, bool, str]] = []
        await scenario(cdp, "warm-up", "top\n\nbottom", [])
        for kind, block in BLOCKS.items():
            await scenario(cdp, f"{kind}: between text", f"top\n\n{block}\n\nbottom", results)
            await scenario(cdp, f"{kind}: whole note", block, results)
            await scenario(cdp, f"{kind}: at the end", f"top\n\n{block}", results)
            await scenario(cdp, f"{kind}: at the start", f"{block}\n\nbottom", results)
            await scenario(
                cdp,
                f"{kind}: next to a table",
                f"top\n\n{block}\n{BLOCKS['table']}\n\nbottom",
                results,
            )
        props = "---\ntitle: x\ntags: [one, two]\n---"
        await scenario(
            cdp, "properties: then text", f"{props}\nnext line\n\n{BLOCKS['table']}", results
        )
        await scenario(
            cdp, "properties: then a table", f"{props}\n{BLOCKS['table']}\n\nend", results
        )
        await slash_checks(cdp, results)
        await leave_checks(cdp, results)
        await lazy_checks(cdp, results)
        await page_break_checks(cdp, results)
        return results


SLASH = {  # command -> text that must sit between empty lines afterwards
    "table": "| Column 1",
    "code": "```",
    "math": "$$",
    "callout": "> **Note:**",
    "h1": "# ",
    "quote": "> ",
    "flowchart": "```mermaid",
    "divider": "---",
    "pagebreak": "---/",
}


async def slash_checks(cdp: Cdp, results: list[tuple[str, str, bool, str]]) -> None:
    """Type `/command` + Enter between two text lines: the block must get empty lines around it."""
    for cid, start in SLASH.items():
        await cdp.js('qa.set("above\\nX\\nbelow")')
        await asyncio.sleep(0.4)
        await cdp.js(
            "(() => { const v = qa.view(); v.dispatch({changes: {from: 6, to: 7, insert: ''}, selection: {anchor: 6}}); v.focus(); })()"
        )
        await cdp.type("/")
        await asyncio.sleep(0.3)
        await cdp.type(cid)
        await asyncio.sleep(0.9)
        await cdp.key("Enter", 13)
        await asyncio.sleep(1.2)
        text = await cdp.js("qa.text()")
        lines = text.split("\n")
        idx = next((i for i, line in enumerate(lines) if line.startswith(start)), -1)
        end = idx
        while end + 1 < len(lines) and lines[end + 1].strip() and cid not in {"h1"}:
            end += 1
        ok = idx > 1 and lines[idx - 1] == "" and end + 1 < len(lines) and lines[end + 1] == ""
        results.append((f"/{cid}", "inserted with empty lines around", ok, repr(text[:120])))
    await cdp.js('qa.set("x\\n\\n> **Warning:** careful\\n> second line\\n\\ny")')
    await asyncio.sleep(0.6)
    shape = await cdp.js("""(() => { const ls = [...document.querySelectorAll('.cm-line.pp-callout')];
      return ls.map(l => [l.classList.contains('pp-callout-first'), l.classList.contains('pp-callout-last'), getComputedStyle(l).borderTopLeftRadius, getComputedStyle(l, '::before').width]); })()""")
    ok = (
        bool(shape)
        and shape[0][0]
        and shape[-1][1]
        and shape[0][2] not in ("0px", "")
        and shape[0][3] == "4px"
    )
    results.append(("callout", "card with rounded ends and a stick", ok, repr(shape)))


LEAVE = {  # a block's last line -> what Enter, Enter, typing "after" must give
    "quote": ("> one", "> one\n\nafter"),
    "callout": ("> **Note:** one", "> **Note:** one\n\nafter"),
    "bullet": ("- one", "- one\n\nafter"),
    "todo": ("- [ ] one", "- [ ] one\n\nafter"),
    "numbered": ("1. one", "1. one\n\nafter"),
    "nested quote": ("> > one", "> > one\n\nafter"),  # three Enters: one level per Enter
}


async def leave_checks(cdp: Cdp, results: list[tuple[str, str, bool, str]]) -> None:
    """Leaving a list / quote with Enter on its empty line must close it with an empty line, so
    the next text is not a markdown "lazy" line that still belongs to the block."""
    for name, (start, want) in LEAVE.items():
        await cdp.js(f"qa.set({json.dumps(start)})")
        await asyncio.sleep(0.4)
        await cdp.js(
            "(() => { const v = qa.view(); v.dispatch({selection: {anchor: v.state.doc.length}}); v.focus(); })()"
        )
        await cdp.key("Enter", 13)
        await cdp.key("Enter", 13)
        if name == "nested quote":
            await cdp.key("Enter", 13)
        await cdp.type("after")
        await asyncio.sleep(0.4)
        text = await cdp.js("qa.text()")
        results.append(
            (
                f"leave {name}",
                "Enter twice closes it with an empty line",
                text.rstrip("\n") == want,
                repr(text),
            )
        )


LAZY_JS = """(() => {
  const lines = [...document.querySelectorAll('.pp-editor .cm-line')];
  const at = (t) => lines.find((l) => l.textContent.trim().endsWith(t));
  const left = (t) => {
    const l = at(t); if (!l) return -1;
    const w = document.createTreeWalker(l, NodeFilter.SHOW_TEXT);
    for (let n = w.nextNode(); n; n = w.nextNode()) {
      const i = n.data.indexOf(t);
      if (i >= 0) { const r = document.createRange(); r.setStart(n, i); r.setEnd(n, i + 1); return r.getBoundingClientRect().left; }
    }
    return -1;
  };
  return {
    calloutLazy: at('lazy1')?.className ?? '',
    quoteLazy: at('lazy2')?.className ?? '',
    itemText: left('item'), itemLazy: left('lazy3'),
  };
})()"""


async def lazy_checks(cdp: Cdp, results: list[tuple[str, str, bool, str]]) -> None:
    """A line written without `>` / indentation right under a quote or a list item belongs to it
    in markdown; Live Preview must draw it inside the callout / quote / item, not outside."""
    note = "> **Note:** head\nlazy1\n> tail\n\npara\n\n> q\nlazy2\n\n- item\nlazy3\n\nend"
    await cdp.js(f"qa.set({json.dumps(note)})")
    await asyncio.sleep(0.4)
    await cdp.js(
        "(() => { const v = qa.view(); v.dispatch({selection: {anchor: v.state.doc.length}}); })()"
    )
    await asyncio.sleep(0.6)
    r = await cdp.js(LAZY_JS)
    if not isinstance(r, dict):
        results.append(("lazy lines", "measured", False, repr(r)))
        return
    results.append(
        (
            "lazy line in a callout",
            "drawn inside the card",
            "pp-callout" in r["calloutLazy"] and "pp-quote" in r["calloutLazy"],
            repr(r),
        )
    )
    results.append(
        ("lazy line in a quote", "drawn with the quote bar", "pp-quote" in r["quoteLazy"], repr(r))
    )
    results.append(
        (
            "lazy line in a list item",
            "lines up with the item text",
            r["itemText"] > 0 and abs(r["itemText"] - r["itemLazy"]) < 2,
            repr(r),
        )
    )


PAGE_BREAK_JS = """(() => {
  const w = document.querySelector('.pp-split .pp-page-break-line');
  const raw = document.querySelector('.pp-split .cm-line.pp-page-break-raw');
  const lum = (c) => { const v = c.match(/[\\d.]+/g).slice(0, 3).map((x) => { x /= 255; return x <= 0.03928 ? x / 12.92 : ((x + 0.055) / 1.055) ** 2.4; }); return 0.2126 * v[0] + 0.7152 * v[1] + 0.0722 * v[2]; };
  let bg = 'rgba(0, 0, 0, 0)';
  for (let e = w; e && /rgba\\(0, 0, 0, 0\\)|transparent/.test(bg); e = e.parentElement) bg = getComputedStyle(e).backgroundColor;
  const fg = w ? getComputedStyle(w).color : null;
  const [a, b] = w ? [lum(fg), lum(bg)] : [0, 0];
  return { widget: !!w, label: w?.textContent ?? '', raw: !!raw, height: w ? Math.round(w.getBoundingClientRect().height) : 0,
           contrast: w ? Math.round(((Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05)) * 10) / 10 : 0 };
})()"""


async def page_break_checks(cdp: Cdp, results: list[tuple[str, str, bool, str]]) -> None:
    """A page break is drawn as a labelled line in both themes and is raw on the caret's line;
    typing right under it turns it back into text (it needs an empty line below)."""
    note = "top\n\n---/\n\nbottom"
    shots = os.environ.get("QA_SHOTS")
    for theme in ("light", "dark"):
        await cdp.js(
            f"document.body.classList.toggle('body--dark', {json.dumps(theme == 'dark')});"
            f"document.body.classList.toggle('body--light', {json.dumps(theme == 'light')}); 1"
        )
        await cdp.js(f"qa.set({json.dumps(note)})")
        await asyncio.sleep(0.6)
        r = await cdp.js(PAGE_BREAK_JS)
        ok = r["widget"] and r["label"] == "Page break" and not r["raw"] and r["contrast"] >= 3
        results.append(("page break", f"drawn line ({theme})", ok, repr(r)))
        if shots:
            shot = await cdp.call("Page.captureScreenshot", format="png")
            Path(shots, f"pagebreak-{theme}.png").write_bytes(base64.b64decode(shot["data"]))
    await cdp.js(
        "document.body.classList.toggle('body--dark', false); document.body.classList.toggle('body--light', true); 1"
    )
    await cdp.js("(() => { const v = qa.view(); v.dispatch({selection: {anchor: 6}}); })()")
    await asyncio.sleep(0.5)
    r = await cdp.js(PAGE_BREAK_JS)
    results.append(("page break", "raw on the caret line", not r["widget"] and r["raw"], repr(r)))
    await cdp.js(f"qa.set({json.dumps(note)})")
    await asyncio.sleep(0.3)
    await cdp.js(
        "(() => { const v = qa.view(); const at = v.state.doc.line(4).from; v.dispatch({selection: {anchor: at}}); v.focus(); })()"
    )
    await cdp.type("x")
    await asyncio.sleep(0.6)
    r = await cdp.js(PAGE_BREAK_JS)
    results.append(
        ("page break", "text right under it: no longer a break", not r["widget"], repr(r))
    )


def main() -> int:
    keep = "--keep" in sys.argv
    work = Path(tempfile.mkdtemp(prefix="pp-qa-"))
    vault = work / "vault"
    (vault / ".qa.assets").mkdir(parents=True)
    (vault / ".qa.assets" / "p.png").write_bytes(PNG)
    (vault / "qa.md").write_text("start\n")
    (vault / "other.md").write_text("# Other\n\nembedded text\n")
    (vault / ".paper-pile").mkdir()
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
    failed = [r for r in results if not r[2]]
    for name, check, ok, detail in results:
        if ok and "--all" not in sys.argv:
            continue
        print(f"{'PASS' if ok else 'FAIL'}  {name:32} {check:46} {'' if ok else detail}")
    print(f"\n{len(results) - len(failed)} passed, {len(failed)} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
