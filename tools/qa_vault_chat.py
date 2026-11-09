# ruff: noqa: E501
"""Vault agent in the chat, real app (dev tool; PLAN_vault_agent M7 / MC): a vault question →
the found notes with chips → a chip clicked → a summary with citation pills → a pill clicked
opens its note. Native app offscreen on a throwaway vault, isolated settings, a scripted fake
model, real mouse events over CDP (elementFromPoint checked).
Usage:  uv run python tools/qa_vault_chat.py [--keep] [--auto]   (--auto: Apply at once)
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

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))
from qa_editor import Cdp  # noqa: E402

from paper_pile.core.ai.access import Grant, save_grant  # noqa: E402

PORT = int(os.environ.get("QA_PORT", "9363"))
MODE = "auto" if "--auto" in sys.argv else "ask"  # ai.edits for the edit checks (PLAN §4.32)
NOTES = {
    "Research/Yunus.md": "# Yunus\n\nFounder of Grameen Bank.\nMicrocredit for the poor.\n\n## Groups\n\nLoans to groups.\n",
    "Research/Bank.md": "# Bank\n\n## Groups\n\nMicrocredit groups lend to each other.\n",
    "Other.md": "# Other\n\nNothing here.\n",
}


def step(action: str, **kw: object) -> dict[str, object]:
    base: dict[str, object] = {
        "action": action,
        "meta": "",
        "folders": [],
        "tags": [],
        "notes": [],
        "linked_from": [],
        "links_to": [],
        "dates": {},
        "date_kind": "content",
        "from_result": "",
        "topic": "",
        "terms": [],
        "detail": "",
        "depends_on": -1,
    }
    base.update(kw)
    return base


YES = json.dumps(
    {
        "verdicts": [
            {"n": n, "relevance": "yes", "reason": "about microcredit"} for n in range(1, 11)
        ]
    }
)
SCRIPT = [
    json.dumps(
        {
            "needs_vault": True,
            "steps": [step("locate", topic="microcredit", terms=["microcredit"])],
            "question": "",
            "options": [],
        }
    ),
    YES,  # the judge: every candidate on topic
    json.dumps({"terms": []}),  # no second round
    json.dumps(
        {
            "needs_vault": True,
            "steps": [step("summarise", from_result="all", detail="summarise these notes")],
            "question": "",
            "options": [],
        }
    ),
    json.dumps({"summary": "Grameen Bank and microcredit.", "terms": ["microcredit"]}),  # cards
    json.dumps({"summary": "Microcredit groups.", "terms": ["microcredit"]}),
    "Grameen lends to the poor [1]. Groups lend to each other [2].",
    # an edit across notes: remove a section (Python cuts it; no edit-pipeline call)
    json.dumps(
        {
            "needs_vault": True,
            "steps": [
                step(
                    "edit",
                    folders=["Research"],
                    detail="remove the Groups section from the notes in Research",
                )
            ],
            "question": "",
            "options": [],
        }
    ),
    json.dumps({"kind": "remove", "section": "Groups", "instruction": "remove the Groups section"}),
]
HELP = r"""
window.qa = {
  rect(sel, i = 0) { const e = document.querySelectorAll(sel)[i]; if (!e) return null; const r = e.getBoundingClientRect(); return [r.x + r.width / 2, r.y + r.height / 2]; },
  hit(sel, i = 0) { const p = qa.rect(sel, i); if (!p) return false; const e = document.elementFromPoint(p[0], p[1]); return !!e && !!e.closest(sel); },
  all(sel) { return [...document.querySelectorAll(sel)].map(e => e.textContent.trim()); },
  last() { const b = [...document.querySelectorAll('.pp-chat .pp-msg-ai .pp-msg-body')]; return b.length ? b[b.length - 1].textContent : ''; },
  chip(label) { return [...document.querySelectorAll('.pp-vault-chip')].findIndex(e => e.textContent.trim() === label); },
  doc() { const c = document.querySelector('.pp-split .cm-content'); if (!c) return ''; const v = c.cmTile?.root?.view ?? c.cmView?.view; return v ? v.state.doc.toString() : ''; },
};
'ok'
"""
results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: object = "") -> None:
    results.append((name, bool(ok), str(detail)[:200]))


async def wait_for(cdp: Cdp, expr: str, seconds: float = 15) -> object:
    end = time.monotonic() + seconds
    value: object = None
    while time.monotonic() < end:
        value = await cdp.js(expr)
        if value:
            return value
        await asyncio.sleep(0.25)
    return value


async def click_at(cdp: Cdp, rect_expr: str, ctrl: bool = False) -> None:
    """A real mouse click at the centre of what ``rect_expr`` names (Ctrl held with ``ctrl``)."""
    pos = await cdp.js(rect_expr)
    if not pos:
        return
    x, y = pos
    mods = 2 if ctrl else 0
    await cdp.call("Input.dispatchMouseEvent", type="mouseMoved", x=x, y=y, modifiers=mods)
    for kind in ("mousePressed", "mouseReleased"):
        await cdp.call(
            "Input.dispatchMouseEvent",
            type=kind,
            x=x,
            y=y,
            button="left",
            clickCount=1,
            modifiers=mods,
        )


async def send(cdp: Cdp, text: str) -> None:
    await cdp.js("document.querySelector('.pp-chat .pp-chat-input textarea').focus()")
    await cdp.type(text)
    await cdp.key("Enter", 13)


async def checks(port: int, vault: Path) -> None:
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
        await send(cdp, "where are my microcredit notes?")
        listed = await wait_for(cdp, "qa.last().includes('Found') && qa.last()", 20)
        check(
            "a vault question is answered by the agent",
            bool(listed) and "Yunus" in str(listed) and "Bank" in str(listed),
            listed,
        )
        chips = await wait_for(
            cdp, "qa.all('.pp-vault-chip').length && qa.all('.pp-vault-chip')", 5
        )
        check(
            "chips under the answer",
            isinstance(chips, list) and {"Summarise all", "Make a table", "Open all"} <= set(chips),
            chips,
        )
        # save the search, then find it in the chat's menu (P30.41)
        save_i = await cdp.js("qa.chip('Save this search')")
        await click_at(cdp, f"qa.rect('.pp-vault-chip', {save_i})")
        await asyncio.sleep(0.5)
        await click_at(cdp, "qa.rect('.pp-chat-more-btn')")
        listed = await wait_for(
            cdp,
            "qa.all('.pp-chat-menu .pp-menu-title').includes('where are my microcredit notes?')",
            5,
        )
        check("a saved search is listed in the chat menu", listed is True, listed)
        await cdp.key("Escape", 27)
        await asyncio.sleep(0.4)
        i = await cdp.js("qa.chip('Summarise all')")
        hit = await cdp.js(f"qa.hit('.pp-vault-chip', {i})")
        check("the chip is not covered (elementFromPoint)", hit is True, hit)
        pos = await cdp.js(f"qa.rect('.pp-vault-chip', {i})")
        if pos:
            await cdp.click(*pos)
        summary = await wait_for(cdp, "qa.all('.pp-chat .pp-cite').length >= 2 && qa.last()", 20)
        check(
            "the chip's message ran: a summary with pills",
            bool(summary) and "Grameen lends" in str(summary),
            summary,
        )
        pills = await cdp.js(
            "[...document.querySelectorAll('.pp-chat .pp-cite')].map(p => [p.textContent, p.dataset.tip])"
        )
        check(
            "pills carry the note as hover text",
            isinstance(pills, list) and len(pills) >= 2 and all(t for _, t in pills),
            pills,
        )
        shots = os.environ.get("QA_SHOTS")
        if shots:  # what the answer looks like (pills, chips, steps)
            import base64

            shot = await cdp.call("Page.captureScreenshot", format="png")
            Path(shots, "vault-chat.png").write_bytes(base64.b64decode(shot["data"]))
        old_chips = await cdp.js("qa.all('.pp-vault-chip')")
        check(
            "only the newest answer has chips", "Summarise all" not in (old_chips or []), old_chips
        )
        hit = await cdp.js("qa.hit('.pp-chat .pp-cite', 1)")
        check("the pill is not covered (elementFromPoint)", hit is True, hit)
        pos = await cdp.js("qa.rect('.pp-chat .pp-cite', 1)")
        if pos:
            await cdp.click(*pos)
        opened = await wait_for(cdp, "qa.doc()", 10)
        check(
            "clicking a pill opens its note",
            isinstance(opened, str) and "Microcredit" in opened,
            opened,
        )
        tab = await cdp.js("qa.all('.pp-tab-active .pp-tab-name, .pp-tab.pp-tab-active')")
        check("the cited note is the active tab", bool(tab), tab)
        band = await wait_for(cdp, "document.querySelectorAll('.pp-cite-band').length", 5)
        check("a band stays on the cited lines", bool(band), band)
        await click_at(cdp, "qa.rect('.pp-split .cm-content')")  # a click in the note
        await asyncio.sleep(0.4)
        gone = await cdp.js("document.querySelectorAll('.pp-cite-band').length")
        check("the band goes on the next click", gone == 0, gone)
        link = await cdp.js("qa.hit('.pp-chat a[href^=\"pp-note:\"]', 0)")
        check("a note title in a list is a link, not covered", link is True, link)
        await click_at(cdp, "qa.rect('.pp-chat a[href^=\"pp-note:\"]', 0)")
        named = await wait_for(cdp, "qa.doc().includes('Microcredit') && qa.doc()", 10)
        check("clicking a note title opens it", bool(named), named)
        await click_at(cdp, "qa.rect('.pp-chat .pp-cite', 0)", ctrl=True)
        split = await wait_for(cdp, "!!document.querySelector('.pp-split-on')", 8)
        check("Ctrl+click on a pill opens split view", split is True, split)

        # an edit across notes (PLAN §4.32): no gate in the chat — by the edit mode
        bank = vault / "Research" / "Bank.md"
        yunus = vault / "Research" / "Yunus.md"
        before, yunus_before = bank.read_text(), yunus.read_text()
        await send(cdp, "remove the Groups section from the notes in Research")
        if MODE == "auto":
            applied = await wait_for(cdp, "qa.last().startsWith('Changed') && qa.last()", 20)
            await asyncio.sleep(1.5)  # the editor's write lands on disk
            check(
                "Apply at once: written without asking",
                bool(applied)
                and "Apply all" not in str(applied)
                and "## Groups" not in bank.read_text()
                and "## Groups" not in yunus.read_text(),
                [applied, bank.read_text()],
            )
            check(
                "no chips (no gate, no Undo chip)",
                not await cdp.js("qa.all('.pp-vault-chip').length"),
            )
            flashed = await cdp.js(
                "document.querySelectorAll('.pp-split .cm-line.pp-ai-add, .pp-split .cm-line.pp-ai-del').length"
            )
            check("the open note's changed lines flash", bool(flashed), flashed)
            await asyncio.sleep(3)
            gone = await cdp.js(
                "document.querySelectorAll('.pp-split .cm-line.pp-ai-add, .pp-split .cm-line.pp-ai-del').length"
            )
            check("the flash fades away", gone == 0, gone)
            return
        shown = await wait_for(cdp, "qa.last().includes('shown in the note') && qa.last()", 20)
        check(
            "Review in the note: the chat says where, no gate",
            bool(shown)
            and "Apply all" not in str(shown)
            and "Nothing is changed" not in str(shown),
            shown,
        )
        check("no chips in the chat", not await cdp.js("qa.all('.pp-vault-chip').length"))
        check(
            "nothing is written before Accept",
            bank.read_text() == before and yunus.read_text() == yunus_before,
        )
        bar = await wait_for(
            cdp, "document.querySelectorAll('.pp-split .pp-aidiff-bar').length", 10
        )
        check("the note on screen shows the diff", bool(bar), bar)
        name = await cdp.js("qa.all('.pp-tab.pp-tab-active')")
        first = "Bank" if "Bank" in str(name) else "Yunus"
        hit = await cdp.js("qa.hit('.pp-split .pp-aidiff-bar .pp-aidiff-accept')")
        check("Accept all is not covered (elementFromPoint)", hit is True, hit)
        await click_at(cdp, "qa.rect('.pp-split .pp-aidiff-bar .pp-aidiff-accept')")
        await asyncio.sleep(1.5)
        target, other = (bank, yunus) if first == "Bank" else (yunus, bank)
        other_before = before if other is bank else yunus_before
        check(
            "Accept all changed that note only",
            "## Groups" not in target.read_text() and other.read_text() == other_before,
            [first, target.read_text(), other.read_text()],
        )
        tabs = await cdp.js("qa.all('.pp-tab')")
        i = next((k for k, t in enumerate(tabs or []) if t.startswith(other.stem)), None)
        check("the other note waits in its own tab", i is not None, tabs)
        if i is not None:
            await click_at(cdp, f"qa.rect('.pp-tab', {i})")
        bar = await wait_for(
            cdp, "document.querySelectorAll('.pp-split .pp-aidiff-bar').length", 10
        )
        check("its diff shows when its tab is opened", bool(bar), bar)
        await click_at(cdp, "qa.rect('.pp-split .pp-aidiff-bar .pp-aidiff-reject')")
        await asyncio.sleep(1.0)
        check(
            "Reject all leaves it as it was", other.read_text() == other_before, other.read_text()
        )


def main() -> int:
    work = Path(tempfile.mkdtemp(prefix="pp-qa-vault-"))
    vault = work / "vault"
    (vault / ".paper-pile").mkdir(parents=True)
    for rel, text in NOTES.items():
        (vault / rel).parent.mkdir(parents=True, exist_ok=True)
        (vault / rel).write_text(text)
    script = work / "script.json"
    script.write_text(json.dumps(SCRIPT))
    xdg = work / "xdg"
    save_grant(vault, Grant("2026-11-06T12:00"), xdg / "paper-pile")
    if MODE == "auto":
        (xdg / "paper-pile").mkdir(parents=True, exist_ok=True)
        (xdg / "paper-pile" / "config.toml").write_text('[ai]\nedits = "auto"\n')
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
            asyncio.run(checks(PORT, vault))
        except Exception as exc:  # noqa: BLE001
            check("script ran to the end", False, repr(exc))
    finally:
        os.killpg(app.pid, 15)
        if "--keep" not in sys.argv:
            shutil.rmtree(work, ignore_errors=True)
    for name, ok, detail in results:
        print(f"{'PASS' if ok else 'FAIL'}  {name:48} {'' if ok else detail}")
    print(f"\n{sum(r[1] for r in results)} passed, {sum(not r[1] for r in results)} failed")
    return 0 if all(r[1] for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
