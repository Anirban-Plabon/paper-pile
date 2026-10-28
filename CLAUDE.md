# CLAUDE.md — paper-pile

You are building **paper-pile**: a local, Obsidian-like markdown note app with a
Cursor-clean 3-pane UI and built-in local AI (Ollama). Read this file fully at the
start of every session. It is short on purpose; details live in `docs/`.

## Source of truth
| File | Purpose | Who edits |
|---|---|---|
| `CLAUDE.md` | Rules, conventions, gotchas | You, via the update protocol below |
| `docs/PLAN.md` | Spec + phased task list with acceptance criteria | You, only when a requirement changes |
| `docs/TRACKER.md` | Live status, decisions, issues, session log | You, after every task |

If code and docs disagree, **stop and reconcile** — never let them drift silently.

## Session start ritual
1. Read `CLAUDE.md` → `docs/TRACKER.md` (Current focus + Open issues) → relevant phase in `docs/PLAN.md`.
2. Run `uv run pytest -q` to confirm the baseline is green. If red, fixing it is task #1.
3. State in one line which task ID you are picking up.

## Living-docs update protocol (MANDATORY)
Apply these after every task, error, or user instruction. Do it in the same commit as the code.

| Trigger | Update |
|---|---|
| Task started | TRACKER: status → `🔄 in progress`, set Current focus |
| Task finished (acceptance criteria met + tests green) | TRACKER: status → `✅ done`, add Session log line |
| Task blocked | TRACKER: status → `⛔ blocked`, add Open issue with reason |
| Error that took >1 attempt to fix | TRACKER: Issues log entry (symptom → root cause → fix). If the lesson applies beyond this one bug, add a line to **Gotchas** below |
| User changes / adds a requirement | PLAN: edit the spec + affected tasks. TRACKER: Decision log entry (date, change, reason) + add/modify task rows |
| You deviate from PLAN for a technical reason | TRACKER: Decision log entry. PLAN: update so it describes reality |
| Spike resolves an unknown | PLAN: replace the "spike" note with the chosen approach. TRACKER: Decision log |
| New dependency added | PLAN §Stack table + TRACKER Decision log (pin the version) |

Never mark a task done without its acceptance criteria verified. Never delete Issues/Decision log entries — they are history.

## Architecture rules (non-negotiable)
1. **`paper_pile/core/` has zero UI imports.** No `nicegui`, no `textual`. A future TUI must reuse core unchanged. If core needs to "notify the UI", use callbacks/events defined in core.
2. **Plain files are the source of truth.** SQLite (`.paper-pile/index.db`) is a cache that must be fully rebuildable from the vault. Never store note content only in the DB.
3. **The app owns asset lifecycle.** Any rename/delete/duplicate of a note must handle its `.<stem>.assets/` folder and fix references.
4. **Never hard-delete user data.** Deletes go to `<vault>/.trash/`.
5. **No CDN.** All JS/CSS (CodeMirror, KaTeX, Mermaid) is vendored under `paper_pile/gui/static/vendor/` and served locally. App must work fully offline.
6. **JS is a thin layer.** JS only renders/captures (editor, popup menus, paste events). Logic, parsing, command registry, AI all live in Python.
7. **`--serve` mode must keep working** (web mode, bind `127.0.0.1` only). Don't introduce native-only code paths without a web fallback.

## Conventions
- Python ≥ 3.12, managed with **uv**. Run everything via `uv run ...`.
- Lint/format: `ruff check --fix` and `ruff format`. Type hints everywhere; `mypy paper_pile/core` should pass.
- Tests: `pytest`. Core logic needs unit tests. UI gets a manual QA checklist per phase (in PLAN) plus NiceGUI `User`-fixture tests where cheap.
- Small commits, message format: `P<phase>.<task>: <what>` e.g. `P3.2: backlinks query`.
- Paths: always `pathlib.Path`. Vault-relative paths in the index, POSIX style.
- No print-debugging left behind; use `logging` (logger name `paper_pile.<module>`).
- Keep functions small; one module = one responsibility.

## Commands
```bash
uv sync --extra ai               # install deps (plain `uv sync` = no AI)
uv run paper-pile .              # run native window on current dir as vault
uv run paper-pile --serve ~/n    # web mode on 127.0.0.1
uv run pytest -q                 # tests
uv run ruff check --fix && uv run ruff format
```

## When unsure
Ask the user a **short** question instead of guessing on anything that changes the spec, file format, or data safety. For pure implementation details, pick the simplest option, log it in the Decision log, and continue.

## Gotchas
<!-- Append one line per durable lesson: `- <area>: <lesson>` -->
- NiceGUI User tests: need `@pytest.mark.nicegui_main_file(<file calling ui.run()>)` (see `tests/gui/nicegui_main.py`); `user.should_see(text)` also matches tooltips, so wait on a word only the dialog has.
- Icons: Quasar renders `svguse:` as `<i class=q-icon><svg><use>` (style `.q-icon svg use`, not `.q-icon > use`), and a button's icon is 1.7× the button's font-size — set icon sizes on `.q-icon`, never on the button.
- UI checks: when driving the real app (native or `--serve`), set `XDG_CONFIG_HOME` AND `XDG_STATE_HOME` to ABSOLUTE scratch dirs, or settings land in the user's real `~/.config/paper-pile` and the throwaway vault becomes the user's "last vault".
- CSS vs Quasar: Quasar utility classes (`.block`, `.hidden`, …) are layered `!important`, which beats our unlayered `!important` — work around them (size/overflow), don't fight them.
- CodeMirror tooltips (slash menu, autocomplete) get CM's light theme from `.ͼ2 .cm-tooltip`, injected after app.css — theme them with `.cm-editor .cm-tooltip…` (higher specificity), not a bare class.
- Quasar textareas: `.q-field__control-container` has 2 px padding and dense `.q-field__native` a 36 px `min-height` — zero/override both (and use a whole-pixel line-height) when a field must match a fixed button height.
- WSL: WSLg reports every monitor at scale 1 whatever Windows uses; the real per-monitor scale only comes from Windows (`core/display.py`). Don't trust Qt's devicePixelRatio/physical DPI there.
- Never open this repo (or `tests/fixtures`) as a vault: auto-title adds `title:` front matter to every `.md` it opens and silently changes fixtures. A test failure is never "pre-existing" until its cause is known.
- Git on `/mnt/*` (drvfs): files touched by Windows tools come back CRLF (`.gitattributes` keeps LF canonical) and `git update-index --refresh` may not clear stale entries — compare `git hash-object` with the index blob before believing `git status`.
- Editor bundle: never keep per-editor state in module globals — a page can hold two editors (split view). Use the runtime facet (`rtOf(view.state)` in `context.js`).
- After `tools/build_editor.sh`, restart the app: NiceGUI serves the bundle as a cached ES module, so a page reload keeps the old code.
- Qt from another thread (`native_boot.py`): a QObject that receives a queued signal must be kept referenced (`_KEEP`), or the call is silently dropped.
- UI tests: never drive the app on a vault the user may use. Before a test run, check which vault the user's own app has open (`ls -l /proc/<pid>/fd | grep index.db`) and test on a fresh COPY. Isolating `XDG_CONFIG_HOME` does not isolate the vault.
- Two editors (split): never read "the active tab's text" from `self._editor` — use `EditorPane._live_text(tab_id)` (the editor checks it shows that doc), or one note's text gets saved under another.
- Scripted edits: read then write (`s = p.read_text(); …; p.write_text(s)`), never `open(p,'w')` in the same expression as a read — it truncates first. Uncommitted work has no backup when edited by scripts: keep a copy (`cp f f.bak`) before editing a large uncommitted file.
- WSL: Qt's `availableGeometry()` is the whole monitor (the Windows taskbar is unknown to WSLg); size windows against the work area from `core/display.py`.
- Editor widgets: anything with a large min-content width (nowrap chips, long values) widens the whole CodeMirror content and makes the note scroll sideways — give such containers `min-width: 0` + `contain: inline-size`.
- CodeMirror layout: never put vertical `margin` on editor lines or block widgets (CM does not measure margins; clicks drift) — use padding or an outer spacer. A widget whose size changes after it is drawn must call `measureAgain(view)` (`context.js`), not just `requestMeasure()`.
- Run `uv run python tools/qa_editor.py` after any editor CSS/JS change (it starts its own throwaway vault; ~6 min).
- UI checks: click with real mouse events (CDP `Input.dispatchMouseEvent`, check `document.elementFromPoint`), never JS `el.click()` — it skips hit-testing, so a button covered by another element still "works".
- Markdown lazy lines: a line without `>`/indent right under a quote or list line still belongs to it (the `Blockquote`/`ListItem` node spans it). Decorate from the node's lines, not from `QuoteMark`s, and never leave the caret on a line directly under a block the user just "left".
- Editor line CSS: padding on a line class (`.pp-h1 { padding }`) loses to `.pp-editor .cm-line { padding }` — write it as `.pp-editor .cm-line.<class>` and check the computed value.
- Qt on Wayland (WSLg): `windowStateChanged` arrives BEFORE the new size (use `heightChanged` to measure), and never `resize()` a window while the compositor may still have it maximized — it is a protocol error that kills the app.
- markdown-it block rules: `state.parentType` is not reliable (`lheading` leaves it at `"paragraph"` when it fails); test top level with `state.level == 0`.
- Editor bundle: after moving code between modules, grep the old module for every moved name — esbuild bundles an undefined identifier without a word and it only throws at runtime (a throwing widget breaks the whole view update).
- CodeMirror: a plugin/field that stays in a reconfigured Compartment keeps its instance (constructor not re-run); react to facet changes in `update()` (compare `u.startState.facet` / `u.state.facet`).
- Qt WebEngine in a dev tool (not the app) as root: `QApplication(sys.argv[:1])` and `QTWEBENGINE_DISABLE_SANDBOX=1`, or Chromium refuses to start.
- HTML5 drag & drop: a drop target's `dropEffect` must be one the drag source's `effectAllowed` permits (tree rows and tabs use `'move'`), or `drop` never fires. Test drags with CDP `Input.setInterceptDrags` + `dispatchDragEvent`; plain mouse events don't start an HTML5 drag.
- Settings rows stack by a CSS container query on their box (`ppbox`), not by JS — keep it that way. In general, layout state set by JS from measured positions must not change what was measured: a class that lets a field shrink can make the row fit again and flip forever. Keep sizes that decide wrapping (min-width) the same in both states, and re-measure per element with a ResizeObserver.
- Date fields: never use a native `<input type=date>` — its calendar icon and popup ignore our theme (dark mode, rounded popups). Use `ui.date` in a `ui.menu` (`.pp-date-popup`, see `memories.py`).
- CodeMirror keymaps: the first binding for a key wins — a key the default keymap already binds (Mod-Enter, Mod-h…) must be listed BEFORE `...defaultKeymap`.
- Popups: Quasar places a `ui.menu` once, at open — a menu filled on `before-show` is still empty then. `static/menus.js` re-places menus on resize and keeps them above `--pp-inset-bottom`; a new popup kind that is not a `.q-menu`/`.pp-ctxmenu` must get the same (Quasar and CodeMirror only know `innerHeight`, which includes the strip under the WSL taskbar).
- NiceGUI handlers run in the slot of the element that fired. If the handler deletes that element (redrawing a tab strip, a list), wrap any later UI work in `with <live element>:` — otherwise `RuntimeError: The parent element this slot belongs to has been deleted`.
- Editor tooltips (slash menu, autocomplete) are clipped by the editor pane: `tooltipSpace` (index.js) keeps them inside the editor's box. A real-click check must confirm `elementFromPoint` hits the target — a covered button looks clickable in a script.
- NiceGUI async handlers: pass the coroutine function as `on_click` (NiceGUI awaits it in the element's slot). `background_tasks.create(...)` runs without a slot, so any `ui.*` it builds (a dialog) fails with "slot stack … is empty".
- CSS: a right-aligned flex row (`justify-content: flex-end`) overflows to the LEFT, where `scrollWidth` does not see it (and nothing scrolls to it). Use `safe flex-end` when overflow must be measured (tabs.js icons-only) or reachable.
- CodeMirror widgets that should animate a state change (fold chevron, checkbox tick) must implement `updateDOM` and keep their element — otherwise CM swaps the DOM, transitions never run, and on-create keyframes replay every time a line scrolls into view.
- Motion: durations come from `--pp-dur*` tokens (× `--pp-motion`); JS animations read `motionFactor()` (`motion.js`). Never hard-code a transition time, and animate only opacity/transform — never a size CodeMirror measures.
- Real-pages QA in the 800 px offscreen test window: the sheet column is a few px wide (each line wraps ~180 px tall), so page edges are far off-screen — fold both side panes (Ctrl+B, Ctrl+L) before checking them.
- Popups that get their content late (slash menu, Python results) must not be placed before it arrives: keep the tooltip box at its full size (transparent wrapper) and hide the menu until the first results, or it opens on one side and jumps.
- WSL + several monitors: if Windows places a monitor at negative y (above / left of the main one), WSLg maximizes windows into the wrong strip (clipped at Windows' y = 0, then shifted). Check `~/.cache/paper-pile/monitors.json` (`top` < 0) before debugging the app's window code.
- UI-path work (tab switch, refresh, anything per keystroke or per event) runs on NiceGUI's one event loop: it must not walk the vault, read many files, fsync, or wait for `Index._lock` held by a background sync — every request (even icon files) waits behind it. Use the index, mtime caches and debounced writes; measure with `tools/perf_ui.py` (`--loop-debug` names the blocking callbacks).
- WSL performance: `/mnt/*` (9p drvfs) makes imports ~10× and vault walks ~45× slower than the Linux file system, and a distro whose Mesa lacks `d3d12` (e.g. RHEL) renders with llvmpipe. Check both before blaming app code for lag.
- Killing test instances: `pgrep -f` / `pkill -f` patterns match your own shell's command line — use the bracket trick (`'[p]p-perf-'`) and kill by process group (`kill -9 -- -<pgid>`); a leftover app keeps the CDP port, and the next run silently measures the old instance.
- Dialogs: always `paper_pile.gui.dialog.Dialog`, never `ui.dialog` — NiceGUI 3.16+ leaves a hidden canary element per dialog that keeps the whole deleted dialog alive (page + server). A dialog made anew per use must also be deleted (after `await`, or on `hide`).
- Memory: find leaks with `tools/mem_soak.py` (identical rounds must level off) and CDP heap snapshots diffed by constructor; user-timing entries (`performance.mark`) are never freed by the browser — Tailwind's runtime makes them, `static/marks.js` clears them.
- Note header (P21): each editor side has its own split / AI / ⋯ buttons. They act on "the active note", so build their actions with `EditorPane._side_actions(slot)` (focuses that side first) — a plain `note_actions(self)` would act on the other side's note.
- GUI classes are not type-checked (mypy covers `core/` only): before adding an attribute to a big component (`EditorPane`, `Layout`), grep `self._<name>` — a clash silently overwrites one of them.
