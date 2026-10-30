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
    '{"action": "edit"}',  # 3. "put it in quote": no edit verb, so the model decides
    "> We compare four options for hosting.",
    json.dumps(  # 4. /tone with no words: three tones (one pick-one group)
        {
            "options": [
                {"label": t, "group": "tone"} for t in ("More formal", "Friendly", "Confident")
            ]
        }
    ),
    "The backups are run every night. See [[Ops]].",
    '{"action": "edit"}',  # 5. a messy request: routed to an edit, the planner offers options
    json.dumps(
        {
            "already_there": [],
            "edits": [],
            "options": ["Mention Fly.io here", "Add the price"],
            "question": "",
        }
    ),
    "not a plan",  # the re-run (options off): no usable plan twice → the selection is changed
    "not a plan",
    "- **VM**: a whole machine (5 a month; Fly.io is cheaper)",
    "",  # 6. an empty answer: nothing changed, Try again in the box
    "The backups are run every night. See [[Ops]].",
    "The backups do run every night. See [[Ops]].",  # the diff bar's Try again
    "Our nightly job copies all data to the cloud. See [[Ops]].",  # 7. too big for a fix…
    "Our nightly job copies all data to the cloud. See [[Ops]].",  # …also when asked again
    "The backups run every night. See [[Ops]].",  # Smaller change
    # 9. Summarize from the Ask box: written under the text, without the chatter around it
    "Sure! Here is a one-line summary:\n\nDocker runs one container.\n\nLet me know if you need more.",
    '{"options": ["More formal", "Friendly", "Confident"]}',  # 10. /tone in the chat box
    "The backups are run each night. See [[Ops]].",
    "Les sauvegardes tournent chaque nuit. Voir [[Ops]].",  # 11. Translate → Replace
    "Les sauvegardes tournent la nuit. Voir [[Ops]].",  # → Insert below
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
    widths = await cdp.js(
        "[qa.box('.pp-askpop-cmds'), qa.box('.pp-askpop-card')].map(b => b && b[1])"
    )
    if os.environ.get("QA_SHOTS") and command == "/tone":
        shot = await cdp.call("Page.captureScreenshot", format="png")
        Path(os.environ["QA_SHOTS"], "box-list.png").write_bytes(base64.b64decode(shot["data"]))
    check(
        f"Ask box: the / list is narrower than the box ({command})",
        widths[0] and widths[1] and widths[0] < widths[1],
        widths,
    )
    await cdp.key("Enter", 13)
    await asyncio.sleep(0.4)
    await cdp.type(words)
    await cdp.key("Enter", 13)


async def ask_free(cdp: Cdp, selected: str, words: str) -> None:
    """Typed words without a ``/`` command."""
    await asyncio.sleep(1.5)  # the box opens no sooner than QUIET_S after the last edit
    await cdp.js(f"qa.select({json.dumps(selected)})")
    await wait_for(
        cdp,
        "!!document.querySelector('.pp-askpop textarea') && qa.rect('.pp-askpop textarea') !== null",
    )
    await asyncio.sleep(0.6)
    await cdp.js("document.querySelector('.pp-askpop textarea').focus()")
    await asyncio.sleep(0.3)
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
        gap = await cdp.js(
            "(() => { const r = document.querySelector('.pp-aidiff-band').getBoundingClientRect();"
            " const g = document.querySelector('.pp-aidiff-add').getBoundingClientRect();"
            " return [Math.round(r.bottom), Math.round(g.top)]; })()"
        )
        check("red band stops above the green rows", gap is not None and gap[0] <= gap[1], gap)
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
        # 3. words with no edit verb: the model says "edit", so it becomes a diff, not an answer
        await ask_free(cdp, "We compare four options for hosting.", "put it in quote")
        bar = await wait_for(cdp, "document.querySelector('.pp-aidiff-bar-text')?.textContent", 15)
        answers = await cdp.js("document.querySelectorAll('.pp-askpop .pp-msg-ai').length")
        check(
            "unclear words routed by the model to an edit",
            bar == "AI suggests 1 change" and not answers,
            [bar, answers],
        )
        pos = await cdp.js("qa.rect('.pp-aidiff-bar .pp-aidiff-accept')")
        if pos:
            await cdp.click(*pos)
        text = await wait_for(cdp, "!document.querySelector('.pp-aidiff-bar') && qa.text()", 8)
        check(
            "the paragraph became a quote",
            isinstance(text, str) and "\n> We compare four options for hosting.\n" in text,
            text,
        )
        # 4. a command with no words: the AI's options, ticked with real clicks, then Apply
        await asyncio.sleep(1.5)
        await ask_box(cdp, "Teh backups runs every night. See [[Ops]].", "/tone", "")
        shown = await wait_for(
            cdp, "qa.all('.pp-optbox .pp-opt-text').length && qa.all('.pp-optbox .pp-opt-text')", 10
        )
        check(
            "no words: the options box opens",
            shown == ["More formal", "Friendly", "Confident"],
            shown,
        )
        off = await cdp.js("document.querySelector('.pp-optbox-apply')?.disabled")
        check("Apply is off with nothing ticked", off is True, off)
        hit = await cdp.js("qa.hit('.pp-optbox .pp-opt', 0)")
        check("an option is clickable (hit-test)", hit, hit)
        pos = await cdp.js("qa.rect('.pp-optbox .pp-opt', 0)")
        if pos:
            await cdp.click(*pos)
        await asyncio.sleep(0.4)
        state = await cdp.js(
            "[document.querySelector('.pp-optbox .pp-opt').classList.contains('pp-opt-on'), document.querySelector('.pp-optbox-apply').textContent.trim(), document.querySelector('.pp-optbox-apply').disabled]"
        )
        check("ticking shows Apply 1", state == [True, "Apply 1", False], state)
        pos = await cdp.js("qa.rect('.pp-optbox .pp-opt', 1)")
        if pos:
            await cdp.click(*pos)  # another tone: the first one is unticked
        await asyncio.sleep(0.4)
        state = await cdp.js(
            "[[...document.querySelectorAll('.pp-optbox .pp-opt')].map(r => r.classList.contains('pp-opt-on')), document.querySelector('.pp-optbox-hint').textContent]"
        )
        check(
            "one tone at a time, with a hint",
            state == [[False, True, False, False], "Only one tone"],
            state,
        )
        shot = await cdp.call("Page.captureScreenshot", format="png")
        Path(os.environ["QA_OUT"], "options.png").write_bytes(base64.b64decode(shot["data"]))
        if os.environ.get("QA_SHOTS"):
            Path(os.environ["QA_SHOTS"], "options.png").write_bytes(base64.b64decode(shot["data"]))
        pos = await cdp.js("qa.rect('.pp-optbox-apply')")
        if pos:
            await cdp.click(*pos)
        bar = await wait_for(cdp, "document.querySelector('.pp-aidiff-bar-text')?.textContent", 15)
        added = await cdp.js("qa.all('.pp-aidiff-add').join('\\n')")
        check(
            "Apply runs the command with the ticked option",
            bar == "AI suggests 1 change" and "are run every night" in (added or ""),
            [bar, added],
        )
        pos = await cdp.js("qa.rect('.pp-aidiff-bar .pp-aidiff-reject')")
        if pos:
            await cdp.click(*pos)
        await wait_for(cdp, "!document.querySelector('.pp-aidiff-bar')", 5)
        # 5. a messy request: the AI comes back with clearer ones, the user ticks both
        await ask_free(cdp, "- **VM**: a whole machine", "fly too and maybe cost idk")
        shown = await wait_for(
            cdp, "qa.all('.pp-optbox .pp-opt-text').length && qa.all('.pp-optbox .pp-opt-text')", 15
        )
        title = await cdp.js("qa.all('.pp-optbox-title')")
        check(
            "a messy request comes back as options",
            shown == ["Mention Fly.io here", "Add the price"] and "mean" in str(title),
            [shown, title],
        )
        for i in (0, 1):
            pos = await cdp.js(f"qa.rect('.pp-optbox .pp-opt', {i})")
            if pos:
                await cdp.click(*pos)
            await asyncio.sleep(0.3)
        label = await cdp.js("document.querySelector('.pp-optbox-apply').textContent.trim()")
        check("both ticked: Apply 2", label == "Apply 2", label)
        if os.environ.get("QA_SHOTS"):
            shot = await cdp.call("Page.captureScreenshot", format="png")
            Path(os.environ["QA_SHOTS"], "plan-options.png").write_bytes(
                base64.b64decode(shot["data"])
            )
        pos = await cdp.js("qa.rect('.pp-optbox-apply')")
        if pos:
            await cdp.click(*pos)
        bar = await wait_for(cdp, "document.querySelector('.pp-aidiff-bar-text')?.textContent", 15)
        added = await cdp.js("qa.all('.pp-aidiff-add').join('\\n')")
        check(
            "Apply runs the picked requests (no options again)",
            bar == "AI suggests 1 change" and "Fly.io is cheaper" in (added or ""),
            [bar, added],
        )
        pos = await cdp.js("qa.rect('.pp-aidiff-bar .pp-aidiff-reject')")
        if pos:
            await cdp.click(*pos)
        await wait_for(cdp, "!document.querySelector('.pp-aidiff-bar')", 5)
        # 6. the change fails: the box says why, Try again runs it again
        backups = "Teh backups runs every night. See [[Ops]]."
        await ask_free(cdp, backups, "rewrite it more formally")
        said = await wait_for(
            cdp,
            "qa.all('.pp-askpop .pp-ai-action').length && [qa.all('.pp-askpop .pp-msg-error'), qa.all('.pp-askpop .pp-ai-action')]",
            15,
        )
        check(
            "a failed change says why, with Try again",
            bool(said)
            and "Nothing was changed" in str(said[0])
            and said[1] == ["Try again", "Change request"],
            said,
        )
        if os.environ.get("QA_SHOTS"):
            shot = await cdp.call("Page.captureScreenshot", format="png")
            Path(os.environ["QA_SHOTS"], "failed.png").write_bytes(base64.b64decode(shot["data"]))
        hit = await cdp.js("qa.hit('.pp-askpop .pp-ai-action', 0)")
        pos = await cdp.js("qa.rect('.pp-askpop .pp-ai-action', 0)")
        if pos:
            await cdp.click(*pos)
        bar = await wait_for(cdp, "document.querySelector('.pp-aidiff-bar-text')?.textContent", 15)
        added = await cdp.js("qa.all('.pp-aidiff-add').join('\\n')")
        check(
            "Try again runs it again",
            hit and "are run every night" in (added or ""),
            [hit, bar, added],
        )
        pos = await cdp.js("qa.rect('.pp-aidiff-bar .pp-aidiff-again')")
        if pos:
            await cdp.click(*pos)
        added = await wait_for(
            cdp, "(t => t.includes('do run') && t)(qa.all('.pp-aidiff-add').join('\\n'))", 15
        )
        check("the diff bar's Try again: a new answer", "do run every night" in str(added), added)
        pos = await cdp.js("qa.rect('.pp-aidiff-bar .pp-aidiff-reject')")
        if pos:
            await cdp.click(*pos)
        await wait_for(cdp, "!document.querySelector('.pp-aidiff-bar')", 5)
        # 7. a fix that changed too much: Smaller change
        await asyncio.sleep(1.5)
        await ask_box(cdp, backups, "/rewrite", "fix grammar")
        smaller = await wait_for(
            cdp, "!!document.querySelector('.pp-aidiff-bar .pp-aidiff-smaller')", 15
        )
        check("too big a change offers Smaller change", smaller, smaller)
        pos = await cdp.js("qa.rect('.pp-aidiff-bar .pp-aidiff-smaller')")
        if pos:
            await cdp.click(*pos)
        added = await wait_for(
            cdp, "(t => t.includes('backups run') && t)(qa.all('.pp-aidiff-add').join('\\n'))", 15
        )
        check(
            "Smaller change: a smaller answer", "The backups run every night" in str(added), added
        )
        pos = await cdp.js("qa.rect('.pp-aidiff-bar .pp-aidiff-reject')")
        if pos:
            await cdp.click(*pos)
        await wait_for(cdp, "!document.querySelector('.pp-aidiff-bar')", 5)
        # 8. the palette with nothing selected: the Ask box at the caret, the command picked
        await asyncio.sleep(1.5)
        await cdp.js(
            "(() => { const v = qa.view(); v.focus(); v.dispatch({selection: {anchor: 0}}); })()"
        )
        await asyncio.sleep(0.4)
        await cdp.key("p", 80, ctrl=True)
        await wait_for(cdp, "!!document.querySelector('.pp-picker input, .q-dialog input')", 5)
        await asyncio.sleep(0.4)
        await cdp.type("Change tone")
        await asyncio.sleep(0.6)
        await cdp.key("Enter", 13)
        chip = await wait_for(
            cdp,
            "(e => e && e.getClientRects().length && e.textContent)(document.querySelector('.pp-askpop-chip'))",
            8,
        )
        check("palette: the Ask box with the command picked", chip == "/Change tone", chip)
        await cdp.key("Escape", 27)
        await asyncio.sleep(0.5)
        # 9. Summarize in the Ask box: written into the note under the selection
        await asyncio.sleep(1.0)
        await ask_box(cdp, "- **Docker**: one container", "/summarize", "one line")
        text = await wait_for(
            cdp, "(t => t.includes('Docker runs one container.') && t)(qa.text())", 15
        )
        check(
            "Summarize goes after the whole list (not inside it)",
            "- **Fly.io**: a hosted platform\n\nDocker runs one container.\n" in str(text)
            and "Sure" not in str(text)
            and "Let me know" not in str(text),
            text,
        )
        await asyncio.sleep(0.8)
        await cdp.key("z", 90, ctrl=True)  # one undo step takes it out again
        await asyncio.sleep(0.6)
        text = await cdp.js("qa.text()")
        check("one undo step removes it", "Docker runs one container." not in text, text)
        # 10. the chat box: / list, /tone with no words → options card → Apply → diff
        await asyncio.sleep(1.5)
        await cdp.js(f"qa.select({json.dumps(backups)})")
        await wait_for(cdp, "qa.rect('.pp-askpop-to-chat') !== null", 5)
        await asyncio.sleep(0.6)
        pos = await cdp.js("qa.rect('.pp-askpop-to-chat')")
        if pos:
            await cdp.click(*pos)  # Move to chat: the selection becomes a chip
        await wait_for(cdp, "!!document.querySelector('.pp-chat .pp-chat-chip')", 5)
        await cdp.js("document.querySelector('.pp-chat .pp-chat-input textarea').focus()")
        await cdp.type("/to")
        listed = await wait_for(cdp, "qa.all('.pp-chat-cmd').length && qa.all('.pp-chat-cmd')", 5)
        check(
            "chat: the / list shows the AI commands",
            bool(listed) and "Change tone" in str(listed),
            listed,
        )
        widths = await cdp.js(
            "[qa.box('.pp-chat-mentions'), qa.box('.pp-chat .pp-chat-card')].map(b => b && b[1])"
        )
        if os.environ.get("QA_SHOTS"):
            shot = await cdp.call("Page.captureScreenshot", format="png")
            Path(os.environ["QA_SHOTS"], "chat-list.png").write_bytes(
                base64.b64decode(shot["data"])
            )
        check(
            "chat: the / list is narrower than the box",
            widths[0] and widths[1] and widths[0] < widths[1],
            widths,
        )
        pos = await cdp.js("qa.rect('.pp-chat-cmd', 0)")
        if pos:
            await cdp.click(*pos)
        await asyncio.sleep(0.4)
        value = await cdp.js("document.querySelector('.pp-chat .pp-chat-input textarea').value")
        check("picking puts /tone in the box", value == "/tone ", value)
        await cdp.js("document.querySelector('.pp-chat .pp-chat-input textarea').focus()")
        await cdp.key("Enter", 13)
        shown = await wait_for(
            cdp,
            "qa.all('.pp-chat .pp-optbox .pp-opt-text').length && qa.all('.pp-chat .pp-optbox .pp-opt-text')",
            10,
        )
        check(
            "chat: /tone with no words shows options",
            shown == ["More formal", "Friendly", "Confident"],
            shown,
        )
        if os.environ.get("QA_SHOTS"):
            shot = await cdp.call("Page.captureScreenshot", format="png")
            Path(os.environ["QA_SHOTS"], "chat-options.png").write_bytes(
                base64.b64decode(shot["data"])
            )
        pos = await cdp.js("qa.rect('.pp-chat .pp-optbox .pp-opt', 0)")
        if pos:
            await cdp.click(*pos)
        await asyncio.sleep(0.3)
        pos = await cdp.js("qa.rect('.pp-chat .pp-optbox-apply')")
        if pos:
            await cdp.click(*pos)
        added = await wait_for(
            cdp, "(t => t.includes('each night') && t)(qa.all('.pp-aidiff-add').join('\\n'))", 15
        )
        said = await cdp.js("qa.all('.pp-chat .pp-chat-cmdcard .pp-msg-body')")
        check(
            "chat: Apply changes the attached text as a diff",
            "each night" in str(added),
            [added, said],
        )
        pos = await cdp.js("qa.rect('.pp-aidiff-bar .pp-aidiff-reject')")
        if pos:
            await cdp.click(*pos)
        await wait_for(cdp, "!document.querySelector('.pp-aidiff-bar')", 5)
        # 11. Translate in the Ask box: shown, then Replace (a diff) or Insert below
        for push in ("replace", "insert"):
            await asyncio.sleep(1.5)
            await ask_box(cdp, backups, "/translate", "French")
            buttons = await wait_for(
                cdp,
                "qa.all('.pp-askpop .pp-ai-action').length && qa.all('.pp-askpop .pp-ai-action')",
                15,
            )
            check(
                f"Translate answer: Replace / Insert below / Copy ({push})",
                buttons == ["Replace", "Insert below", "Copy"],
                buttons,
            )
            pos = await cdp.js(f"qa.rect('.pp-askpop .pp-ai-push-{push}')")
            if pos:
                await cdp.click(*pos)
            if push == "replace":
                added = await wait_for(
                    cdp,
                    "(t => t.includes('chaque nuit') && t)(qa.all('.pp-aidiff-add').join('\\n'))",
                    10,
                )
                again = await cdp.js("!!document.querySelector('.pp-aidiff-bar .pp-aidiff-again')")
                check(
                    "Replace: a diff, without Try again",
                    "chaque nuit" in str(added) and not again,
                    [added, again],
                )
                pos = await cdp.js("qa.rect('.pp-aidiff-bar .pp-aidiff-reject')")
                if pos:
                    await cdp.click(*pos)
                await wait_for(cdp, "!document.querySelector('.pp-aidiff-bar')", 5)
            else:
                text = await wait_for(cdp, "(t => t.includes('la nuit') && t)(qa.text())", 10)
                check(
                    "Insert below: under the selected text",
                    f"{backups}\n\nLes sauvegardes tournent la nuit. Voir [[Ops]]." in str(text),
                    text,
                )


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
