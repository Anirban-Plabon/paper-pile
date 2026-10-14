# paper-pile — Tracker

> Updated by Claude Code after every task, error, or requirement change
> (protocol in CLAUDE.md). Never delete log entries.

Legend: 🧠 = needs Opus (see PLAN §6 model guidance) · ⬜ todo · 🔄 in progress · ✅ done · ⛔ blocked · ⏭️ skipped/deferred

## Current focus
- **Phase:** P0 — Foundation
- **Task:** P1.2 (next; P0, P1.1 done)
- **Next up:** P1.3 → P1.4 → P1.5

## Open issues
<!-- - [ ] YYYY-MM-DD · task ID · what's blocking · what's needed -->
- (none)

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
| P1.2 | core/vault.py | ⬜ | |
| P1.3 | 3-pane layout | ⬜ | |
| P1.4 | Tree + context menu + drag | ⬜ | |
| P1.5 | Watcher | ⬜ | |

### P2 — Editor, tabs, preview
| ID | Task | Status | Notes |
|---|---|---|---|
| P2.1 | Editor + autosave + recovery | ⬜ | |
| P2.2 | Tabs (no preview tab, restore) | ⬜ | changed 2026-10-14 |
| P2.3 | Parser + dollar rule | ⬜ | |
| P2.4 🧠 | Live Preview decorations + Source toggle | ⬜ | changed 2026-10-14; highest cost |
| P2.5 | External-change handling | ⬜ | |
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
