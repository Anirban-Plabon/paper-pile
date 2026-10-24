# ruff: noqa: E501  (embedded JavaScript)
"""Memory soak: what grows over a long session? (dev tool, not part of the app)

Launches the native app offscreen on a generated throwaway vault (isolated XDG dirs, index
built first) and repeats one round of everyday work: open 8 notes rich in diagrams, math,
tables, images and code through the quick switcher, cycle the tabs, open the palette, settings
and a context menu, close the 8 tabs again. After each round (and a forced garbage collection)
it prints the page's JS heap, DOM nodes, listeners and the RSS of the renderer, the window
process and the Python server. Identical rounds should level off; a steady climb is a leak.

    uv run python tools/mem_soak.py [--rounds 12] [--keep] [--visible]

``--visible`` opens a real window instead of the offscreen one (window size, display scaling
and the compositor then count, as in daily use; it takes the screen while it runs).
"""

import argparse
import asyncio
import json
import os
import shutil
import subprocess
import tempfile
import time
import urllib.request
from pathlib import Path

import websockets
from qa_editor import PNG, Cdp

from paper_pile.core.index import Index
from paper_pile.core.vault import Vault

REPO = Path(__file__).resolve().parent.parent
PORT = int(os.environ.get("SOAK_PORT", "9453"))
TABS = "document.querySelectorAll('.pp-tabstrip .pp-tab').length"
DIALOG = "!!document.querySelector('.q-dialog .q-card, .q-dialog__inner > div')"
RICH = 8

RICH_BODY = """# Rich {i}

Some **bold** text, a [[n{i}]] link, a #tag and inline math $a^2 + b^2 = c^{i}$.

$$
\\int_0^{i} x^2 \\, dx = \\frac{{{i}^3}}{{3}}
$$

```mermaid
graph TD
  A{i}[Start] --> B{i}{{Choice}}
  B{i} -->|yes| C{i}[Done]
  B{i} -->|no| A{i}
```

| col a | col b | col c |
|---|---|---|
| {i} | x | y |
| z | {i} | w |

![pic](.rich{i}.assets/p.png)

```python
def f{i}(x):
    return x * {i}
```

- [ ] a task
- [x] a done task
"""


def make_vault(vault: Path, notes: int) -> list[str]:
    para = "Plain text with a [[link]] and some words in it. " * 5
    for i in range(notes):
        folder = vault / f"folder{i % 20:02d}"
        folder.mkdir(parents=True, exist_ok=True)
        (folder / f"n{i}.md").write_text(f"# Note {i}\n\n" + (para + "\n\n") * 6)
    names = []
    for i in range(RICH):
        (vault / f".rich{i}.assets").mkdir()
        (vault / f".rich{i}.assets" / "p.png").write_bytes(PNG)
        (vault / f"rich{i}.md").write_text(RICH_BODY.format(i=i))
        names.append(f"rich{i}")
    tabs = [f"folder{i % 20:02d}/n{i}.md" for i in range(6)]
    (vault / ".paper-pile").mkdir()
    (vault / ".paper-pile" / "session.json").write_text(
        json.dumps({"tabs": tabs, "active": tabs[0]})
    )
    index = Index(Vault(vault))
    index.sync()
    index.close()
    return names


def rss_mb(pid: int) -> float:
    try:
        for line in Path(f"/proc/{pid}/status").read_text().splitlines():
            if line.startswith("VmRSS:"):
                return int(line.split()[1]) / 1024
    except OSError:
        pass
    return 0.0


def processes(pgid: int) -> dict[str, float]:
    """RSS (MB) by role of every process in the app's process group."""
    out = {"renderer": 0.0, "window": 0.0, "server": 0.0}
    for d in Path("/proc").iterdir():
        if not d.name.isdigit():
            continue
        try:
            if os.getpgid(int(d.name)) != pgid:
                continue
            cmd = (d / "cmdline").read_bytes().replace(b"\0", b" ").decode(errors="replace")
        except (OSError, ProcessLookupError):
            continue
        if "QtWebEngineProcess" in cmd:
            if "--type=renderer" in cmd:
                out["renderer"] += rss_mb(int(d.name))
        elif "multiprocessing" in cmd and "spawn_main" in cmd:
            out["window"] += rss_mb(int(d.name))
        elif "bin/paper-pile" in cmd:
            out["server"] += rss_mb(int(d.name))
    return out


async def key(cdp: Cdp, k: str, code: int, ctrl: bool = True) -> None:
    for t in ("rawKeyDown", "keyUp"):
        await cdp.call(
            "Input.dispatchKeyEvent",
            type=t,
            key=k,
            windowsVirtualKeyCode=code,
            modifiers=2 if ctrl else 0,
        )


async def until(cdp: Cdp, cond: str, secs: float = 10) -> bool:
    end = time.time() + secs
    while time.time() < end:
        if await cdp.js(f"!!({cond})"):
            return True
        await asyncio.sleep(0.05)
    return False


async def open_note(cdp: Cdp, name: str) -> bool:
    n = await cdp.js(TABS)
    await key(cdp, "o", 79)
    if not await until(cdp, DIALOG):
        return False
    await asyncio.sleep(0.2)
    await cdp.call("Input.insertText", text=name)
    await asyncio.sleep(0.6)
    await key(cdp, "Enter", 13, ctrl=False)
    return await until(cdp, f"{TABS} > {n}")


async def one_round(cdp: Cdp, names: list[str]) -> int:
    base = await cdp.js(TABS)
    misses = 0
    for name in names:
        misses += not await open_note(cdp, name)
        await asyncio.sleep(1.0)  # let diagrams / math render
    for _ in range(len(names) + 2):
        await key(cdp, "Tab", 9)
        await asyncio.sleep(0.4)
    await key(cdp, "p", 80)
    await until(cdp, DIALOG)
    await key(cdp, "Escape", 27, ctrl=False)
    await asyncio.sleep(0.4)
    xy = await cdp.js(
        "(() => { const r = document.querySelector('.pp-tree-row')?.getBoundingClientRect(); return r && [r.x + 20, r.y + r.height / 2]; })()"
    )
    if xy:
        for t in ("mousePressed", "mouseReleased"):
            await cdp.call(
                "Input.dispatchMouseEvent", type=t, x=xy[0], y=xy[1], button="right", clickCount=1
            )
        await asyncio.sleep(0.4)
        await key(cdp, "Escape", 27, ctrl=False)
        await asyncio.sleep(0.3)
    while await cdp.js(TABS) > base:
        n = await cdp.js(TABS)
        await key(cdp, "w", 87)
        if not await until(cdp, f"{TABS} < {n}"):
            misses += 1
            break
        await asyncio.sleep(0.2)
    return misses


async def page_metrics(cdp: Cdp) -> dict[str, float]:
    await cdp.call("HeapProfiler.collectGarbage")
    await asyncio.sleep(0.5)
    r = await cdp.call("Performance.getMetrics")
    m = {x["name"]: x["value"] for x in r["metrics"]}
    return {
        "heap": m["JSHeapUsedSize"] / 1e6,
        "nodes": m["Nodes"],
        "listeners": m["JSEventListeners"],
        "docs": m["Documents"],
    }


async def run(pgid: int, names: list[str], rounds: int) -> None:
    for _ in range(1200):
        try:
            pages = json.load(urllib.request.urlopen(f"http://127.0.0.1:{PORT}/json", timeout=1))
            url = next(p["webSocketDebuggerUrl"] for p in pages if p.get("type") == "page")
            break
        except (OSError, StopIteration):
            await asyncio.sleep(0.1)
    else:
        raise SystemExit("the app never opened a page")
    async with websockets.connect(url, max_size=None) as ws:
        cdp = Cdp(ws)
        await cdp.call("Performance.enable")
        await until(cdp, "document.querySelectorAll('.cm-line').length > 3", 120)
        await asyncio.sleep(3)
        print(
            f"{'round':>5} {'heap MB':>8} {'nodes':>7} {'listen':>7} {'docs':>5} {'renderer':>9} {'window':>7} {'server':>7}  misses"
        )

        async def row(label: str, misses: int | str = "") -> None:
            m = await page_metrics(cdp)
            p = processes(pgid)
            print(
                f"{label:>5} {m['heap']:8.1f} {m['nodes']:7.0f} {m['listeners']:7.0f} {m['docs']:5.0f} {p['renderer']:9.0f} {p['window']:7.0f} {p['server']:7.0f}  {misses}",
                flush=True,
            )

        await row("start")
        for i in range(1, rounds + 1):
            misses = await one_round(cdp, names)
            await asyncio.sleep(1)
            await row(str(i), misses)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--rounds", type=int, default=12)
    ap.add_argument("--notes", type=int, default=300)
    ap.add_argument("--keep", action="store_true", help="keep the throwaway folder")
    ap.add_argument("--visible", action="store_true", help="a real window, not offscreen")
    args = ap.parse_args()
    work = Path(tempfile.mkdtemp(prefix="pp-soak-"))
    vault = work / "vault"
    vault.mkdir()
    names = make_vault(vault, args.notes)
    env = {
        **os.environ,
        "XDG_CONFIG_HOME": str(work / "xdg"),
        "XDG_STATE_HOME": str(work / "state"),  # or the user's "last vault" points here
        "XDG_CACHE_HOME": str(work / "cache"),
        "QTWEBENGINE_CHROMIUM_FLAGS": f"--remote-debugging-port={PORT}",
    }
    if not args.visible:
        env["QT_QPA_PLATFORM"] = "offscreen"
    with (work / "app.log").open("w") as out:
        app = subprocess.Popen(
            [str(REPO / ".venv" / "bin" / "paper-pile"), str(vault)],
            cwd=REPO,
            env=env,
            stdout=out,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    try:
        asyncio.run(run(app.pid, names, args.rounds))
    finally:
        os.killpg(app.pid, 15)
        try:
            app.wait(5)
        except subprocess.TimeoutExpired:
            os.killpg(app.pid, 9)
        if args.keep:
            print("kept:", work)
        else:
            shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    main()
