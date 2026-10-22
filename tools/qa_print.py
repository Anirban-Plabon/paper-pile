# ruff: noqa: E501  (embedded JavaScript)
"""Print QA (PLAN §4.17): page view, the print layout and the PDF, in the real app (dev tool).

Launches the native app offscreen on a throwaway vault, drives it over CDP and prints one line per
check. Usage:  uv run python tools/qa_print.py [--keep] [--all]

* page view is turned on from the ⋯ menu (real mouse clicks) and off again;
* for each fixture note: no sheet overflows, the layout rules hold (manual breaks, headings kept
  with what follows, 2 lines on each side of a cut paragraph, code/table cuts on line/row
  boundaries, pictures fit), and the editor's page lines sit on the lines where pages start;
* the PDF: the print page is saved by the same Qt code the native export uses (``--pdf`` mode
  runs it in its own process) and each PDF page's text is compared with the sheet's;
* the properties block is hidden and the caret / Backspace cannot get into it;
* switching the paper to Letter in Settings lays the note out again;
* typing stays fast in a 1000-line note with page view on.
"""

import asyncio
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

sys.path.insert(0, str(Path(__file__).resolve().parent))
from qa_editor import REPO, Cdp  # noqa: E402

PORT = int(os.environ.get("QA_PRINT_PORT", "9341"))
BREAK = '<div style="page-break-after: always;"></div>'


def words(n: int, start: int = 0) -> str:
    return " ".join(f"w{i}" for i in range(start, start + n))


def para(lines: int, tag: str, width: int = 12) -> str:
    return "\n".join(f"{tag}{i} " + words(width) for i in range(lines))


FIXTURES = {
    "long paragraphs": "\n\n".join(para(9, f"p{k}l") for k in range(14)),
    "manual breaks": f"# One\n\nfirst page\n\n---/\n\nsecond page starts here\n\n{BREAK}\n\n---/\n\nthird page\n",
    "heading at the bottom": "\n\n".join(para(1, f"s{k}x", 30) for k in range(20))
    + "\n\n## Kept with its text\n\n"
    + para(6, "after"),
    "tall code": "intro\n\n```python\n"
    + "\n".join(f"line_{i} = {i}" for i in range(140))
    + "\n```\n\noutro\n",
    "long table": "| n | name |\n| --- | --- |\n"
    + "\n".join(f"| {i} | row{i} |" for i in range(110))
    + "\n\nafter table\n",
    "tall image": "above\n\n![tall](.qa.assets/tall.png)\n\nbelow\n",
    "math and diagram": "# Maths\n\n$$\n\\int_0^1 x^2\\,dx = \\frac{1}{3}\n$$\n\n```mermaid\ngraph TD\nA-->B\nB-->C\n```\n\n"
    + para(40, "m"),
    "lists": "\n".join(f"- item{i} " + words(10) for i in range(60))
    + "\n\n"
    + "\n".join(f"{i + 1}. num{i} " + words(10) for i in range(40)),
    "properties": "---\ntitle: Secret title\ntags: [a]\n---\n# Visible\n\n" + para(60, "fm"),
}

JS = r"""
window.qp = {
  view() { const c = document.querySelector('.pp-split .cm-content'); return c.cmTile?.root?.view ?? c.cmView.view; },
  set(text) { const v = qp.view(); v.dispatch({changes: {from: 0, to: v.state.doc.length, insert: text}, selection: {anchor: 0}}); v.focus(); return v.state.doc.length; },
  frame() { return document.querySelector('.pp-print-frame'); },
  src() { return qp.frame()?.src ?? ''; },
  result() { try { return qp.frame()?.contentWindow?.ppPrint ?? null; } catch (e) { return null; } },
  // page lines are only drawn near the screen: scroll through the note and collect them
  async lines() {
    const v = qp.view(); const s = v.scrollDOM; const found = new Set();
    for (let y = 0; ; y += s.clientHeight / 2) {
      s.scrollTop = y; await new Promise((r) => setTimeout(r, 60)); v.requestMeasure(); await new Promise((r) => setTimeout(r, 60));
      for (const w of v.dom.querySelectorAll('.pp-page-line')) found.add(v.state.doc.lineAt(v.posAtDOM(w)).number);
      if (y >= s.scrollHeight) break;
    }
    s.scrollTop = 0;
    return [...found].sort((a, b) => a - b);
  },
  overflow() {
    const d = qp.frame().contentDocument; const out = [];
    d.querySelectorAll('.pp-sheet-body').forEach((b, i) => {
      const r = b.getBoundingClientRect();
      let worst = 0;
      for (const el of b.querySelectorAll('*')) worst = Math.max(worst, el.getBoundingClientRect().bottom - r.bottom);
      if (worst > 1) out.push([i + 1, Math.round(worst)]);
    });
    return out;
  },
  sheets() {
    const d = qp.frame().contentDocument;
    return [...d.querySelectorAll('.pp-sheet-body')].map((b) => ({
      first: b.firstElementChild?.tagName ?? '', last: b.lastElementChild?.tagName ?? '',
      tags: [...b.children].map((c) => c.tagName + (c.className ? '.' + c.className.split(' ')[0] : '')),
      text: (() => { const c = b.cloneNode(true); c.querySelectorAll('.katex, .pp-diagram, .math').forEach((m) => m.remove()); d.body.appendChild(c); const t = c.innerText; c.remove(); return t; })(),
      head: b.firstElementChild && !b.firstElementChild.matches('.math, .pp-diagram') ? b.firstElementChild.innerText : '',
      height: Math.round(b.getBoundingClientRect().height), sheet: Math.round(b.parentElement.getBoundingClientRect().height),
      pics: [...b.querySelectorAll('img, svg')].map((p) => Math.round(p.getBoundingClientRect().bottom - b.getBoundingClientRect().bottom)),
    }));
  },
  caret() { const v = qp.view(); return v.state.selection.main.head; },
};
'ok'
"""


async def wait_layout(cdp: Cdp, before: str, timeout: float = 30) -> dict | None:
    """Wait until page view has laid out the editor's text again (a new print page, done)."""
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        await asyncio.sleep(0.3)
        if await cdp.js("qp.src()") == before:
            continue
        result = await cdp.js("qp.result()")
        if result and result.get("done"):
            await asyncio.sleep(0.3)  # the editor applies it right after
            return result
    return None


async def click_text(cdp: Cdp, selector: str, text: str) -> bool:
    """A real mouse click on the element matching ``selector`` whose text contains ``text``."""
    pos = await cdp.js(
        f"(() => {{ const el = [...document.querySelectorAll({json.dumps(selector)})].find((e) => e.offsetParent && e.textContent.includes({json.dumps(text)})); if (!el) return null;"
        " const r = el.getBoundingClientRect(); return [r.left + r.width / 2, r.top + r.height / 2]; })()"
    )
    if not pos:
        return False
    await cdp.click(*pos)
    return True


async def open_menu_and_click(cdp: Cdp, label: str) -> bool:
    pos = await cdp.js(
        "(() => { const b = [...document.querySelectorAll('button')].find((e) => e.offsetParent && e.getAttribute('data-tip') === 'More options'); if (!b) return null;"
        " const r = b.getBoundingClientRect(); return [r.left + r.width / 2, r.top + r.height / 2]; })()"
    )
    if not pos:
        return False
    await cdp.click(*pos)
    await asyncio.sleep(0.6)
    ok = await click_text(cdp, ".pp-note-menu-item", label)
    await asyncio.sleep(0.6)
    return ok


def pdf_pages(url: str, out: Path, paper: str) -> list[str] | str:
    """Save ``url`` as a PDF with the native export's Qt code (own process); its pages' text."""
    r = subprocess.run(
        [sys.executable, __file__, "--pdf", url, str(out), paper],
        capture_output=True,
        text=True,
        timeout=150,
        env={**os.environ, "QT_QPA_PLATFORM": "offscreen", "QTWEBENGINE_DISABLE_SANDBOX": "1"},
    )
    try:
        return json.loads(r.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return f"pdf failed: {r.stdout[-400:]} {r.stderr[-800:]}"


def norm(text: str) -> str:
    """Letters and digits only: a PDF's text comes back with its own spacing (a monospace font is
    read glyph by glyph)."""
    return re.sub(r"[^A-Za-z0-9]", "", text)


def check_pdf(
    name: str, url: str, sheets: list[dict], work: Path, paper: str, results: list
) -> None:
    got = pdf_pages(url, work / f"{re.sub(r'\W+', '_', name)}.pdf", paper)
    if isinstance(got, str):
        results.append((name, "PDF saved", False, got))
        return
    results.append(
        (
            name,
            "PDF has the sheets' page count",
            len(got) == len(sheets),
            f"pdf={len(got)} sheets={len(sheets)}",
        )
    )
    bad = []
    for i, (page, sheet) in enumerate(zip(got, sheets, strict=False)):
        want, have = norm(sheet["text"]), norm(page)
        if not want:
            continue
        head, tail = norm(sheet["head"])[:16], want[-16:]
        if head not in have or tail not in have:
            bad.append((i + 1, head, tail, have[:24], have[-24:]))
    results.append((name, "each PDF page starts and ends like its sheet", not bad, repr(bad[:2])))


def expectations(
    name: str, text: str, result: dict, sheets: list[dict]
) -> list[tuple[str, bool, str]]:
    pages = result["pages"]
    starts = [p["line"] for p in pages[1:]]
    lines = text.split("\n")
    out: list[tuple[str, bool, str]] = []
    if name == "manual breaks":
        second = lines.index("second page starts here") + 1
        third = lines.index("third page") + 1
        out.append(
            (
                "pages start after each break (a run of breaks counts once)",
                starts == [second, third],
                repr(starts),
            )
        )
    if name == "long paragraphs":
        bad = []
        for s in starts:
            line = lines[s - 1]
            m = re.match(r"p(\d+)l(\d+) ", line)
            if m and int(m.group(2)) not in (0,) and not (2 <= int(m.group(2)) <= 7):
                bad.append(line[:8])
        out.append(
            ("a cut paragraph keeps 2 lines on each side", not bad and len(pages) > 1, repr(bad))
        )
    if name == "heading at the bottom":
        out.append(
            (
                "no sheet ends with a heading",
                all(s["last"] not in {"H1", "H2", "H3"} for s in sheets[:-1]),
                repr([s["last"] for s in sheets]),
            )
        )
    if name == "tall code":
        ok = len(pages) > 1 and all(
            re.match(r"line_\d+ = \d+$", lines[s - 1])
            for s in starts
            if lines[s - 1].startswith("line_")
        )
        out.append(("code is cut between code lines", ok, repr(starts)))
        out.append(
            (
                "the code continues on the next sheet",
                any(t.startswith("PRE") for t in sheets[1]["tags"][:1]),
                repr(sheets[1]["tags"][:3]),
            )
        )
    if name == "long table":
        ok = len(pages) > 1 and all(
            re.match(r"\| \d+ \| row\d+ \|$", lines[s - 1])
            for s in starts
            if lines[s - 1].startswith("|")
        )
        out.append(("tables are cut between rows", ok, repr(starts)))
        out.append(
            (
                "the header repeats on the next sheet",
                "n\tname" in sheets[1]["text"] or "n name" in sheets[1]["text"].replace("\t", " "),
                sheets[1]["text"][:40],
            )
        )
    if name == "tall image":
        out.append(
            (
                "the picture fits its sheet",
                all(b <= 1 for s in sheets for b in s["pics"]),
                repr([s["pics"] for s in sheets]),
            )
        )
    if name == "math and diagram":
        out.append(
            (
                "math and the diagram are drawn",
                "SVG" in json.dumps([s["tags"] for s in sheets])
                or any("pp-diagram" in t for s in sheets for t in s["tags"]),
                repr(sheets[0]["tags"][:5]),
            )
        )
    if name == "properties":
        out.append(
            (
                "the properties are not printed",
                "Secret" not in sheets[0]["text"],
                sheets[0]["text"][:40],
            )
        )
    return out


async def run(port: int, work: Path, results: list[tuple[str, str, bool, str]]) -> None:
    tabs = json.load(urllib.request.urlopen(f"http://127.0.0.1:{port}/json"))
    page = next(t for t in tabs if t.get("type") == "page")
    origin = re.match(r"https?://[^/]+", page["url"]).group(0)
    async with websockets.connect(page["webSocketDebuggerUrl"], max_size=None) as ws:
        cdp = Cdp(ws)
        await cdp.js(JS)
        await cdp.js("qp.set('warm up')")
        await asyncio.sleep(1)
        # a wide window and folded side panes: room for a whole sheet of paper
        await cdp.call(
            "Emulation.setDeviceMetricsOverride",
            width=1400,
            height=900,
            deviceScaleFactor=1,
            mobile=False,
        )
        await cdp.key("b", 66, ctrl=True)
        await cdp.key("l", 76, ctrl=True)
        await asyncio.sleep(1)

        # page view on, from the ⋯ menu
        ok = await open_menu_and_click(cdp, "Page view")
        await asyncio.sleep(1)
        on = await cdp.js("!!document.querySelector('.pp-split .cm-editor.pp-page-view')")
        results.append(
            ("page view", "turned on from the ⋯ menu", ok and on, f"clicked={ok} on={on}")
        )
        cfg = (
            (work / "xdg" / "paper-pile" / "config.toml").read_text()
            if (work / "xdg" / "paper-pile" / "config.toml").exists()
            else ""
        )
        results.append(
            ("page view", "remembered in the settings", 'page_view = "lines"' in cfg, cfg[-120:])
        )
        width = await cdp.js(
            "(() => { const c = document.querySelector('.pp-split .cm-content'); const s = getComputedStyle(c); return [c.getBoundingClientRect().width - parseFloat(s.paddingLeft) - parseFloat(s.paddingRight), 170 * 96 / 25.4 + 8]; })()"
        )
        results.append(
            (
                "page view",
                "text column = A4 text width",
                abs(width[0] - width[1]) < 1.5,
                repr(width),
            )
        )

        for name, text in FIXTURES.items():
            before = await cdp.js("qp.src()")
            await cdp.js(f"qp.set({json.dumps(text)})")
            result = await wait_layout(cdp, before)
            if not result or result.get("error"):
                results.append((name, "laid out", False, repr(result)[:300]))
                continue
            sheets = await cdp.js("qp.sheets()")
            over = await cdp.js("qp.overflow()")
            results.append((name, "no sheet overflows", not over, repr(over)))
            editor_lines = await cdp.js("qp.lines()")
            want = [p["line"] for p in result["pages"][1:]]
            if name == "long table":  # inside the table widget a page line cannot be drawn
                want = [w for w in want if not text.split("\n")[w - 1].startswith("|")]
                editor_lines = [
                    e for e in editor_lines if not text.split("\n")[e - 1].startswith("|")
                ]
            results.append(
                (
                    name,
                    "page lines sit where the pages start",
                    editor_lines == want,
                    f"editor={editor_lines} pages={want}",
                )
            )
            for check, ok, detail in expectations(name, text, result, sheets):
                results.append((name, check, ok, detail))
            src = await cdp.js("qp.src()")
            check_pdf(
                name, src if src.startswith("http") else origin + src, sheets, work, "A4", results
            )

        # the properties block: hidden, and the caret / Backspace cannot get in
        text = FIXTURES["properties"]
        body = text.index("# Visible")
        await cdp.js(f"qp.set({json.dumps(text)})")
        await asyncio.sleep(0.8)
        hidden = await cdp.js(
            "!document.querySelector('.pp-split .pp-frontmatter') && ![...document.querySelectorAll('.pp-split .cm-line')].some((l) => l.textContent.includes('Secret'))"
        )
        results.append(("properties", "hidden in page view", hidden, ""))
        await cdp.key("Home", 36, ctrl=True)
        await cdp.key("ArrowUp", 38)
        caret = await cdp.js("qp.caret()")
        results.append(
            (
                "properties",
                "the caret cannot enter them",
                caret >= body,
                f"caret={caret} body={body}",
            )
        )
        await cdp.js(
            f"(() => {{ const v = qp.view(); v.dispatch({{selection: {{anchor: {body}}}}}); v.focus(); }})()"
        )
        await cdp.key("Backspace", 8)
        await asyncio.sleep(0.3)
        after = await cdp.js("qp.view().state.doc.toString()")
        results.append(
            (
                "properties",
                "Backspace at the first line keeps them",
                after == text,
                repr(after[:60]),
            )
        )
        scroll = await cdp.js("document.querySelector('.pp-split .cm-scroller').scrollTop")

        # paper: Letter (Settings → Print) lays it out again, with more pages
        before_pages = len((await cdp.js("qp.result()"))["pages"])
        before = await cdp.js("qp.src()")
        await cdp.key(",", 188, ctrl=True)
        await asyncio.sleep(1.2)
        went = await click_text(cdp, ".pp-set-navitem", "Print")
        await asyncio.sleep(0.6)
        picked = await click_text(cdp, ".pp-set-content .pp-seg-item", "Letter")
        result = await wait_layout(cdp, before)
        letter = await cdp.js(
            "getComputedStyle(document.querySelector('.pp-split .cm-editor')).getPropertyValue('--pp-page-text').trim()"
        )
        sheet = (await cdp.js("qp.sheets()"))[0]["sheet"] if result else 0
        want_h = round((279.4 - 0.3) * 96 / 25.4)
        ok = bool(result) and abs(sheet - want_h) <= 1 and letter == "175.9mm"
        results.append(
            (
                "paper",
                "Letter lays the note out again",
                ok,
                f"nav={went} picked={picked} pages {before_pages}->{len(result['pages']) if result else None} width={letter} sheet={sheet}px want {want_h}",
            )
        )
        if result:
            sheets = await cdp.js("qp.sheets()")
            src = await cdp.js("qp.src()")
            check_pdf(
                "letter",
                src if src.startswith("http") else origin + src,
                sheets,
                work,
                "Letter",
                results,
            )
        closed = await cdp.js(
            "(() => { const x = document.querySelector('.pp-set-close'); if (!x) return false; const r = x.getBoundingClientRect(); return [r.left + r.width / 2, r.top + r.height / 2]; })()"
        )
        if closed:
            await cdp.click(*closed)  # close Settings
            await asyncio.sleep(0.8)

        # page view off again: properties back, caret and scroll kept
        caret = await cdp.js("qp.caret()")
        ok = await open_menu_and_click(cdp, "Page view")
        await asyncio.sleep(1)
        off = await cdp.js(
            "!document.querySelector('.pp-split .cm-editor.pp-page-view') && !document.querySelector('.pp-split .pp-page-line')"
        )
        back = await cdp.js("!!document.querySelector('.pp-split .pp-frontmatter')")
        results.append(
            (
                "page view",
                "turned off from the ⋯ menu",
                ok and off and back,
                f"off={off} properties={back}",
            )
        )
        results.append(
            ("page view", "caret kept when turned off", await cdp.js("qp.caret()") == caret, "")
        )
        del scroll

        await real_pages_checks(cdp, work, origin, results)

        # a 1000-line note: typing costs the same with page view on as off; pages still arrive
        typing_js = "(() => { const v = qp.view(); v.dispatch({selection: {anchor: 500}}); const t = performance.now(); for (let i = 0; i < 50; i++) v.dispatch({changes: {from: v.state.selection.main.head, insert: 'x'}, selection: {anchor: v.state.selection.main.head + 1}, userEvent: 'input.type'}); return (performance.now() - t) / 50; })()"
        big = para(1000, "big", 10)
        await cdp.js(f"qp.set({json.dumps(big)})")
        await asyncio.sleep(1.5)
        off_ms = min([await cdp.js(typing_js) or 99 for _ in range(3)])
        before = await cdp.js("qp.src()")
        await open_menu_and_click(cdp, "Page view")
        t0 = time.monotonic()
        result = await wait_layout(cdp, before, timeout=60)
        layout_s = time.monotonic() - t0
        on_ms = min([await cdp.js(typing_js) or 99 for _ in range(3)])
        results.append(
            (
                "1000 lines",
                "typing costs no more with page view on",
                on_ms <= off_ms * 1.3 + 2,
                f"off {off_ms:.1f} ms/key, on {on_ms:.1f} ms/key",
            )
        )
        results.append(
            (
                "1000 lines",
                "pages arrive after a pause",
                bool(result) and layout_s < 20,
                f"{layout_s:.1f}s, {len(result['pages']) if result else 0} pages",
            )
        )


# Every sheet's height in Real pages, from CodeMirror's height map (after scrolling through once, so
# every line has been measured), and the line each gap stands on.
SHEETS_JS = """(async (margin) => {
  const v = qp.view(); const s = v.scrollDOM; const gaps = new Map();
  for (let y = 0; y < s.scrollHeight + 400; y += 250) {
    s.scrollTop = y; await new Promise((r) => setTimeout(r, 100));
    for (const g of v.dom.querySelectorAll('.pp-sheet-gap')) gaps.set(g.getAttribute('aria-label'), { pos: v.posAtDOM(g), end: parseFloat(g.querySelector('.pp-sheet-end').style.height) });
  }
  await new Promise((r) => setTimeout(r, 400));
  const list = [...gaps.values()].map((g) => ({ ...g, top: v.lineBlockAt(g.pos).top })).sort((a, b) => a.top - b.top);
  let top = 0; const heights = [];
  for (const g of list) { heights.push(Math.round(g.top + g.end - top)); top = g.top + g.end + 28; }
  heights.push(Math.round(v.contentHeight - top));
  s.scrollTop = 0;
  return { heights, lines: list.map((g) => v.state.doc.lineAt(g.pos).number) };
})"""


async def set_page_view(cdp: Cdp, label: str) -> bool:
    """Settings → Editor → Page view → ``label``; Settings closed again."""
    await cdp.key(",", 188, ctrl=True)
    await asyncio.sleep(1.2)
    ok = await click_text(cdp, ".pp-set-navitem", "Editor")
    await asyncio.sleep(0.6)
    ok = ok and await click_text(cdp, ".pp-set-content .pp-seg-item", label)
    await asyncio.sleep(0.6)
    closed = await cdp.js(
        "(() => { const x = document.querySelector('.pp-set-close'); if (!x) return false; const r = x.getBoundingClientRect(); return [r.left + r.width / 2, r.top + r.height / 2]; })()"
    )
    if closed:
        await cdp.click(*closed)
        await asyncio.sleep(0.8)
    return ok


async def caret_line(cdp: Cdp) -> int:
    return await cdp.js("qp.view().state.doc.lineAt(qp.caret()).number")


async def put_caret(cdp: Cdp, line: int) -> None:
    await cdp.js(
        f"(() => {{ const v = qp.view(); const at = v.state.doc.line({line}).from; v.dispatch({{selection: {{anchor: at}}, scrollIntoView: true}}); v.focus(); }})()"
    )
    await asyncio.sleep(0.3)


async def real_pages_checks(cdp: Cdp, work: Path, origin: str, results: list) -> None:
    """Real pages: sheets as tall as the paper, gaps on the page starts, caret and clicks across a
    gap, Enter pushing a line onto the next page, Ctrl+Enter, the ⋯ menu's last style."""
    want = round(279.4 * 96 / 25.4)  # a Letter sheet: the paper is Letter by now (see "paper")
    text = FIXTURES["long paragraphs"]
    before = await cdp.js("qp.src()")
    await cdp.js(f"qp.set({json.dumps(text)})")
    picked = await set_page_view(cdp, "Real pages")
    result = await wait_layout(cdp, before)
    real = await cdp.js("!!document.querySelector('.pp-split .cm-editor.pp-real-pages')")
    results.append(
        (
            "real pages",
            "chosen in Settings",
            picked and real and bool(result),
            f"picked={picked} on={real}",
        )
    )
    if not result:
        return
    await asyncio.sleep(1)
    got = await cdp.js(f"{SHEETS_JS}({round(20 * 96 / 25.4)})")
    starts = [p["line"] for p in result["pages"][1:]]
    results.append(
        (
            "real pages",
            "a gap on every page start",
            got["lines"] == starts,
            f"gaps={got['lines']} pages={starts}",
        )
    )
    results.append(
        (
            "real pages",
            "every sheet is the paper's height",
            all(abs(h - want) <= 2 for h in got["heights"]),
            f"{got['heights']} want {want}",
        )
    )

    # caret and clicks across a gap
    start = starts[0]
    await put_caret(cdp, start - 1)
    await cdp.key("ArrowDown", 40)
    results.append(
        (
            "real pages",
            "ArrowDown crosses the gap",
            await caret_line(cdp) == start,
            f"line {await caret_line(cdp)} want {start}",
        )
    )
    await put_caret(cdp, start + 3)
    pos = await cdp.js(
        f"(() => {{ const v = qp.view(); const c = v.coordsAtPos(v.state.doc.line({start}).from + 2); return [c.left + 1, (c.top + c.bottom) / 2]; }})()"
    )
    await cdp.click(*pos)
    await asyncio.sleep(0.3)
    results.append(
        (
            "real pages",
            "a click lands on its line",
            await caret_line(cdp) == start,
            f"line {await caret_line(cdp)} want {start}",
        )
    )

    # Enter pushes a line onto the next page
    rows = "\n\n".join(f"row{i} " + words(8) for i in range(70))
    before = await cdp.js("qp.src()")
    await cdp.js(f"qp.set({json.dumps(rows)})")
    result = await wait_layout(cdp, before)
    if result:
        target = result["pages"][1]["line"] - 2  # the last row on page 1
        await put_caret(cdp, target)
        before = await cdp.js("qp.src()")
        for _ in range(12):
            await cdp.key("Enter", 13)
        result = await wait_layout(cdp, before)
        moved = result["pages"][1]["line"] if result else None
        results.append(
            (
                "enter",
                "pushes the line onto the next page",
                moved == target + 12,
                f"page 2 starts on {moved}, want {target + 12}",
            )
        )
        if result:
            sheets = await cdp.js("qp.sheets()")
            results.append(
                (
                    "enter",
                    "the pushed line starts its sheet",
                    sheets[1]["text"].startswith(f"row{(target - 1) // 2}"),
                    sheets[1]["text"][:20],
                )
            )
            src = await cdp.js("qp.src()")
            check_pdf(
                "enter",
                src if src.startswith("http") else origin + src,
                sheets,
                work,
                "Letter",
                results,
            )

    # Ctrl+Enter: a page break at the caret
    before = await cdp.js("qp.src()")
    await cdp.js(f"qp.set({json.dumps(text)})")
    await wait_layout(cdp, before)
    await put_caret(cdp, 5)
    before = await cdp.js("qp.src()")
    await cdp.key("Enter", 13, ctrl=True)
    result = await wait_layout(cdp, before)
    now = await cdp.js("qp.view().state.doc.toString()")
    line = now.split("\n").index(text.split("\n")[4]) + 1
    ok = (
        "p0l3 " in now
        and "\n\n---/\n\np0l4 " in now
        and bool(result)
        and result["pages"][1]["line"] == line
    )
    results.append(
        (
            "ctrl+enter",
            "inserts ---/ and starts a new page",
            ok,
            f"{now[:120]!r} pages={result and [p['line'] for p in result['pages']]}",
        )
    )

    # the ⋯ menu brings back the last style; leave page view off
    await open_menu_and_click(cdp, "Page view")
    off = await cdp.js("!document.querySelector('.pp-split .cm-editor.pp-page-view')")
    await open_menu_and_click(cdp, "Page view")
    back = await cdp.js("!!document.querySelector('.pp-split .cm-editor.pp-real-pages')")
    results.append(
        (
            "real pages",
            "the ⋯ menu brings back the last style",
            off and back,
            f"off={off} back={back}",
        )
    )
    await open_menu_and_click(cdp, "Page view")


def pdf_mode(url: str, out: str, paper: str) -> None:
    """``--pdf``: print ``url`` with native_boot.print_to_pdf and report each page's text."""
    from qtpy.QtCore import QTimer
    from qtpy.QtPdf import QPdfDocument
    from qtpy.QtWidgets import QApplication

    from paper_pile.gui.native_boot import print_to_pdf

    app = QApplication(sys.argv[:1])
    state: dict[str, bool] = {}

    def done(ok: bool) -> None:
        state["ok"] = ok
        QTimer.singleShot(0, app.quit)

    QTimer.singleShot(0, lambda: print_to_pdf(url, out, paper, done))
    app.exec()
    if not state.get("ok"):
        print(json.dumps("print_to_pdf failed"))
        return
    doc = QPdfDocument(None)
    doc.load(out)
    print(json.dumps([doc.getAllText(i).text() for i in range(doc.pageCount())]))


def main() -> int:
    if "--pdf" in sys.argv:
        i = sys.argv.index("--pdf")
        pdf_mode(*sys.argv[i + 1 : i + 4])
        return 0
    keep = "--keep" in sys.argv
    work = Path(tempfile.mkdtemp(prefix="pp-qa-print-"))
    vault = work / "vault"
    (vault / ".qa.assets").mkdir(parents=True)
    from PIL import Image

    Image.new("RGB", (300, 3000), (90, 140, 220)).save(vault / ".qa.assets" / "tall.png")
    (vault / "qa.md").write_text("start\n")
    (vault / ".paper-pile").mkdir()
    (vault / ".paper-pile" / "session.json").write_text(
        json.dumps({"tabs": ["qa.md"], "active": "qa.md"})
    )
    env = {
        **os.environ,
        "QT_QPA_PLATFORM": "offscreen",
        "XDG_CONFIG_HOME": str(work / "xdg"),
        "XDG_STATE_HOME": str(work / "state"),
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
        results: list[tuple[str, str, bool, str]] = []
        try:
            asyncio.run(run(PORT, work, results))
        except Exception as exc:  # report what was checked before it broke
            import traceback

            traceback.print_exc()
            results.append(("harness", "ran to the end", False, repr(exc)))
    finally:
        os.killpg(app.pid, 15)
        if keep:
            print(f"kept {work}")
        else:
            shutil.rmtree(work, ignore_errors=True)
    failed = [r for r in results if not r[2]]
    for name, check, ok, detail in results:
        if ok and "--all" not in sys.argv:
            continue
        print(f"{'PASS' if ok else 'FAIL'}  {name:24} {check:52} {'' if ok else detail}")
    print(f"\n{len(results) - len(failed)} passed, {len(failed)} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
