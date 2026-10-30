# ruff: noqa: E501
"""AI edits QA (dev tool, not part of the app): the Ask box → edit pipeline → diff (PLAN §4.29).

Launches the native app offscreen on a throwaway vault with a scripted fake model, asks for a
change in several places and for a small fix through the Ask box, and checks the diff (reasons,
"outside the selection", word marks, the retried answer) with real mouse events over CDP.
Usage:  uv run python tools/qa_ai_edit.py
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

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))
from qa_editor import Cdp  # noqa: E402

from paper_pile.core.ai.access import Grant, save_grant  # noqa: E402

PORT = int(os.environ.get("QA_PORT", "9361"))
NOTE = """# Hosting

We compare three options for hosting.

- **Docker**: one container
- **VM**: a whole machine
- **Bare metal**: no layer

## Cost

| Option | Price |
|---|---|
| Docker | 0 |
| VM | 5 |
| Bare metal | 40 |

## Notes

Teh backups runs every night. See [[Ops]].
"""
PLAN = {
    "already_there": [],
    "edits": [
        {"why": "add the option", "action": "add_after", "block": "B5", "new_section": False},
        {"why": "add it to the table", "action": "add_after", "block": "B7", "new_section": False},
        {"why": "update the count", "action": "change", "block": "B2", "new_section": False},
    ],
    "question": "",
}
SCRIPT = [
    json.dumps(PLAN),
    "- **Fly.io**: a hosted platform",
    "| Fly.io | 2 |",
    "We compare four options for hosting.",
    "The backups run every night.",
    "The backups run every night. See [[Ops]].",
]
HELP = r"""
window.qa = {
  view() { const c = document.querySelector('.pp-split .cm-content'); return c.cmTile?.root?.view ?? c.cmView.view; },
  text() { return qa.view().state.doc.toString(); },
  select(s) { const v = qa.view(); const t = v.state.doc.toString(); const a = t.indexOf(s); v.focus(); v.dispatch({selection: {anchor: a, head: a + s.length}}); return a; },
  rect(sel, i = 0) { const e = document.querySelectorAll(sel)[i]; if (!e) return null; const r = e.getBoundingClientRect(); return [r.x + r.width / 2, r.y + r.height / 2]; },
  hit(sel, i = 0) { const p = qa.rect(sel, i); if (!p) return false; const e = document.elementFromPoint(p[0], p[1]); return !!e && !!e.closest(sel); },
  all(sel) { return [...document.querySelectorAll(sel)].map(e => e.textContent); },
  box(sel, i = 0) { const e = document.querySelectorAll(sel)[i]; if (!e) return null; const r = e.getBoundingClientRect(); return [Math.round(r.left), Math.round(r.width), Math.round(r.height), getComputedStyle(e).borderTopLeftRadius]; },
  empty() { return qa.view().state.selection.main.empty; },
};
'ok'
"""

results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: object = "") -> None:
    results.append((name, bool(ok), str(detail)[:300]))


async def wait_for(cdp: Cdp, expr: str, seconds: float = 10) -> object:
    end = time.monotonic() + seconds
    value = None
    while time.monotonic() < end:
        value = await cdp.js(expr)
        if value:
            return value
        await asyncio.sleep(0.2)
    return value


async def ask_box(cdp: Cdp, selected: str, command: str, words: str) -> None:
    await cdp.js(f"qa.select({json.dumps(selected)})")
    await wait_for(
        cdp,
        "!!document.querySelector('.pp-askpop textarea') && qa.rect('.pp-askpop textarea') !== null",
    )
    await asyncio.sleep(0.6)
    await cdp.js("document.querySelector('.pp-askpop textarea').focus()")
    await asyncio.sleep(0.3)
    band, line = await cdp.js("[qa.box('.pp-ai-band'), qa.box('.pp-split .cm-line')]")
    check(
        "the target band: full line width, square",
        band is not None and line is not None and band[:2] == line[:2] and band[3] == "0px",
        [band, line],
    )
    await cdp.type(command)
    await asyncio.sleep(0.5)
    await cdp.key("Enter", 13)
    await asyncio.sleep(0.4)
    await cdp.type(words)
    await cdp.key("Enter", 13)


async def main_checks(port: int) -> None:
    tabs = json.load(urllib.request.urlopen(f"http://127.0.0.1:{port}/json"))
    async with websockets.connect(tabs[0]["webSocketDebuggerUrl"], max_size=None) as ws:
        cdp = Cdp(ws)
        await cdp.call(
            "Emulation.setDeviceMetricsOverride",
            width=1600,
            height=1000,
            deviceScaleFactor=1,
            mobile=False,
        )
        await asyncio.sleep(1)
        await cdp.js(HELP)
        # 1. a multi-place change from the Ask box
        await ask_box(cdp, "- **Bare metal**: no layer", "/rewrite", "add option D: Fly.io")
        bar = await wait_for(cdp, "document.querySelector('.pp-aidiff-bar-text')?.textContent", 15)
        check("bar counts changes and places", bar == "AI suggests 3 changes in 3 places", bar)
        await asyncio.sleep(0.3)
        state = await cdp.js("[qa.empty(), document.querySelectorAll('.pp-ai-band').length]")
        check("with the diff: no selection, no target band", state == [True, 0], state)
        red, green = await cdp.js("[qa.box('.pp-aidiff-band'), qa.box('.pp-aidiff-add')]")
        check(
            "red band and green row: same box, square",
            red is not None and green is not None and red[:2] == green[:2] and red[3] == "0px",
            [red, green],
        )
        whys = await cdp.js("qa.all('.pp-aidiff-why')")
        check(
            "each change says why",
            whys == ["update the count", "add the option", "add it to the table"],
            whys,
        )
        chips = await cdp.js("qa.all('.pp-aidiff-chip-outside').length")
        check("changes outside the selection are marked", chips == 2, chips)
        words = await cdp.js("qa.all('.pp-aidiff-addword')")
        check("changed words are marked", "four" in (words or []), words)
        dels = await cdp.js("qa.all('.pp-aidiff-delword')")
        check("removed words are marked", "three" in (dels or []), dels)
        notes = await cdp.js("qa.all('.pp-aidiff-note')")
        check("notes line (nothing to suggest here)", notes == [], notes)
        shot = await cdp.call("Page.captureScreenshot", format="png")
        Path(os.environ["QA_OUT"], "diff.png").write_bytes(base64.b64decode(shot["data"]))
        hit = await cdp.js("qa.hit('.pp-aidiff-bar .pp-aidiff-accept')")
        check("Accept all is clickable (hit-test)", hit, hit)
        pos = await cdp.js("qa.rect('.pp-aidiff-bar .pp-aidiff-accept')")
        if pos:
            await cdp.click(*pos)
        text = await wait_for(cdp, "!document.querySelector('.pp-aidiff-bar') && qa.text()", 8)
        ok = (
            isinstance(text, str)
            and "We compare four options" in text
            and "- **Bare metal**: no layer\n- **Fly.io**: a hosted platform" in text
            and "| Bare metal | 40 |\n| Fly.io | 2 |" in text
        )
        check("Accept all applies every place", ok, text)
        # 2. a small fix: the dropped link is asked for again, word marks shown
        await ask_box(cdp, "Teh backups runs every night. See [[Ops]].", "/rewrite", "fix grammar")
        bar = await wait_for(cdp, "document.querySelector('.pp-aidiff-bar-text')?.textContent", 15)
        check("fix shows one change", bar == "AI suggests 1 change", bar)
        added = await cdp.js("qa.all('.pp-aidiff-add').join('\\n')")
        check("the retried answer kept the link", "See [[Ops]]" in (added or ""), added)
        pos = await cdp.js("qa.rect('.pp-aidiff-bar .pp-aidiff-reject')")
        if pos:
            await cdp.click(*pos)
        gone = await wait_for(cdp, "!document.querySelector('.pp-aidiff-bar')", 5)
        text = await cdp.js("qa.text()")
        check("Reject all leaves the note", gone and "Teh backups runs every night." in text, text)


def main() -> int:
    work = Path(tempfile.mkdtemp(prefix="pp-qa-ai-"))
    os.environ["QA_OUT"] = str(work)
    vault = work / "vault"
    (vault / ".paper-pile").mkdir(parents=True)
    (vault / "h.md").write_text(NOTE)
    (vault / ".paper-pile" / "session.json").write_text(
        json.dumps({"tabs": ["h.md"], "active": "h.md"})
    )
    script = work / "script.json"
    script.write_text(json.dumps(SCRIPT))
    xdg = work / "xdg"
    save_grant(vault, Grant("2026-10-30T12:00"), xdg / "paper-pile")
    env = {
        **os.environ,
        "QT_QPA_PLATFORM": "offscreen",
        "XDG_CONFIG_HOME": str(xdg),
        "XDG_STATE_HOME": str(work / "state"),
        "XDG_CACHE_HOME": str(work / "cache"),
        "QTWEBENGINE_CHROMIUM_FLAGS": f"--remote-debugging-port={PORT}",
        "PAPER_PILE_FAKE_AI": "1",
        "PAPER_PILE_FAKE_AI_SCRIPT": str(script),
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
        try:
            asyncio.run(main_checks(PORT))
        except Exception as exc:  # noqa: BLE001
            check("script ran to the end", False, repr(exc))
    finally:
        os.killpg(app.pid, 15)
        if "--keep" not in sys.argv:
            shutil.rmtree(work, ignore_errors=True)
    for name, ok, detail in results:
        print(f"{'PASS' if ok else 'FAIL'}  {name:45} {'' if ok else detail}")
    print(f"\n{sum(r[1] for r in results)} passed, {sum(not r[1] for r in results)} failed")
    return 0 if all(r[1] for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
