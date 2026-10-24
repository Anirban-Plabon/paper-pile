# ruff: noqa: E501  (embedded JavaScript)
"""UI timing: how long do startup and the everyday actions take? (dev tool, not part of the app)

Launches the native app offscreen on a generated throwaway vault (isolated XDG dirs), drives it
over CDP and prints one line per action: wall time until the result is on screen (two frames
painted) and how much of it the renderer's main thread was busy — the rest is the server and the
websocket. Scrolling and pane toggles print frame stats. Usage:

    uv run python tools/perf_ui.py [--notes 2000] [--keep] [--loop-debug] [--cold-index]

The vault's index is built before the app starts, as after any earlier run (``--cold-index``:
a vault opened for the first time, indexed while the actions are measured).

``--loop-debug`` runs the server with asyncio's debug mode and lists the callbacks that blocked
the event loop longest (debug mode itself slows the app a little).
"""

import argparse
import asyncio
import json
import os
import random
import re
import shutil
import statistics
import subprocess
import tempfile
import time
import urllib.request
from collections.abc import Awaitable, Callable
from pathlib import Path

import websockets
from qa_editor import Cdp

from paper_pile.core.index import Index
from paper_pile.core.vault import Vault

REPO = Path(__file__).resolve().parent.parent
PORT = int(os.environ.get("PERF_PORT", "9447"))

WAIT = r"""
(async (cond, limit) => {
  const t0 = performance.now();
  while (!cond()) {
    if (performance.now() - t0 > limit) return -1;
    await new Promise(r => requestAnimationFrame(r));
  }
  await new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)));
  return performance.now() - t0;
})
"""

FRAMES = r"""
(async (ms) => {
  const d = []; let last = performance.now(); const end = last + ms;
  while (performance.now() < end) {
    await new Promise(r => requestAnimationFrame(r));
    const n = performance.now(); d.push(n - last); last = n;
  }
  d.sort((a, b) => a - b);
  return {fps: Math.round(d.length / (ms / 1000)), p50: Math.round(d[d.length >> 1]),
          p95: Math.round(d[Math.floor(d.length * 0.95)]), max: Math.round(d[d.length - 1]),
          long: d.filter(x => x > 50).length};
})
"""

TABS = "document.querySelectorAll('.pp-tabstrip .pp-tab').length"
ACTIVE = "(document.querySelector('.pp-tab-active .pp-tab-title')?.textContent || '')"
DIALOG = "!!document.querySelector('.q-dialog .q-card, .q-dialog__inner > div')"
SETTINGS = "!!document.querySelector('.pp-set')?.offsetParent"

Action = Callable[[], Awaitable[None]]


def make_vault(vault: Path, notes: int) -> None:
    random.seed(1)
    para = "Some text with a [[link]] and #tag and **bold** words in it. " * 6
    for i in range(notes):
        folder = vault / f"folder{i % 40:02d}"
        folder.mkdir(parents=True, exist_ok=True)
        links = " ".join(f"[[n{random.randrange(notes)}]]" for _ in range(4))
        body = f"# Note {i}\n\n" + (para + "\n\n") * 8 + f"{links}\n\n- [ ] a task\n"
        (folder / f"n{i}.md").write_text(body)
    sections = (
        f"## Section {k}\n\n{para}\n\n- item one\n- item two\n\n| a | b |\n|---|---|\n| {k} | x |"
        for k in range(400)
    )
    (vault / "big.md").write_text("# Big note\n\n" + "\n\n".join(sections))
    tabs = ["big.md"] + [f"folder{i % 40:02d}/n{i}.md" for i in range(min(14, notes))]
    (vault / ".paper-pile").mkdir()
    (vault / ".paper-pile" / "session.json").write_text(
        json.dumps({"tabs": tabs, "active": "big.md"})
    )


async def busy_ms(cdp: Cdp) -> float:
    r = await cdp.call("Performance.getMetrics")
    return next(m["value"] for m in r["metrics"] if m["name"] == "TaskDuration") * 1000


async def timed(cdp: Cdp, act: Action, cond: str, limit: int = 10000) -> tuple[float, float]:
    """(wall ms until ``cond`` holds and two frames are painted, renderer busy ms); -1: never"""
    b0 = await busy_ms(cdp)
    t0 = time.perf_counter()
    await act()
    r = await cdp.js(f"{WAIT}(() => {cond}, {limit})")
    wall = (time.perf_counter() - t0) * 1000
    return (wall if r != -1 else -1.0), await busy_ms(cdp) - b0


def key(cdp: Cdp, k: str, code: int, ctrl: bool = True) -> Action:
    async def go() -> None:
        for t in ("rawKeyDown", "keyUp"):
            await cdp.call(
                "Input.dispatchKeyEvent",
                type=t,
                key=k,
                windowsVirtualKeyCode=code,
                modifiers=2 if ctrl else 0,
            )

    return go


ESC = 27


def report(name: str, runs: list[tuple[float, float]]) -> None:
    ok = [w for w, _ in runs if w >= 0]
    if not ok:
        print(f"{name:26} not detected")
        return
    busy = statistics.median(b for _, b in runs)
    print(
        f"{name:26} median {statistics.median(ok):6.0f} ms  max {max(ok):6.0f} ms  browser ~{busy:4.0f} ms  (n={len(ok)}/{len(runs)})"
    )


async def frames(cdp: Cdp, ms: int, during: Action) -> object:
    await cdp.js(f"window.__ppFrames = {FRAMES}({ms}), 0")
    await during()
    return await cdp.js("window.__ppFrames")


async def wait_for_page() -> str:
    for _ in range(600):
        try:
            pages = json.load(urllib.request.urlopen(f"http://127.0.0.1:{PORT}/json", timeout=1))
            return next(p["webSocketDebuggerUrl"] for p in pages if p.get("type") == "page")
        except (OSError, StopIteration):
            await asyncio.sleep(0.1)
    raise SystemExit("the app never opened a page")


async def run(t_launch: float) -> None:
    url = await wait_for_page()
    t_page = time.perf_counter()
    async with websockets.connect(url, max_size=None) as ws:
        cdp = Cdp(ws)
        await cdp.call("Performance.enable")
        while not await cdp.js("document.querySelectorAll('.cm-line').length > 5"):
            await asyncio.sleep(0.05)
        print(
            f"startup: window {t_page - t_launch:5.1f} s, note text shown {time.perf_counter() - t_launch:5.1f} s"
        )
        await asyncio.sleep(3)
        print(
            f"DOM nodes {await cdp.js('document.getElementsByTagName(`*`).length')}, tabs {await cdp.js(TABS)}, tree rows {await cdp.js('document.querySelectorAll(`.pp-tree-row`).length')}\n"
        )

        box = await cdp.js(
            "(() => { const r = document.querySelector('.cm-editor')?.getBoundingClientRect(); return r && [r.x + r.width / 2, r.y + r.height / 2]; })()"
        )

        async def wheel() -> None:
            for _ in range(40):
                await cdp.call(
                    "Input.dispatchMouseEvent",
                    type="mouseWheel",
                    x=box[0],
                    y=box[1],
                    deltaX=0,
                    deltaY=120,
                )
                await asyncio.sleep(0.04)

        if box:
            print(f"{'scroll big note':26}", await frames(cdp, 2000, wheel))
        for side, k, code in (("left", "b", 66), ("right", "l", 76)):
            print(f"{'toggle ' + side + ' pane':26}", await frames(cdp, 1200, key(cdp, k, code)))
            await asyncio.sleep(0.6)
            await key(cdp, k, code)()
            await asyncio.sleep(1.0)
        print()

        runs = []
        for _ in range(8):
            before = await cdp.js(ACTIVE)
            runs.append(await timed(cdp, key(cdp, "Tab", 9), f"{ACTIVE} !== {json.dumps(before)}"))
            await asyncio.sleep(0.3)
        report("switch tab (Ctrl+Tab)", runs)

        runs = []
        for _ in range(5):
            runs.append(await timed(cdp, key(cdp, "p", 80), DIALOG))
            await asyncio.sleep(0.3)
            await timed(cdp, key(cdp, "Escape", ESC, ctrl=False), f"!({DIALOG})")
            await asyncio.sleep(0.3)
        report("open palette (Ctrl+P)", runs)

        report("open settings (Ctrl+,)", [await timed(cdp, key(cdp, ",", 188), SETTINGS)])
        await asyncio.sleep(0.5)

        runs = []
        for i in range(4):
            xy = await cdp.js(
                f"(() => {{ const r = document.querySelectorAll('.pp-tree-row')[{i}]?.getBoundingClientRect(); return r && [r.x + 20, r.y + r.height / 2]; }})()"
            )
            if not xy:
                break

            async def right_click(xy: list[float] = xy) -> None:
                for t in ("mousePressed", "mouseReleased"):
                    await cdp.call(
                        "Input.dispatchMouseEvent",
                        type=t,
                        x=xy[0],
                        y=xy[1],
                        button="right",
                        clickCount=1,
                    )

            runs.append(
                await timed(cdp, right_click, "!!document.querySelector('.pp-ctxmenu, .q-menu')")
            )
            await asyncio.sleep(0.3)
            await key(cdp, "Escape", ESC, ctrl=False)()
            await asyncio.sleep(0.5)
        report("tree context menu", runs)

        runs = []
        for _ in range(4):
            n = await cdp.js(TABS)
            runs.append(await timed(cdp, key(cdp, "n", 78), f"{TABS} > {n}"))
            await asyncio.sleep(1.0)
        report("new note (Ctrl+N)", runs)

        runs = []
        for _ in range(6):
            n = await cdp.js(TABS)
            runs.append(await timed(cdp, key(cdp, "w", 87), f"{TABS} < {n}"))
            await asyncio.sleep(0.4)
        report("close tab (Ctrl+W)", runs)


def slow_callbacks(log: Path, top: int = 12) -> None:
    found = re.findall(
        r"Executing (<.{0,140}?) took ([0-9.]+) seconds", log.read_text(errors="replace")
    )
    print(f"\nslowest event-loop callbacks ({len(found)} over 100 ms):")
    for what, secs in sorted(found, key=lambda f: -float(f[1]))[:top]:
        print(f"  {float(secs):5.2f} s  {re.sub(r' at /\S+', '', what)[:110]}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--notes", type=int, default=2000)
    ap.add_argument("--keep", action="store_true", help="keep the throwaway folder")
    ap.add_argument("--loop-debug", action="store_true")
    ap.add_argument("--cold-index", action="store_true", help="no index before the start")
    args = ap.parse_args()
    work = Path(tempfile.mkdtemp(prefix="pp-perf-"))
    vault = work / "vault"
    vault.mkdir()
    make_vault(vault, args.notes)
    if not args.cold_index:
        index = Index(Vault(vault))
        index.sync()
        index.close()
    env = {
        **os.environ,
        "QT_QPA_PLATFORM": "offscreen",
        "XDG_CONFIG_HOME": str(work / "xdg"),
        "XDG_STATE_HOME": str(work / "state"),  # or the user's "last vault" points here
        "XDG_CACHE_HOME": str(work / "cache"),
        "QTWEBENGINE_CHROMIUM_FLAGS": f"--remote-debugging-port={PORT}",
    }
    if args.loop_debug:
        env |= {"PYTHONASYNCIODEBUG": "1", "PYTHONWARNINGS": "ignore"}
    log = work / "app.log"
    t = time.perf_counter()
    with log.open("w") as out:
        app = subprocess.Popen(
            ["uv", "run", "paper-pile", str(vault)],
            cwd=REPO,
            env=env,
            stdout=out,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    try:
        asyncio.run(run(t))
    finally:
        os.killpg(app.pid, 15)
        try:
            app.wait(5)
        except subprocess.TimeoutExpired:
            os.killpg(app.pid, 9)
        if args.loop_debug:
            slow_callbacks(log)
        if args.keep:
            print("kept:", work)
        else:
            shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    main()
