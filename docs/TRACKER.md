# paper-pile — Tracker

> Updated by Claude Code after every task, error, or requirement change
> (protocol in CLAUDE.md). Never delete log entries.

Legend: 🧠 = needs Opus (see PLAN §6 model guidance) · ⬜ todo · 🔄 in progress · ✅ done · ⛔ blocked · ⏭️ skipped/deferred

## Current focus
- **Phase:** P0 — Foundation
- **Task:** P2.6 (next; P0, P1, P2.1–P2.5 done)
- **Next up:** P3.1 → P3.2 → P3.3 → P3.4 → 🧠 P3.5

## Open issues
<!-- - [ ] YYYY-MM-DD · task ID · what's blocking · what's needed -->
- (none)  <!-- 2026-10-14 · P2.5 external edits: resolved (content-hash sync + conflict banner), see Decision log -->

## Task status

### P0 — Foundation
| ID | Task | Status | Notes |
|---|---|---|---|
| P0.1 | uv project, pyproject, tooling | ✅ | deps pinned exact; `mypy` config targets `paper_pile/core` (created in P0.2) |
| P0.2 | Repo skeleton | ✅ | `preview.py` kept as widget-rendering helpers (live preview, no split pane) |
| P0.3 | events + config | ✅ | 12 tests; config saves only changed layer values, corrupt file ignored + `.bak` on save |
| P0.4 🧠 | Spike S1 — editor component | ✅ | own CM6 bundle chosen; all 7 acceptance items verified in headless Chrome (18 checks) |
| P0.5 🧠 | Spike S2 — block widgets (display math + mermaid) in editor, offline | ✅ | 17 browser checks + parser check; requests to non-127.0.0.1 aborted during test |
| P0.6 | Spike S3 — native mode + shortcuts | ✅ | 12/12 shortcuts delivered on Qt X11 backend; Wayland-native launches OK, keys unverified → manual QA item in PLAN checklist | |

### P1 — Shell & vault
| ID | Task | Status | Notes |
|---|---|---|---|
| P1.1 | CLI + --serve token | ✅ | 42 tests; all 4 forms verified for real (serve: token/cookie/host/ws; native `.`: window process + server up); closing-window-exits-app left to P1.3 manual QA |
| P1.2 | core/vault.py | ✅ | 81 tests total (39 new); safety rules mutation-checked (overwrite, trash, symlink escape) | |
| P1.3 | 3-pane layout | ✅ | 85 tests; 21 browser checks (Chrome) + 12 checks inside the native QtWebEngine window (via CDP); compositor-level keys on Wayland still manual | |
| P1.4 | Tree + context menu + drag | ✅ | 107 tests (+22 core); 39 browser checks with real mouse/keyboard + 6 in the native window; tab/editor wiring comes via bus events in P2 | |
| P1.5 | Watcher | ✅ | 130 tests (+23); 22 browser checks, all changes visible in 160–180 ms; 5 checks in the native window | |

### P2 — Editor, tabs, preview
| ID | Task | Status | Notes |
|---|---|---|---|
| P2.1 | Editor + autosave + recovery | ✅ | 147 tests (+17 core); 41 browser checks incl. real `kill -9` crash recovery; 5 in the native window; S1/S2 suites still green. Known gap → open issue for P2.5 | |
| P2.2 | Tabs (no preview tab, restore) | ✅ | 163 tests (+16 core); 62 browser checks; P2.1/S1/S2 suites still green; 10 checks in the native window incl. real Ctrl+Tab/Ctrl+W and a full relaunch restore |
| P2.3 | Parser + dollar rule | ✅ | 215 tests (+52); `core/parser.py`; math rules shared with the editor via a 33-case fixture checked by pytest and by the Lezer grammar; also verified in the running app | |
| P2.4 🧠 | Live Preview decorations + Source toggle | ✅ | 296 Python tests; 101 browser checks on one gallery note (all elements) + 53 shared grammar cases; S1 18, S2 17, P2.1 41, P2.2 62, layout 21 still green; 14 checks in the native window incl. real Ctrl+E/Ctrl+Z, lazy language chunk and relaunch; perf p95 ≤ 14 ms on 5,000 lines |
| P2.5 | External-change handling | ✅ | 315 tests (+19 core); 39 browser checks with a separate process editing files; native 7 checks; P2.1/P2.2/gallery suites still green | |
| P2.6 | .txt plain mode | ⬜ | |

### P3 — Links & index
| ID | Task | Status | Notes |
|---|---|---|---|
| P3.1 | Wikilink plugin | ⬜ | |
| P3.2 | SQLite index + FTS | ⬜ | |
| P3.3 | Resolve + navigate + create-on-missing | ⬜ | |
| P3.4 | Backlinks pane | ⬜ | |
| P3.5 🧠 | Rename-safe rewriting | ⬜ | |

### P4 — Slash menu
| ID | Task | Status | Notes |
|---|---|---|---|
| P4.1 | Command registry | ⬜ | |
| P4.2 🧠 | Notion-style popup | ⬜ | |
| P4.3 | Phase-1 commands + note picker | ⬜ | |

### P5 — Images
| ID | Task | Status | Notes |
|---|---|---|---|
| P5.1 | assets.py + lifecycle | ⬜ | |
| P5.2 | Paste / drop / picker | ⬜ | |
| P5.3 | Drag-resize | ⬜ | |
| P5.4 | Tree hide + vault-op integration | ⬜ | |

### P6 — Smart Paste
| ID | Task | Status | Notes |
|---|---|---|---|
| P6.1 | Collect fixtures | ⬜ | needs user samples |
| P6.2 | html_to_md + normalize | ⬜ | |
| P6.3 | Wire in + raw paste + toggle | ⬜ | |

### P7 — AI
| ID | Task | Status | Notes |
|---|---|---|---|
| P7.1 | Provider + Ollama + health | ⬜ | |
| P7.2 | Chat pane | ⬜ | |
| P7.3 | Context builder + @note | ⬜ | |
| P7.4 | AI slash commands | ⬜ | |

### P8 — Settings, theme, profile
| ID | Task | Status | Notes |
|---|---|---|---|
| P8.1 | Theme system | ⬜ | |
| P8.2 | Settings dialog + persistence | ⬜ | |
| P8.3 | Profile block + theme toggle | ⬜ | |

### P9 — Navigation & polish
| ID | Task | Status | Notes |
|---|---|---|---|
| P9.1 | Palette + switcher | ⬜ | |
| P9.2 | Vault search | ⬜ | |
| P9.3 | Outline panel | ⬜ | |
| P9.4 | Status bar | ⬜ | |
| P9.5 | Shortcuts | ⬜ | |
| P9.6 | Final QA + README | ⬜ | |

## Decision log
<!-- YYYY-MM-DD · decision · reason · (who: user / claude) -->
| Date | Decision | Reason | By |
|---|---|---|---|
| 2026-10-13 | GUI first (NiceGUI + pywebview[qt]), TUI later | Mermaid + live editing need a web renderer | user |
| 2026-10-13 | Phase 1 targets Ubuntu desktop only; RHEL/server later | Reduce scope | user |
| 2026-10-13 | `core/` UI-agnostic; `--serve` kept working | Future TUI + server/teams | planning |
| 2026-10-13 | AI = Ollama only, behind Provider protocol | Local-first; cloud can slot in later | user |
| 2026-10-13 | Images in hidden per-note `.<stem>.assets/`, hash names, `![alt\|w](path)` | Traceless + portable; base64 only for future export | user |
| 2026-10-13 | Smart Paste on by default, Ctrl+Shift+V raw | Chatbot paste must not break math | user |
| 2026-10-13 | Notion-style `/` menu, registry in Python, thin JS popup | Matches reference screenshot; logic stays in Python | user |
| 2026-10-13 | Multiple note tabs required | User requirement | user |
| 2026-10-14 | Python 3.12 via uv (`.python-version`), not system 3.14 | Matches PLAN; safest wheels for Qt/pywebview | user |
| 2026-10-14 | `git init` (branch `main`) | Commit convention needs git | user |
| 2026-10-14 | Default Ollama model for dev/testing: `gemma4:12b` | User choice; installed locally | user |
| 2026-10-14 | Pinned exact versions: nicegui 3.18.0, pywebview[qt] 6.2.1, markdown-it-py 4.2.0, mdit-py-plugins 0.6.1, watchdog 6.0.0, beautifulsoup4 4.15.0, markdownify 1.2.3, ollama 0.6.3, tomli-w 1.2.0, platformdirs 4.13.0, pillow 12.3.0; dev: pytest 9.1.1, pytest-asyncio 1.4.0, ruff 0.17.0, mypy 2.4.0 | PLAN §2 requires pins | claude |
| 2026-10-14 | Config layers saved separately (global/vault), atomic writes, unparseable TOML ignored with warning and backed up to `.bak` before overwrite; `EventBus` is synchronous and swallows+logs handler errors | Never lose user settings; UI must not break core | claude |
| 2026-10-14 | Marked P0.4, P0.5, P2.4, P3.5, P4.2 as 🧠 Opus-needed (design in plan mode; `/model opus` if stuck). All other tasks stay on Sonnet | Session uses opusplan; reserve Opus for CM6-internals and data-corruption-risk work | user |
| 2026-10-14 | S1: own esbuild CM6 bundle + thin NiceGUI element; built-in `ui.codemirror` rejected | Built-in has Python-driven decorations (per-keystroke round trip), no lang-markdown/GFM or Lezer extensions, hard-wired basicSetup | claude |
| 2026-10-14 | S1: pasted images go via HTTP POST route, text/HTML via websocket; browser owns buffer, Python edits via explicit methods | socket.io `max_http_buffer_size` is 1 MB; avoid clobbering typing | claude |
| 2026-10-14 | npm pins (exact): codemirror 6.0.2, @codemirror/{state 6.7.6, view 6.43.14, commands 6.11.1, language 6.13.1, search 6.7.2, lang-markdown 6.5.2}, @lezer/{markdown 1.8.0, highlight 1.2.5}, katex 0.19.0, esbuild 0.28.2 (dev). Bundle + KaTeX css/fonts committed under `static/vendor/` | PLAN §2 requires pins; end users need no Node | claude |
| 2026-10-14 | S2: block widgets (`$$` math, ```` ```mermaid ````) from a CM6 StateField, source revealed when the selection touches the block; `BlockMath` Lezer block parser in math.js | CM6 forbids line-spanning/block replace decorations from a ViewPlugin | claude |
| 2026-10-14 | S2: Mermaid 12.2.0 pinned, bundled via esbuild `--splitting` into lazy chunks (committed, ~6 MB under `vendor/pp-editor/`); renders serialized, `parse` before `render` (no mermaid error graphic), SVG cache keyed by theme+source | Offline, main bundle stays ~0.8 MB, mermaid global state is not concurrency-safe | claude |
| 2026-10-14 | Editor/widget CSS lives in `static/app.css` (moved out of the spike page) | Single place; P8.1 will drive it from CSS variables | claude |
| 2026-10-14 | S3: native mode = `pywebview[qt]`, launched with `PYWEBVIEW_GUI=qt`; keep Qt's default (Wayland) backend, do not force xcb | xcb needs 8 apt libs (not pip-only); default backend works out of the box | claude |
| 2026-10-14 | S3: shortcuts via one capture-phase `keydown` listener + `preventDefault`, forwarded to Python; compare `e.key.toLowerCase()` | Verified all PLAN §4.14 shortcuts reach the page; Shift makes `e.key` uppercase | claude |
| 2026-10-14 | P1.1: last vault stored in `platformdirs.user_state_dir("paper-pile")/last_vault.json` (not the config dir) | It is state, not a setting the user edits | claude |
| 2026-10-14 | P1.1: no vault + no last vault → terminal prompt (error if non-interactive); missing path is an error, never auto-created. Native folder picker deferred to P1.3 | Data safety: a typo must not create folders; GUI picker needs the layout | claude |
| 2026-10-14 | P1.1: `--serve` auth = `TokenGate` ASGI middleware (query token → HttpOnly SameSite=Strict cookie, loopback Host check, 401/403, ws close 1008); native mode has no token in phase 1 | Covers HTTP + websockets + static; also protects the S1 image-paste route | claude |
| 2026-10-14 | P1.2: trash layout `.trash/<timestamp-µs>/<original rel path>`; vault API refuses hidden/escaping/non-note paths and never overwrites; non-UTF-8 notes raise instead of lossy decode; symlinks escaping the vault are hidden/refused | Data safety (CLAUDE rule 4), web-mode path traversal, no silent corruption | claude |
| 2026-10-14 | P1.2: extracted `core/fsutil.atomic_write_bytes` (fsync + mode kept), `config.py` now uses it; PLAN §3 lists `fsutil.py` | One atomic-write implementation for vault and config | claude |
| 2026-10-14 | P1.3: layout = two nested px Quasar splitters (`gui/layout.py`); limits left 180–480 / right 280–640; collapse via Ctrl+B / Ctrl+L + status-bar toggle buttons (no drag-to-collapse); defaults 260/340; state in `session.json` | Predictable, remembers width while collapsed; PLAN only said "collapsible, width remembered" | claude |
| 2026-10-14 | P1.3: `gui/shortcuts.py` intercepts only registered combos (Ctrl+C/V/F/Z etc. pass through); P9.5 just adds entries | S3 spike intercepted every Ctrl combo, which would break editing | claude |
| 2026-10-14 | P1.3: `session.json` schema: `panes_open` added, `preview_mode: "split"` replaced by `mode: "live"/"source"`; PLAN §5 and §4.2 diagram updated (diagram still showed a split preview) | Matches the no-preview-pane decision | claude |
| 2026-10-14 | P1.4: file-tree logic lives in `core/vault.py` (`validate_name`, `note_filename`, `join_rel`, `create_note_in`, `create_folder_in`, `rename_in_place`, `move_into`); GUI is thin (rows + `static/tree.js` event delegation + dialogs) | Core logic gets unit tests; same ops reusable by a future TUI | claude |
| 2026-10-14 | P1.4: flat indented rows, children listed only while expanded; expansion not persisted yet; no virtualisation, keyboard nav, F2/Delete keys or multi-select | Keep P1.4 to the PLAN scope; revisit if large vaults feel slow | claude |
| 2026-10-14 | P1.4: tree publishes `tree.open`, `vault.renamed`, `vault.deleted` on `MainLayout.bus` (core `EventBus`); center pane temporarily shows "Opened: <path>" | Tabs/editor (P2) subscribe instead of the tree knowing about them | claude |
| 2026-10-14 | P1.4: "Reveal in file manager" only in native mode (`xdg-open` on the folder) | In `--serve` mode it would act on the server, not the user's machine (CLAUDE rule 7: web fallback) | claude |
| 2026-10-14 | P1.5: one `VaultWatcher` per process publishing batched `vault.fs_changed(events=[FsEvent])` on an app-level bus; pages subscribe and unsubscribe on disconnect; 150 ms debounce window from the first event; `dispatch` callback keeps `core` UI-free (GUI passes `loop.call_soon_threadsafe`) | watchdog runs on its own thread; NiceGUI elements must be touched on the loop; multiple pages in `--serve` mode | claude |
| 2026-10-14 | P1.5: watcher ignores hidden paths, non-notes and folder-modified noise; moves into/out of `.trash` map to deleted/created; the app's own writes echo back and are not suppressed (P2.5 must detect its own saves) | Matches what the tree shows; keeps the watcher simple and stateless | claude |
| 2026-10-14 | P2.1: autosave = editor reports at 0.3 s + 0.7 s timer (~1 s); immediate on blur, Ctrl+S, note switch, page disconnect; failed save retried every 5 s | Spec says ~1 s debounce; never leave edits only in the browser | claude |
| 2026-10-14 | P2.1: `NoteBuffer` (core) owns dirty/save/recovery rules; `EditorPane` (GUI) only owns timing and dialogs; saving never recreates a note deleted on disk | Core logic is unit-tested; an autosave must not undo an external delete/move | claude |
| 2026-10-14 | P2.1: `setText(text, docId)` — events carry the doc id and stale ones are dropped; `setText` builds a fresh CM state (resets undo history) | A late change or Ctrl+Z must never move text between notes (data-corruption risk) | claude |
| 2026-10-14 | P2.1: recovery entries are one JSON per note named by a hash of the path; startup dialog Restore/Discard/Later; opening a note with a pending entry asks again | Crash safety per PLAN §4.5; user decides, nothing is overwritten silently | claude |
| 2026-10-14 | P2.1: deleting the open note through the tree discards its buffer instead of saving it | The file is in `.trash/`; saving would resurrect it | claude |
| 2026-10-14 | P2.2: tab logic in `core/tabs.py` (`TabList`); one `NoteBuffer` + one parked CM6 state per tab; new tab appended at the end; close → right neighbour else left; same-name tabs show the folder | Unit-testable rules; per-tab undo/cursor; matches VS Code/Obsidian habits | claude |
| 2026-10-14 | P2.2: web-mode shortcut fallbacks Alt+W / Alt+PageDown / Alt+PageUp (shortcut layer accepts Alt-only combos); Ctrl+W/Ctrl+Tab stay for native | Browsers reserve Ctrl+W/Ctrl+Tab (S3 fallback rule); keeps `--serve` usable (CLAUDE rule 7) | claude |
| 2026-10-14 | P2.2: restore skips vanished notes silently, activates the last restored tab if the saved active one is gone; recovery dialog comes after the restore | A stale session must not produce a wall of errors | claude |
| 2026-10-14 | P2.2: opening an already-open note only focuses its tab (no recovery re-prompt); the on-open recovery prompt applies to notes not yet open | A pending draft is already offered at startup; prompting on every focus would be noise | claude |
| 2026-10-14 | P2.3: the Python parser (markdown-it + `dollarmath`) is the reference for math semantics; the editor's Lezer grammar was changed to match it (first-closing-`$`-decides, no digit before the opening `$`, inline `$$x$$`, unclosed/blank-line `$$` blocks are text, block may follow a paragraph line) and a shared fixture `tests/fixtures/math_cases.json` is checked by pytest and `tools/editor_src/check_math.mjs` (run by `build_editor.sh`) | PLAN demanded the two stay in sync; Python renders the real output | claude |
| 2026-10-14 | P2.3: parser config: raw HTML escaped (`html=False`), `breaks=True`, GFM tables + strikethrough, task lists, footnotes, front matter; `$$` made able to interrupt a paragraph by wrapping the plugin rule (it ignores `silent`) | Safe output for chat/export; newline rendering matches the editor; friendlier for pasted chat text | claude |
| 2026-10-14 | P2.3: new dependency `PyYAML==6.0.3` pinned explicitly (was only present transitively) + dev `types-pyyaml==6.0.12.20260906`; PLAN §2 updated | Front matter parsing; CLAUDE.md requires pinning new deps | claude |
| 2026-10-14 | P2.4: reveal granularity = element-level for inline syntax (only the touched element turns raw), line-level for prefixes (`#`, `>`, list/task markers, rules), block-level for widgets (table, math, mermaid, front matter, code fences) | Obsidian-like: editing one link must not un-render the rest of the line | claude |
| 2026-10-14 | P2.4: remote images are never fetched (chip instead); vault images are served by token-protected `/_pp/asset` backed by `Vault.asset_path` (images only, `.<stem>.assets` the only hidden folder, SVG sandboxed) | CLAUDE rules 5/7 (offline, web mode) and privacy (no tracking pixels) | claude |
| 2026-10-14 | P2.4: code highlighting decided: CodeMirror/Lezer language packages, curated set, each lazily loaded (esbuild chunk per language); PLAN §2 row updated and pinned | PLAN said "decide in P2, log it"; keeps highlighting inside the editor, bundle small | claude |
| 2026-10-14 | P2.4: tables render as a widget and are edited in the source (revealed while the caret is inside); no inline cell editing in phase 1 | Largest simplification that still meets "tables render in place" | claude |
| 2026-10-14 | P2.4: front matter contract simplified to `---` / next exact `---` at the very top, in both Python (own rule replacing the plugin's, which also accepted `----`, text after dashes and a `...` closer) and the editor grammar; shared fixture `front_matter_cases.json` | Two grammars must agree; the plugin's quirks are not worth copying | claude |
| 2026-10-14 | P2.4: a freshly opened note starts with its caret below front matter; Ctrl/Cmd+click on links acts on `mousedown`; Ctrl+E / status-bar label toggle Live↔Source and persist in `session.json`; web mode opens links in the page, native mode via Python (`webbrowser`), only http/https/mailto | UX details found while testing | claude |
| 2026-10-14 | P2.4: footnotes (`[^1]`) stay plain text in the editor (Lezer GFM has no footnote support); Python still renders them | Out of scope for phase 1; logged as a limit | claude |
| 2026-10-14 | P2.4: new npm pins (exact): @codemirror/lang-{javascript 6.2.5, python 6.2.1, json 6.0.2, html 6.4.12, css 6.3.1, sql 6.10.0, rust 6.0.2, cpp 6.0.3, java 6.0.2, go 6.0.1, yaml 6.1.3}, @codemirror/legacy-modes 6.5.5; `check_math.mjs` → `check_sync.mjs`, `test_math_sync.py` → `test_grammar_sync.py` | CLAUDE.md: pin new dependencies | claude |
| 2026-10-14 | P2.5: outside changes are resolved by **content hash** against what the app last saved/loaded (`NoteBuffer.sync_with_disk`), not by event kind; outcomes unchanged / reloaded / conflict / gone / conflict-gone | The watcher echoes the app's own saves, tools save by rename (delete+create), `touch` changes nothing; only content tells | claude |
| 2026-10-14 | P2.5: clean buffer reloads silently (caret kept, undo history reset, no toast); dirty buffer + different disk = conflict banner (Keep mine / Load theirs; deleted: Keep editing / Close and discard); autosave and retries are off while a conflict is open | PLAN §4.5; never overwrite either side silently | claude |
| 2026-10-14 | P2.5: the losing side of every conflict choice is stashed in `.trash/<stamp>/…(changed on disk | my unsaved edits).md` first (`Vault.stash_text`) | CLAUDE rule 4 (never hard-delete user data) | claude |
| 2026-10-14 | P2.5: a clean note deleted outside closes its tab (toast); a note moved outside keeps its tab under the new path; "diff" view not built | Simplest behaviour that is safe; diff is a later nicety | claude |
| 2026-10-14 | P2.1 suite section H updated: an open note deleted outside now yields the banner (status "Changed on disk") instead of "Save failed" + toast | Behaviour intentionally replaced by P2.5 | claude |
| 2026-10-14 | uv_build backend with `module-root = ""` (flat `paper_pile/` layout, not `src/`) | PLAN §3 layout | claude |
| 2026-10-13 | Preview-tab (VS Code style) behaviour as default | Chosen during planning, unconfirmed — ask user if unsure | planning |
| 2026-10-13 | Split preview in phase 1; inline live preview deferred | Inline needs CM6 decorations, highest cost | planning |
| 2026-10-14 | **SUPERSEDES the two rows above.** No preview tab. Every note (new or existing) edits in Obsidian-style Live Preview (single pane, syntax hides off-cursor); Source mode toggle via Ctrl+E; no split preview pane. Inline live preview moves from Deferred into phase 1 (S1/S2, P2.4, P5.3) | User: "not vs code like, like obsidian" | user |
| 2026-10-13 | Vault RAG deferred; phase 1 context = selection, note, @note, open tabs, linked notes | MVP scope | planning |

## Issues log
<!-- YYYY-MM-DD · task · symptom → root cause → fix · (gotcha added? y/n) -->
| Date | Task | Symptom | Root cause | Fix | Gotcha? |
|---|---|---|---|---|---|
| 2026-10-14 | P0.6 | Native window failed to start with `QT_QPA_PLATFORM=xcb`: "Could not load the Qt platform plugin xcb" | Qt ≥ 6.5 xcb plugin needs system libs `libxcb-cursor0`, `libxcb-icccm4`, `libxcb-keysyms1`, `libxcb-xkb1`, `libxkbcommon-x11-0` (+ image/render-util/util) which are not in pip wheels | For the test only: `apt download` the .debs, extract into a scratch dir, `LD_LIBRARY_PATH`. For the app: don't force xcb (default Wayland backend works) | y — pending: CLAUDE.md is read-only, so not yet added to its Gotchas |
| 2026-10-14 | P2.5 | After **Load theirs** the note still showed "Save failed" and a dirty dot | An earlier failed save left `buffer.error` set; resolving the conflict (and reloading, and adopting an identical disk version) never cleared it | Clear `error` in `load_theirs`, `keep_mine`, the reload path and the identical-text path; regression test | y — pending: CLAUDE.md read-only |
| 2026-10-14 | P2.5 | Test "clean reload within a second" failed although the editor showed the new text; caret test failed | Test mistakes: mangled string escaping in the expected text; the needle for the caret position was not in the note | Fixed in the test | n |
| 2026-10-14 | P2.4 | Ctrl+click on a link opened nothing | CodeMirror's own Ctrl+click handling adds a selection on `mousedown`; the link becomes "touched", its DOM is rebuilt and the original element is gone before `click` would fire | Handle the link on `mousedown` and swallow it | y — pending: CLAUDE.md read-only |
| 2026-10-14 | P2.4 | Clicking a checkbox then Ctrl+Z did nothing | `mousedown.preventDefault()` keeps focus where it was; if the editor was not focused, undo never reached it | `view.focus()` after the toggle | y — pending: CLAUDE.md read-only |
| 2026-10-14 | P2.4 | Bullets/numbers sat 6 px left of the text; quote padding and bars were ignored | Our line `padding-left` replaced CodeMirror's default 6 px line padding, and `.cm-line`'s own rule out-specified `.pp-quote` | Add the 6 px to the hanging indent; scope quote rules as `.pp-editor .cm-line.pp-quote` | y — pending: CLAUDE.md read-only |
| 2026-10-14 | P2.4 | Colours from our CSS never beat a Quasar button's blue (earlier, P1.4), and in the editor the front-matter block opened raw | (a) NiceGUI's `!important` Quasar rules are in cascade layers; (b) the initial caret at 0 touches a block that starts at 0 | (a) `color=None`; (b) initial caret placed below front matter | n (a already noted) |
| 2026-10-14 | P2.4 | Many test failures were test-order artifacts: CodeMirror keeps only lines near the viewport in the DOM (blocks at the bottom of a long note were "missing"), listener attached too late, focus left on the status bar, `\n---\n` matching the front matter's closing line | Not app bugs | Harness gained `scrollTop/scrollEnd/focus`, global request listener, specific needles | n |
| 2026-10-14 | P2.3 | In the running app every formula showed twice (typeset + plain text) | The app page never loaded `vendor/katex/katex.min.css` (only the spike page did), so KaTeX's visually-hidden MathML copy was visible; found by looking at a screenshot — the DOM checks all passed | Link the KaTeX CSS in the page head; test now asserts the MathML copy is ≤ 2 px wide | y — pending: CLAUDE.md read-only |
| 2026-10-14 | P2.3 | `$$` block after a paragraph line produced 3 identical math blocks | `dollarmath`'s block rule ignores `silent`; registered as a paragraph terminator it emitted a token on every terminator check | Wrap the rule: in silent mode run it, delete the tokens, restore `state.line` | y — pending: CLAUDE.md read-only |
| 2026-10-14 | P2.3 | Editor and Python disagreed on 8 of 33 math cases (digit before `$`, stray-`$` scanning, `$$` inline, unclosed/blank-line blocks, …) | S1/S2 grammar was written from the PLAN prose, not from the engine that renders | Rewrote `math.js` to the engine's rules; fixture + check script keep them equal | n |
| 2026-10-14 | P2.2 | **Data-loss bug:** opening a *clean* note deleted that note's pending recovery draft (so restoring tabs at startup, or "Later" then open, silently destroyed the draft before it was offered) | `NoteBuffer.open()` always called `_mirror()`, which clears the store entry when the buffer is clean | `open()` mirrors only when the buffer is dirty; regression test `test_opening_a_clean_note_keeps_a_pending_recovery_draft` | y — pending: CLAUDE.md read-only |
| 2026-10-14 | P2.2 | Every tab switch raised "Something went wrong" and the active tab did not move | `ui.run_javascript` (scroll the active tab into view) needs a page slot context; EditorPane runs in background tasks | Use the element's own client: `self._bar.client.run_javascript(...)` | y — pending: CLAUDE.md read-only |
| 2026-10-14 | P2.2 | P2.1 suite had 3 failures after tabs landed | Expectations of the old single-editor model (Ctrl+Z rewinds across a switch; deleting the only note shows the empty state; re-opening an open note re-prompts) | Updated to tab semantics; invariants (no cross-note text, no resurrection, draft offered) unchanged | n |
| 2026-10-14 | P2.2 | Drag tests timed out | Test positions fell on the splitter handle (first 4 px of the first tab) or outside the 700 px tab bar | Drop at x=14 / x=600 | n |
| 2026-10-14 | P2.1 | After **Restore**, the recovered text was shown but never reached the disk | Autosave is triggered by editor change events; a restored buffer is dirty from the start and the editor reports no change for `setText`, so no save was ever scheduled | `open()` schedules a save when the opened buffer is already dirty | y — pending: CLAUDE.md read-only |
| 2026-10-14 | P2.1 | Test helper `.cmView.view` was undefined | CodeMirror 6.43 renamed its DOM handle to `cmTile.root.view` | Test reads `cmTile?.root?.view ?? cmView.view` (test-only) | n |
| 2026-10-14 | P2.1 | Several test failures turned out to be test mistakes: reading the document from the DOM (Live Preview hides markdown marks off-cursor), clicking Restore on the wrong row (oldest entry first), injecting recovery files under a name the app does not use | Not app bugs | Read text from the editor state; target the row; inject with the hashed file name | n |
| 2026-10-14 | P1.4 | Context menu drew *under* the splitter line, clipped to the left pane | `position: fixed` inside a Quasar splitter panel is still inside that panel's stacking context | `with ui.teleport("body")` for the menu | y — pending: CLAUDE.md read-only |
| 2026-10-14 | P1.4 | Menu labels stayed Quasar-blue and Delete was not red although my CSS had higher specificity and `!important` | NiceGUI ships Quasar's `!important` colour rules inside CSS cascade layers; for `!important`, *layered* beats *unlayered* regardless of specificity, so app CSS can never override a Quasar colour class | Don't give the element a colour class: `ui.button(..., color=None)` | y — pending: CLAUDE.md read-only |
| 2026-10-14 | P1.4 | `move_into("d", "d/sub")` test expected "into itself" but got "not a folder" | `d/sub` did not exist yet, so the missing-folder check correctly came first | Test the real case (`d` into `d`, and into an existing descendant) | n |
| 2026-10-14 | P1.3 | Collapsed pane still measured 24 px wide | `.pp-pane` had 12 px side padding; a box with `width:100%` of 0 never gets narrower than its padding (clipped, but not 0) | Pane has no padding and `overflow:hidden`; padding moved to an inner `.pp-pane-body` | y — pending: CLAUDE.md read-only |
| 2026-10-14 | P1.3 | "Ctrl+B is intercepted" test failed although the shortcut worked | The gate calls `stopPropagation()`, so the test's own bubble-phase listener never ran | Test uses `dispatchEvent()`'s return value (false when `preventDefault` was called) | n |
| 2026-10-14 | P1.3 | `xdotool` keys sent to the native window had no effect (worked in S3) | Desktop-level key injection on Wayland/XWayland is focus-dependent and not reliable | Verified inside the native renderer instead: QtWebEngine exposed via `QTWEBENGINE_REMOTE_DEBUGGING=9222`, raw CDP `Input.dispatchKeyEvent`/mouse events (Playwright cannot attach: no browser-context support) | n |
| 2026-10-14 | P1.1 | `test_websocket_with_cookie_ok` got `WebSocketDisconnect` although cookie was valid | Starlette `TestClient` neither replays its cookie jar nor uses `base_url`'s host on websocket handshakes (sends `Host: testserver`, rejected by the loopback check) — test artifact, gate was right | Pass `host` + `cookie` headers explicitly in websocket tests | n |
| 2026-10-14 | P0.6 | `xdotool key` reached nothing in the Qt window | `windowactivate` did not move keyboard focus under XWayland; page handler itself was fine (proved with a synthetic key from headless Chrome) | `xdotool windowfocus <id>` + click into the page first | n (test tooling only) |

## Session log
<!-- YYYY-MM-DD · tasks completed · short note -->
- 2026-10-13 · planning · CLAUDE.md, PLAN.md, TRACKER.md created
- 2026-10-14 · requirement change · no preview tab, Obsidian-style Live Preview (PLAN + Decision log updated)
- 2026-10-14 · P0.1 · uv project, pinned deps, ruff/mypy/pytest config, CLI stub with --help
- 2026-10-14 · P0.2 · skeleton per PLAN §3; ruff + mypy(core) green
- 2026-10-14 · P0.3 · core/events.py + core/config.py with unit tests (merge order, save round-trip)
- 2026-10-14 · plan · marked 🧠 Opus tasks in PLAN §6 and TRACKER
- 2026-10-14 · P0.4 · editor spike: CM6 live preview (headings/emphasis/code/strike hide off-cursor, inline KaTeX widget, pandoc dollar rule), slash/paste hooks, Python↔JS API, 2 MB image paste; verified with headless Chrome via scratch playwright-core (not a project dep)
- 2026-10-14 · P0.5 · display math + mermaid block widgets in editor, reveal-on-cursor, theme re-render, offline verified; S1 checks still green
- 2026-10-14 · P0.6 · native-window spike: 12/12 shortcuts delivered (Qt X11 backend via injected keys); Wayland-native launches, manual QA noted; **P0 complete**
- 2026-10-14 · P1.1 · CLI (4 forms), last-vault memory, vault path validation, `.paper-pile/` init, `--serve` TokenGate; 42 tests green; verified with curl + headless Chrome + native launch
- 2026-10-14 · P1.2 · core/vault.py (tree, read/write, create, rename/move, delete→trash, duplicate) + fsutil; 81 tests green
- 2026-10-14 · P1.3 · 3-pane layout (resize, limits, collapse, persistence), status bar + chat stubs, shortcuts module; native lifecycle checked: ending the window process exits the app cleanly (exit 0, no leftovers)
- 2026-10-14 · P1.4 · file tree: lazy expand, context menu, create/rename/duplicate/delete→trash, drag-move, native-only Reveal; 107 tests green; verified with real mouse input in Chrome and in the native window
- 2026-10-14 · P1.5 · core/watcher.py + live tree refresh; **phase P1 complete** (CLI, vault, layout, tree, watcher); 130 tests green
- 2026-10-14 · P2.1 · NoteBuffer + RecoveryStore (core), EditorPane (autosave/blur/Ctrl+S/switch/disconnect, retry, recovery dialog), save indicator; found+fixed restore-never-saved bug; 147 tests; verified in Chrome (incl. kill -9) and native window
- 2026-10-14 · P2.2 · TabList (core) + TabBar + multi-buffer EditorPane + per-tab editor state; close/cycle/reorder/dirty dot/restore/rename-delete follow; found+fixed recovery-draft deletion bug; 163 tests; verified in Chrome and in the native window incl. relaunch
- 2026-10-14 · P2.3 · core/parser.py (GFM, front matter, math, safe HTML), shared math fixture + Lezer check, KaTeX css fix in the app page; 215 tests; verified in the running app
- 2026-10-14 · P2.4 · Live Preview complete: element-level reveal, headings/inline styles, lists + hanging indent, tasks, quotes, rules, links (Ctrl+click), images via asset route, front matter, code blocks with lazy highlighting, tables, Source toggle (Ctrl+E); shared grammar fixtures; 296 Python tests; 101 + regression browser checks; native window verified incl. relaunch
- 2026-10-14 · P2.5 · external-change handling: NoteBuffer.sync_with_disk + stash_text (core), EditorPane.on_external + conflict banner + resolutions; closes the open issue; 315 tests; 39 browser + 7 native checks
