# paper-pile — Spec & Build Plan

> Living document. When a requirement changes, edit this file and log it in
> `docs/TRACKER.md` → Decision log (see CLAUDE.md protocol).

---

## 1. Vision
A local note app for one power user (phase 1), later teams. Obsidian's
file-based vault + Cursor's clean 3-pane layout + Notion's `/` menu +
built-in local AI via Ollama. Plain `.md`/`.txt` files, no lock-in.

**Phase-1 target:** Ubuntu desktop, single user, native window.
**Later:** web/server mode (RHEL, SSH tunnel), TUI (Textual), teams.

**Differentiators:** AI truly built in (local), Smart Paste for chatbot text
(math-safe), traceless images, Mermaid + math out of the box.

---

## 2. Stack

| Concern | Choice | Notes |
|---|---|---|
| Python / env | Python 3.12, `uv` | pin in `pyproject.toml` |
| UI framework | NiceGUI (latest stable, pin exact) | native mode via pywebview |
| Native window | `pywebview[qt]` (PyQt6 + QtWebEngine) | S3 result: Qt's default **Wayland** backend is pip-only and works. Launch with `PYWEBVIEW_GUI=qt` (skips the noisy GTK probe). Forcing the X11 backend (`QT_QPA_PLATFORM=xcb`) needs apt libs: `libxcb-cursor0 libxcb-icccm4 libxcb-keysyms1 libxcb-xkb1 libxkbcommon-x11-0 libxcb-image0 libxcb-render-util0 libxcb-util1` |
| Editor | CodeMirror 6 (own esbuild bundle: `@codemirror/lang-markdown` GFM + Lezer inline-math extension + live-preview plugin), custom NiceGUI element | S1 result: NiceGUI's built-in `ui.codemirror` rejected (Python-side decorations round-trip per keystroke; no lang-markdown/GFM or Lezer extensions; hard-wired `basicSetup`). Pinned npm versions in `tools/editor_src/package.json` |
| Markdown parse | `markdown-it-py` + `mdit-py-plugins`, `PyYAML` 6.0.3 (front matter; dev: `types-pyyaml`) | front_matter, dollarmath, tasklists, footnote, table, strikethrough; raw HTML escaped; + custom wikilink plugin (P3.1) |
| Math render | KaTeX 0.19.0 (vendored, client-side) | CM6 widget in the editor; CSS + fonts in `static/vendor/katex/` |
| Diagrams | Mermaid 12.2.0 (bundled by esbuild into lazy chunks under `static/vendor/pp-editor/chunks/`, client-side) | CM6 block widget; loads on first diagram; `securityLevel: strict`; renders serialized + SVG-cached; theme `default`/`dark` |
| Icons | Lucide 1.49.0 (`lucide-static`, ISC; all icons in `static/vendor/lucide/icons.json`, built by `tools/editor_src/build_icons.mjs` from `tools/build_editor.sh`; licence kept) | **One icon style app-wide (user request 2026-10-17):** every icon is a Lucide line icon, 1.75 stroke, sizes 14/16/18 px (`--pp-icon-s/m/l`). Served at `/_pp/icon/<name>.svg` and used as Quasar `svguse:` names (`gui/icons.py`: `ico`, `line_icon`, `icon_button`, `set_icon`); plain DOM uses `ppIconSvg` (`static/icons.js`), which also maps Quasar's own Material icons (select arrows, clear crosses, uploader, notifications) via `IconSet.iconMapFn`. Slash commands name Lucide icons. Font Awesome and the filled Material icons are no longer used (Font Awesome removed) |
| Code highlight | CodeMirror language packages, lazily loaded (`@codemirror/lang-javascript` 6.2.5, `-python` 6.2.1, `-json` 6.0.2, `-html` 6.4.12, `-css` 6.3.1, `-sql` 6.10.0, `-rust` 6.0.2, `-cpp` 6.0.3, `-java` 6.0.2, `-go` 6.0.1, `-yaml` 6.1.3, `@codemirror/legacy-modes` 6.5.5) | Decided in P2.4: highlighting happens inside the editor (Lezer), so no second highlighter and no server round trip; one esbuild chunk per language |
| Index / search | stdlib `sqlite3` + FTS5 | `.paper-pile/index.db`, rebuildable |
| File watching | `watchdog` | external edits |
| HTML → MD (paste) | `beautifulsoup4` + `markdownify` | custom converters for math/code |
| AI | `ollama` (official python lib, AsyncClient) | behind a `Provider` protocol |
| Config | `tomllib` (read) + `tomli-w` (write) + `platformdirs` | |
| Images | `Pillow` | dimension read, format normalize |
| Tests | `pytest`, `pytest-asyncio` | |
| Lint | `ruff`, `mypy` (core) | |

Dev-only: Node + `esbuild` to build the CodeMirror bundle once (`tools/build_editor.sh`).
The built bundle is committed, so end users never need Node.

---

## 3. Repository layout

```
paper-pile/
├── CLAUDE.md
├── pyproject.toml              # [project.scripts] paper-pile = "paper_pile.cli:main"
├── docs/
│   ├── PLAN.md
│   └── TRACKER.md
├── tools/
│   ├── build_editor.sh         # esbuild CodeMirror bundle → gui/static/vendor/
│   ├── editor_src/             # JS source: index.js (createEditor), grammar.js (+ math.js, frontmatter.js), livepreview.js, blocks.js, widgets.js, codelang.js, reveal.js, context.js; check_sync.mjs
│   ├── spike_editor.py         # S1/S2 demo page (dev-only, not shipped)
│   └── spike_native.py         # S3 native-window shortcut test (dev-only)
├── paper_pile/
│   ├── cli.py                  # arg parsing, launch native/serve
│   ├── core/                   # ZERO UI imports
│   │   ├── fsutil.py           # atomic_write_bytes (shared by vault + config)
│   │   ├── vault.py            # file ops, tree, trash, rename/move
│   │   ├── assets.py           # image storage, lifecycle, orphan sweep
│   │   ├── parser.py           # markdown-it setup (GFM, front matter, math), render → HTML, front_matter()
│   │   ├── links.py            # extract links, resolve, rewrite on rename
│   │   ├── index.py            # SQLite: notes, links, FTS
│   │   ├── watcher.py          # watchdog → events
│   │   ├── tabs.py             # TabList: open/close/move/rename/cycle bookkeeping
│   │   ├── commands.py         # slash command registry + actions
│   │   ├── paste.py            # Smart Paste: html→md, delimiter normalize
│   │   ├── config.py           # global + vault TOML, defaults
│   │   ├── session.py          # open tabs, last vault, restore
│   │   ├── buffer.py           # NoteBuffer: dirty tracking, save rules, recovery mirror
│   │   ├── recovery.py         # .paper-pile/recovery store (unsaved buffers)
│   │   ├── events.py           # simple pub/sub so core can notify UIs
│   │   └── ai/
│   │       ├── provider.py     # Provider protocol
│   │       ├── ollama.py       # OllamaProvider
│   │       └── context.py      # context building + token budget
│   └── gui/
│       ├── app.py              # routing, startup (native / serve)
│       ├── layout.py           # 3-pane frame: splitters, collapse, persistence
│       ├── shortcuts.py        # capture-phase keydown → Python (registered combos only)
│       ├── security.py         # --serve token gate (ASGI)
│       ├── files.py            # /_pp/asset route: images referenced from notes
│       ├── theme.py            # light/dark/system, accent palette, CSS vars
│       ├── components/
│       │   ├── tree.py         # left pane
│       │   ├── tabs.py         # tab bar (render + clicks); no preview-tab logic
│       │   ├── editor.py       # NiceGUI element wrapping CM6
│       │   ├── editor_pane.py  # center pane: open note, autosave timing, recovery prompts
│       │   ├── pp_editor.js    # thin Vue wrapper for the element
│       │   ├── preview.py      # rendered HTML + mermaid/katex post-render
│       │   ├── backlinks.py
│       │   ├── chat.py         # right pane, collapsible
│       │   ├── statusbar.py
│       │   ├── palette.py      # Ctrl+P command palette, Ctrl+O switcher
│       │   └── settings.py     # settings dialog + bottom-left profile
│       └── static/
│           ├── vendor/         # pp-editor/ (cm6 bundle + mermaid chunks), katex/ (committed)
│           ├── tree.js         # click / right-click / drag-drop capture for the file tree
│           ├── tabs.js         # drag-to-reorder capture for the tab bar
│           └── app.css
└── tests/
    ├── core/
    ├── fixtures/
    │   ├── vaults/             # tiny sample vaults
    │   └── paste/              # real chatbot clipboard HTML samples
    └── gui/
```

---

## 4. Feature specs

### 4.1 CLI
```
paper-pile                # open last vault (or prompt to pick folder)
paper-pile .              # current dir = vault
paper-pile <path>         # given dir = vault
paper-pile --serve [path] [--port 8080]   # web mode, 127.0.0.1 only, prints URL with token
```
- `--serve` generates a random token per run (`secrets.token_urlsafe(16)`) and prints `http://127.0.0.1:<port>/?token=…`. Enforced by `gui/security.py` (`TokenGate`, pure ASGI): every HTTP request and websocket handshake needs `?token=` or the `pp_token` cookie (HttpOnly, SameSite=Strict, set on the first valid visit), else 401 (websocket closes 1008). `Host` must be `127.0.0.1`/`localhost` (403 otherwise, blocks DNS-rebinding). Bound to `127.0.0.1` only, never configurable. `--port` is only valid with `--serve` (1–65535, default 8080).
- Native mode (no `--serve`) uses NiceGUI's own random localhost port and no token (phase 1; revisit for multi-user).
- Vault resolution: explicit path (`~` expanded, must be an existing directory — a typo errors with exit 2, it never creates folders) → else the last vault if it still exists → else, on a terminal, prompt for a folder; non-interactive with no last vault is an error. The last vault is remembered in `<user_state_dir>/last_vault.json` (`core/session.py`). A native folder-picker for first run arrives with the layout (P1.3).
- **Open vault** (user request 2026-10-21): a folder-open button left of Settings in the profile row; above Settings in the folded icon column; and an "Open vault" button on the empty-editor screen. It opens a dialog with the recent vaults (newest first, up to 8, the open one left out; `last_vault.json` keeps `recent`) and a folder browser ("Folders") listed by Python (`core/folders.py`: visible subfolders, a "vault" badge on folders that have `.paper-pile/`, a path field, Up), so it works the same in the native window and in `--serve` mode; the native window also has a "Browse" button (the system folder picker). No explanatory text (user 2026-10-21). Opening a folder saves every open note and the session first, then the same process switches over (`gui/vault_host.py`: the watcher and the image/embed routes follow the new vault, every open page reloads onto it, the window title changes) and it becomes the last vault. Any existing folder can be opened; `.paper-pile/` is created in it.
- Creates `<vault>/.paper-pile/` on first open (index.db, vault.toml, session.json).

### 4.2 Layout
```
┌────────────┬──────────────────────────────────┬──────────────┐
│ Dir tree   │ [tab][tab*][tab]                 │  AI chat     │
│            │ editor (Live Preview, one pane)  │  (collapsible│
│            │                                  │   Ctrl+L)    │
│            │ ── backlinks ─────────────────── │              │
├────────────┤                                  │              │
│ 👤 ⚙️ ☀️    │ status: words · Ln/Col · saved · ollama ●        │
└────────────┴──────────────────────────────────┴──────────────┘
```
- Panes resizable (splitters). Left pane collapsible (Ctrl+B), right pane collapsible (Ctrl+L), width remembered.
- **Implementation (P1.3, `gui/layout.py`):** two nested px-sized Quasar splitters (outer: left | rest, inner: center | right with `reverse`), status bar under center + chat. Defaults 260 px / 340 px; limits while open: left 180–480, right 280–640 (dragging stops at the limits; collapse is by Ctrl+B / Ctrl+L or the collapse button in the Files header / the chat toggle at the right end of the tab strip, not by dragging). **Native window (2026-10-17):** frameless — no OS title bar. The top row of every column is the title bar: left cell = hide-tree button + `paper-pile — <vault>`, tab strips in the middle and right, and minimize / maximize / close at the top right (`gui/window.py`, `static/window.js`, `gui/native_boot.py`; drag from empty space in the top rows, double-click maximizes, resize from any edge or corner. Move/resize are handed to the compositor with `QWindow.startSystemMove/startSystemResize`, because Wayland ignores a program's own `move()`). `--serve` mode is unchanged (browser chrome, no window buttons). While the left pane is folded a 40 px icon column stays at the window's left edge: expand, search, new folder, new note (top to bottom). A collapsed pane is exactly 0 wide, keeps its last width, and is disabled for dragging. Widths and open/closed state are saved per vault in `.paper-pile/session.json` (resize debounced 0.4 s, toggles immediately) and restored on every page load. Empty states only: the tree (P1.4), tabs/editor (P2), chat (P7) and the profile block at the bottom of the left pane (P8.3) plug into these slots.
- **Screen scale on WSL (2026-10-17):** WSLg reports every monitor at 100 %, so a Linux window looks smaller on a Windows monitor scaled to 125/150 %. In the native window on WSL, `core/display.py` asks Windows (one PowerShell call, a few seconds, in the background; result cached in the user cache dir and shown first on the next start) for each monitor's rectangle and effective DPI, matches them to Qt's screens by geometry, and `gui/native_boot.py` sets the web view's zoom to that scale (divided by any scale Qt already applies), re-applies it when the window changes screen or a monitor is added/removed, and resizes the window by the same ratio so the page keeps its size — never beyond the monitor's work area (without the Windows taskbar, also read from Windows: WSLg reports the whole monitor as free). When WSLg maximizes a window over the taskbar (seen on the external monitor), the page leaves the covered strip empty (`--pp-inset-top/bottom` on `.pp-root`). Unknown screen → zoom 1. Outside WSL and in `--serve` mode nothing changes.
- Editing modes (single pane, Obsidian-style): **Live Preview** (default for every note, new or existing: markdown syntax hides on non-cursor lines, rendered inline) / **Source** (raw markdown). Toggle Ctrl+E. No split preview pane.
- Clean, minimal, Cursor-like: thin borders, no heavy chrome, monospace editor font.

### 4.3 Dir tree
- Shows `.md` and `.txt` files + folders. Hides dotfiles/dot-folders (`.paper-pile`, `.trash`, `.*.assets`).
- Context menu: new note, new folder, rename, delete (→ trash), duplicate, reveal in file manager.
- **Header (2026-10-16):** one row, as tall as the tab strip, with a collapse button, the "Files" title and three line-icon buttons (30 px hit area, 18 px icon, muted grey): **search** (swaps the tree for the 50 most recently modified notes, newest first, with a filter box; a click opens the note; press again to return to the tree), **new folder** (dialog: name, required, plus a *Location* picker over all folders that defaults to the vault top level) and **new note** (no dialog: `Untitled 1`, `Untitled 2`, … in the selected folder, the folder of the selected note, or the vault; opens at once). The context-menu *New note* is the same; *New folder* opens the same dialog with that folder preselected.
- Drag to move file/folder (move = rename → links + assets updated).
- **`core/vault.py` contract (P1.2):** `Vault(root)` takes vault-relative POSIX paths only. Absolute paths, `..`, backslashes, any dot-component (`.trash`, `.paper-pile`, `.*.assets`) and paths resolving outside the vault (symlink escapes) raise `InvalidPathError`. Files must be `.md`/`.txt`. Writes are atomic (`fsutil.atomic_write_bytes`: temp + fsync + replace, mode kept) and preserve CRLF; non-UTF-8 files raise instead of being decoded lossily. `create_note`/`create_folder`/`rename`/`duplicate` never overwrite (`ExistsError`). `list_tree(rel)` returns one level (lazy), folders first then notes, case-insensitive. `delete` moves to `.trash/<YYYY-MM-DDTHH-MM-SS-µs>/<original relative path>` (nothing is unlinked). `duplicate` makes `<name> copy`, `<name> copy 2`, … Asset folders and link rewriting are layered on by P3.5/P5.4.
- Lazy-loads large folders. Live-updates from watcher events.
- **Implementation (P1.4, `gui/components/tree.py` + `static/tree.js`):**
  - Rows are flat and indented by depth; a folder's children are listed (via `Vault.list_tree`) only while it is expanded, and expanded folders are remembered for the session (not persisted yet). `FileTree.refresh()` re-lists from disk and is what the watcher (P1.5) calls.
  - Single click on a folder toggles it; single click on a note selects it and publishes `tree.open`. No preview tab (see §4.4).
  - Context menu (right-click, on a row or on the empty area): folder → New note, New folder, Rename, Duplicate, Delete; note → Rename, Duplicate, Delete; empty area → New note, New folder; **Reveal in file manager is added in native mode only** (it would open a window on the server in `--serve` mode). The menu is teleported to `<body>`; Escape or an outside click closes it.
  - Names go through `core.vault`: `validate_name` (no `/`, `\`, leading dot, empty, >255 bytes), `note_filename` (adds `.md` unless `.md`/`.txt` typed). A new note is created straight away as `Untitled N` (no name prompt; `Vault.free_numbered_name`); the new-folder dialog asks for the name and a location. Rename shows a note's name without its extension and keeps the extension unless one is typed. Delete asks for confirmation and moves to `.trash/` (§4.9 lifecycle covers assets later). Duplicate → `<name> copy`.
  - Drag & drop: drop a note or folder on a folder row to move it there, or on the tree background to move it to the vault root; dropping on a note does nothing. Moves never overwrite; a folder cannot go into itself or a descendant; refusals show a toast.
  - Event bus topics (published on `MainLayout.bus`): `tree.open(path)`, `vault.renamed(old, new)` (rename or move; a folder path covers its children), `vault.deleted(path, trashed)`. Tabs (P2.2) subscribe to these.
  - **Live updates (P1.5, `core/watcher.py`):** one `VaultWatcher` per process (`watchdog`/inotify, recursive) publishes `vault.fs_changed(events=[FsEvent…])` on an app-level bus; each open page's `MainLayout` subscribes (and unsubscribes on disconnect) and calls `FileTree.refresh()` once per batch. `FsEvent(kind, path, is_dir, old_path)` with kind `created|deleted|modified|moved`, vault-relative POSIX paths. Dropped before publishing: hidden paths (`.trash`, `.paper-pile`, `.assets`, atomic-write temp files), non-note files, and folder "modified" noise. A move into `.trash/` is reported as `deleted`, out of it as `created`; renaming a note to/from a non-note extension is `deleted`/`created`. Raw events are coalesced over a 150 ms window that starts at the first event (a terminal change shows in the tree in ~0.2 s). `core` stays UI-free: the owner passes `dispatch` (the GUI uses `loop.call_soon_threadsafe`) so delivery happens on its own thread. The app's own writes also echo back as events (harmless for the tree; **P2.5 must recognise its own saves**, e.g. by content hash, and not treat them as external edits). If the OS refuses to watch (inotify limit) the app logs a warning and runs without live updates.
  - **Multi-select (P13.14):** Ctrl/Cmd+click toggles a row (no open, no expand), Shift+click selects the shown rows from the last clicked one, and a drag that starts on blank tree space (below the rows, the side insets) draws a selection box (Ctrl adds). A plain click on blank space clears the selection (a new note then goes to the vault root). Dragging a selected row moves the whole selection (rows inside a selected folder go with it; the drop folder itself stays put); right-clicking a selected row offers *Add N notes to chat* and *Delete N items* (one confirm). Rows hidden by collapsing drop out of the selection.
  - Not in P1.4: keyboard navigation, F2/Delete keys, persisted expansion, virtualised rows (the flat rows are rebuilt on every expand/refresh, not benchmarked on very large expanded folders).

### 4.4 Tabs
- Multiple note tabs.
- **No preview tabs** (user decision 2026-10-14). Clicking a note in the tree opens it in a normal tab, or focuses its tab if already open.
- Close: Ctrl+W, middle-click, × button. Cycle: Ctrl+Tab / Ctrl+Shift+Tab. Drag to reorder.
- `●` dirty marker if a save is pending or failed.
- Open tabs + active tab restored on relaunch (per vault, `session.json`).
- Rename/move of a note updates its tab; delete closes it.
- Clicking `[[link]]` opens in current tab; Ctrl+click opens a new tab.
- Later (not phase 1): split panes.
- **Implementation (P2.2):**
  - `core/tabs.py` `TabList` is the single source of truth: one tab per note; a new tab goes to the end; closing the active tab activates its **right neighbour, else the left**; closing a background tab changes nothing else; rename/move re-points tabs (a folder path covers its notes) keeping id, position and focus; ids are never reused. Tab chips show the file name plus the folder (dimmed) only when two open notes share a name.
  - Each tab has its own `NoteBuffer` and its own editor state in the browser (undo history, cursor), restored when you return to the tab; Ctrl+Z can never bring in another note's text. Leaving a tab saves it; closing saves it first (a failed save keeps the text in recovery).
  - Close with ×, middle-click, or the shortcut; drag a tab onto the left/right half of another to reorder, or onto the empty bar to move it to the end. A ● replaces the close button's place while a note has unsaved/failed-to-save text. Many tabs scroll horizontally and the active one is scrolled into view.
  - **Shortcuts:** Ctrl+W close, Ctrl+Tab / Ctrl+Shift+Tab cycle (wrapping) — these work in the native window. Web browsers reserve them, so **Alt+W, Alt+PageDown, Alt+PageUp** do the same everywhere (the shortcut layer now accepts Alt-only combos).
  - Session: `session.json` `tabs` + `active` are rewritten on every open/close/move/activate/rename. On launch the tabs reopen in order; notes that no longer exist are skipped quietly, and the active tab falls back to the last restored one. Crash recovery is offered afterwards and **Restore** puts the recovered text into the tab that is already open.
  - `vault.deleted` closes the tabs of the deleted note/folder without saving them (they are in `.trash/`).
### 4.5 Editor
- CodeMirror 6 with markdown language, syntax highlighting, line wrapping, search (Ctrl+F), undo/redo, multiple cursors.
- **Live Preview (default):** CM6 decorations render markdown inline as you type. Syntax markers (`**`, `#`, `[[ ]]`, link URLs, etc.) hide except on the line/selection with the cursor. Headings, bold/italic, lists, tasks (clickable checkbox), quotes, tables, links and images render in place; math (KaTeX) and Mermaid render as block/inline widgets that revert to source when the cursor enters them. The editor is the only pane for a note. Decoration logic is JS (render-only); parsing rules stay consistent with `core/parser.py`.
- **Python ↔ editor protocol (S1):** the browser owns the buffer. Python never sets text through reactive props; it calls `set_text` / `insert_at_cursor` / `set_mode` / `get_text` explicitly. Inserts apply at the JS-side cursor (no offset conversion, so no UTF-16 vs code-point bugs). Events to Python: `change` (full text, debounced 300 ms + flush on blur; API-made changes are not echoed), `slash` (line, ch, caret coords; not fired mid-word or in code/URL), `paste` (`html`+`text`, or image). Pasted images go over an HTTP POST route, not the websocket (socket.io caps messages at ~1 MB). Ctrl+Shift+V skips the hook (raw paste).
- Autosave: debounced 1 s after last keystroke + on tab switch/close/blur. Atomic write (temp file + rename).
  - **Implementation (P2.1):** the editor reports changes 0.3 s after typing stops, then a 0.7 s timer in `EditorPane` fires (~1 s total). Saved immediately on blur, Ctrl+S, switching notes (the freshest text is pulled with `get_text`) and when the page disconnects. A failed save keeps the text dirty, shows "Save failed" + a toast and is retried every 5 s. Status bar shows `Ready / Saved / Editing… / Save failed`.
  - `core/buffer.py` `NoteBuffer` decides *what* happens: dirty ⇔ content hash ≠ saved hash (undoing back to the saved text is clean again); every dirty state is mirrored to recovery; saving **never recreates a note that vanished from disk** (it fails and keeps the text) — so deleting or moving a note outside the app cannot be undone by an autosave.
  - Every `setText` carries a document id; events with an older id are ignored, so a late `change` can never be written into the wrong note. `setText` builds a fresh editor state, which also resets undo history (Ctrl+Z must never pull another note's text into this one).
  - Tree interplay: `vault.renamed` makes the open buffer follow the note; `vault.deleted` closes the editor and discards the buffer (the note is in `.trash/`).
- External change to an open file: if buffer clean → reload silently; if dirty → conflict banner (keep mine / load theirs / diff later).
  - **Implementation (P2.5):** the watcher's `vault.fs_changed` batch reaches every open page; `EditorPane.on_external` looks at the open notes it names (a folder event covers the notes inside it) and asks `NoteBuffer.sync_with_disk()`, which compares the disk's **content hash** with what the app last saved or loaded. So the echo of the app's own autosave, a `touch`, and a save-by-rename (vim and many tools delete and recreate the file) all resolve correctly by content, not by event kind.
  - Outcomes: *unchanged* (nothing to do); *reloaded* (clean buffer: the text is replaced silently, caret kept, no toast); *conflict* (unsaved edits here **and** a different version on disk); *gone* (clean note deleted/moved away: its tab closes with a toast); *conflict-gone* (unsaved edits, note deleted: asked). For the active tab the browser's latest text is pulled first, so keystrokes the server has not heard about yet still count as unsaved.
  - **A conflict never loses text:** the buffer keeps your version, refuses to save (autosave and retries stay off) and a banner above the editor offers **Keep mine** / **Load theirs** (for a deleted note: **Keep editing** — the next save recreates it — / **Close and discard**). The side that loses is first written to `.trash/<stamp>/<folder>/<name> (changed on disk).md` or `(my unsaved edits).md` (`Vault.stash_text`), and a toast says where. A background tab with a conflict gets a toast and a dot; its banner shows when you open it. "Diff" is not built (phase 1).
  - A note moved outside the app keeps its tab under the new path (same code as a rename in the tree). Notes that are not open are ignored. A note that became invalid UTF-8 is left alone (logged).
- Crash safety: unsaved buffer mirrored to `.paper-pile/recovery/` until saved.
  - **Implementation (P2.1, `core/recovery.py`):** one JSON file per note (`<sha256(path)[:20]>.json` with path, text, base hash, time), written on every reported change, removed on save. On start, entries that differ from disk (or whose note is gone) are offered in one dialog: **Restore** (opens the note with the recovered text as unsaved; autosave then writes it), **Discard**, or **Later** (kept). Opening a note that has a pending entry asks again. Nothing on disk is touched before the user chooses. The window of un-mirrored typing is ≤ 0.3 s (the editor's debounce).
- `.txt` files: plain text mode, no preview, no slash menu.
  - **Implementation (P2.6):** the kind follows the file extension (`core.vault.is_plain_text`, mirrored in the editor). A `.txt` note gets only the essentials: history, selection, line wrapping, search, Ctrl+S, and the change/blur events that drive autosave. It has **no** markdown grammar (so no rendering, no syntax colours), **no** slash trigger, no link/paste hooks, and front matter is just text. Tabs keep their own kind, so a `.md` and a `.txt` tab sit side by side; renaming across `.md`/`.txt` rebuilds the open tab in its new kind (undo history of that tab is reset). The status bar shows **Plain text** (not toggleable) while a `.txt` tab is active; Ctrl+E does nothing there and the chosen Live/Source mode is kept for the markdown tabs. A new note is `.md` unless you type `.txt`.

### 4.6 Markdown rendering (inline live preview; no separate preview pane)
- CommonMark + GFM tables, task lists, strikethrough, front matter (shown as a small properties block). **Footnotes** are rendered by the Python parser (chat, export) but are *not* recognised by the editor's grammar: `[^1]` stays plain text while editing (documented limit).
- **Live Preview implementation (P2.4)** — files in `tools/editor_src/`: `livepreview.js` (inline + line decorations), `blocks.js` (block widgets from a StateField), `widgets.js`, `frontmatter.js`, `codelang.js`, `reveal.js`, `grammar.js`.
  - **Reveal rules.** Inline elements (bold, italic, strike, inline code, links, images, inline math, escapes) show their raw syntax only while a selection range *touches that element* (inclusive, so arrowing onto its edge reveals it); line prefixes (`#`, `>`, list markers, task boxes, rules) reveal while the caret is on that line; block widgets (display math, mermaid, tables, front matter, code fences) reveal while the selection touches the block. A freshly opened note starts with its caret below any front matter, so the properties block opens rendered. The block field caches its candidates and only re-walks the tree when the document, the syntax tree or the theme changes; moving the caret just re-filters.
  - **Headings:** ATX and Setext (the `===` underline is dimmed); sizes h1–h6. **Lists:** bullets become `•`/`◦`/`▪` by depth, ordered numbers stay (muted), wrapped lines hang under the item's text (`padding-left/text-indent` in `ch`; exact because the editor font is monospace). **Tasks:** `- [ ]`/`- [x]` become a checkbox; a click toggles one character through the normal edit path (undo, autosave) and focuses the editor; done items are struck through. **Quotes:** `>` hidden, one bar per nesting level. **Rules:** drawn `<hr>`.
  - **Links:** `[text](url)`, `[text][ref]`, `[ref]` (resolved through `[ref]: url` definitions), `<url>` and bare `https://…`/`www.…` are styled; **Ctrl/Cmd+click opens** (a plain click edits). Only `http`, `https` and `mailto` ever open (`core/links.external_url`; the editor repeats the check). Web mode: the page opens a new tab inside the click (popup-blocker safe); native: Python opens the system browser; note/relative links are handed to Python and only toast until P3.3. (It must act on `mousedown`: CodeMirror's own Ctrl+click adds a selection, which rebuilds the link's DOM before `click` fires.)
  - **Images:** `![alt|300](.note.assets/x.png)` shows the picture (width from `|300`) through the token-protected route `/_pp/asset?note=…&path=…`, backed by `Vault.asset_path` (images only; `.<stem>.assets` is the only hidden folder allowed; no traversal, symlink escape, `.trash`, `.paper-pile`; SVG served with a sandboxing CSP). **Remote images are never fetched** (offline rule, no tracking): a chip is shown; a missing file shows "image not found". The editor learns the note's path through `show_doc/set_text/set_path`.
  - **Code blocks:** fence lines are hidden off-block (compact), the language shows as a small label, every code line gets the code look; highlighting via `markdown({codeLanguages})` with a curated, **lazily loaded** set (JavaScript/TypeScript, Python, JSON, HTML, CSS, SQL, Rust, C/C++, Java, Go, YAML, shell, TOML, diff); only languages used in the open note are downloaded; token colours are theme variables (light and dark). An unknown language is plain text. Indented code gets the same look.
  - **Tables:** a real `<table>` block widget (alignment from the delimiter row, inline markdown inside cells); **cells are edited in place** (P4.4): click a cell and type, Tab/Enter/arrows move, a right-click menu and "+" strips add/delete/move rows and columns and set alignment. All table rules live in `core/tables.py`; each edit rewrites the table as tidy aligned GFM. The markdown source still appears when the document caret enters the table (arrow keys) and in Source mode. While the caret is in a table, a live rendered preview of it is shown above the source.
  - **Front matter:** `---` first line, closed by the next line that is exactly `---`, only at the very top (otherwise ordinary markdown); rendered as a properties block (`key: value` rows; no YAML library in JS), raw and dimmed while touched.
  - **Source mode** (Ctrl+E, or the `Live`/`Source` label in the status bar): drops every decoration and widget, keeps text, undo history and syntax colours in code blocks; persisted per vault (`session.json` `mode`), applied on load.
  - **Measured:** on a 5,000-line note mixing every element, the synchronous editor update is p95 ≈ 14 ms for caret moves and ≈ 8 ms for typing (budget 30 ms); opening takes ≈ 0.2 s.
- ` ```mermaid ` → rendered diagram; render error shows inline message, not a crash.
- Math: `$inline$`, `$$inline$$` and `$$block$$` via KaTeX. **Rules (final, P2.3; reference = `core/parser.py`, markdown-it `dollarmath`):**
  - `$inline$`: no whitespace right after the opening `$` or right before the closing one; no digit directly before the opening or after the closing `$` (→ "$5 and $10" and "$5.50" stay text); `\$` is a literal dollar; empty content is not math. The **first** unescaped closing `$` decides: if it is invalid, the opening `$` is plain text (it does not scan further).
  - `$$inline$$` inside a paragraph is math with no whitespace rules.
  - `$$` block: a line starting with `$$` (indent < 4) that closes on the same line (`$$x$$`) or on a later line ending in `$$`. **Unclosed, or a blank line before the closing `$$`, means plain text.** A block may start directly after a paragraph line (no blank line needed); it works in lists and blockquotes.
  - Known limits: inside a blockquote the Python renderer keeps the `>` markers in the math content (plugin limitation; the editor strips them); odd constructs like `$$a$$ and $$b$$` at the start of a line or `$$x$$5` are not guaranteed to match between the two engines and are not in the shared fixture.
  - **Kept in sync by a shared fixture:** `tests/fixtures/math_cases.json` (generated from the Python parser) is asserted by pytest and by `tools/editor_src/check_sync.mjs` against the editor's Lezer grammar (`grammar.js`: math + front matter); `tools/build_editor.sh` runs the check, and `tests/core/test_grammar_sync.py` runs it from pytest. Front matter has its own fixture, `tests/fixtures/front_matter_cases.json`.
- **Block widgets (S2):** `$$…$$` display math (see the rules above; an unclosed `$$` is not a block) and ```` ```mermaid ```` fences render as block widgets from a CM6 `StateField` (block/line-spanning replace decorations are not allowed from a ViewPlugin). **Reveal rule:** a block shows its source whenever any selection range touches it; clicking a widget puts the cursor in it. Invalid diagrams show an inline error line, never a crash or mermaid's own error graphic. The grammar in `tools/editor_src/math.js` is kept in sync with `core/parser.py` by the shared fixture above.
- `[[note]]`, `[[note|alias]]`, `[[note#heading]]` → internal links; missing targets styled distinctly (dashed / dim).
- Standard `[text](other.md)` links also resolved as internal.
- Images `![alt|300](path)` → width 300px.
- Widgets (math, mermaid) re-render debounced (~200 ms) and only when their source changes.

### 4.7 Links & backlinks
- Syntax (built in P3.1): `[[note]]`, `[[note|alias]]`, `[[note#heading]]`, `[[#heading]]`. `[[...]]` must sit on one line, contain no `[`/`]`, and name a note or heading; code spans/fences are never links. The editor shows the alias (else the typed text) and hides the brackets until the caret touches the link; Ctrl/Cmd+click resolves it (P3.3). Rules live in `core/links.py` + `core/parser.py` and `tools/editor_src/wikilink.js`, kept in sync by `tests/fixtures/wikilink_cases.json`.
- Link extraction on save → index (`links` table: src, dst_raw, dst_resolved, kind).
- Resolution (`core/links.resolve_wikilink`): full path match → name or trailing-path match (case-insensitive, `.md`/`.txt` optional); ties → same folder as the source, shallowest, `.md` first, alphabetical → unresolved. Relative `[t](x.md)` links resolve against the source's folder.
- Ctrl/Cmd+click on a link opens the note in a tab (and jumps to `#heading`); on an unresolved wikilink it creates an empty note (same folder as the source; `[[a/b]]` is a path from the root) and opens it. Links to missing notes are styled dashed amber.
- Backlinks pane under the editor: notes whose links really resolve to the current note (`Index.backlinks`), each with the link's line as a one-line snippet; click opens the note at that line. Collapsible.
- **Rename-safe (`core/rewrite.py`):** renaming/moving a note or folder in the app keeps every `[[...]]` and `[t](x.md)` pointing at the same note, across the vault, in one operation, with a toast ("Updated 7 links in 4 notes"). Only a link's target part is edited (alias, `#heading`, `!`, title, `#fragment`, code spans and everything else stay byte-identical); open notes are edited through the editor (undoable). Limits: reference-style links and links whose position in the file is not certain are reported, never guessed; renames made outside the app are not rewritten.

### 4.8 Slash command menu (`/`)
- Trigger: typing `/` at line start or after whitespace. Not inside code blocks/inline code, not in URLs.
- Notion-style popup at the caret: search field placeholder "Type to search", grouped sections, icon + label + optional subtitle/badge + right-aligned markdown hint, footer "Close menu · esc".
- Fuzzy filter on name + aliases; empty groups hidden; recently used float to top (top 5, persisted).
- Keys: ↑/↓ (wrap), PageUp/Down, Enter or Tab apply, Esc close (keeps the literal `/`, does not reopen), Backspace past `/` closes; it also closes when the caret leaves the line, on blur/tab switch, and on a space after "No results". Applying is one undo step (Ctrl+Z restores the typed `/query`).
- **Implemented (P4.2):** the menu is a CM6 tooltip (`tools/editor_src/slash.js`); the editor sends `slash_query`, Python answers with `groups_json`; on pick the editor sends `slash_run`, Python runs the command, turns its action into an exact edit (`core/command_actions.py`) and the editor applies it (`applyChanges`). Phase-1 *Basic blocks* commands live in `core/commands_builtin.py`.
- Registry lives in `core/commands.py`:

```python
@command(
    "h2", "Heading 2", group="Basic blocks", icon="h2", hint="##", aliases=["heading", "subtitle"]
)
def h2(ctx: CommandContext) -> Action:
    return ReplaceLinePrefix("## ")
```
- `CommandContext`: note path, buffer text, cursor, selection, vault, config, ai provider.
- Actions: `Insert(text, cursor_offset)`, `ReplaceLinePrefix(prefix)`, `ReplaceSelection(text)`, `OpenNote(path)`, `OpenPicker(kind)`, `StreamInsert(async_iter)` (for AI).
- GUI sends registry as JSON to the editor JS; JS renders the menu and returns the chosen command id; Python executes and returns the action; JS applies it.

**Phase-1 commands**

| Group | Commands |
|---|---|
| Basic blocks | text, h1–h4, bulleted list, numbered list, todo, quote, divider, page break (§4.17), callout (a quote with a bold `Note:` label) |
| Code & math | code block, math block, inline math |
| Diagrams | mermaid (flowchart), sequence, gantt |
| Media | image (file picker; added with P5), table (3×3) |
| Links | link to note (note picker), embed note |
| Insert | date, time, template (if templates folder set) |
| AI | summarize, continue writing, explain selection, fix grammar, ask… |

### 4.9 Images (traceless)
- Storage: hidden sibling folder per note: `notes/mamba.md` → `notes/.mamba.assets/`.
- Filename: first 12 hex of SHA-256 of bytes + original extension (dedupe, no collisions). PNG for pasted bitmaps.
- Reference inserted: `![image|<width>](.mamba.assets/a3f9c1d2e4b0.png)` — standard markdown path, width in alt (Obsidian convention).
- Sources: clipboard paste, drag-drop, `/image` picker.
- Resize: in live preview, drag image corner → rewrite only the `|<width>` number in the source.
- **Implemented (P5):** `core/assets.py` (content-sniffed type, hash name, header-read size, default width = natural width capped at 640); upload route `POST /_pp/upload` (custom header + loopback origin + 25 MB cap); the orphan sweep runs when a note is closed (not on every save, so Ctrl+Z can still bring a deleted reference back); renames made outside the app do not move the folder.
- Lifecycle (in `core/assets.py`, invoked by vault ops):

| Event | Action |
|---|---|
| Note renamed/moved | Rename/move assets folder + rewrite references in that note |
| Note deleted | Move assets folder to `.trash/` alongside the note |
| Note duplicated | Copy assets folder, rewrite refs in copy |
| Image ref removed | On save, unreferenced files → `.trash/` (orphan sweep) |
| Assets folder empty | Delete folder |

- Export option (later phase): "Export note as single .md" with base64-inlined images.

### 4.10 Smart Paste
On paste into the editor:
1. If clipboard has an **image** → images flow (4.9).
2. Else if it has **text/html** → `core/paste.html_to_md(html)`:
   - KaTeX/MathJax elements → extract LaTeX from `<annotation encoding="application/x-tex">` (or MathJax script tags) → `$...$` inline, `$$...$$` display. Drop the visual duplicate.
   - `<pre><code class="language-x">` → fenced block with language.
   - Tables, nested lists, headings, emphasis, links → markdown.
   - Strip chatbot UI junk ("Copy code", "Copied!", "Copy", language labels in code headers, citation buttons).
3. Else **plain text** → `core/paste.normalize(text)`:
   - `\( ... \)` → `$...$`, `\[ ... \]` → `$$...$$`.
   - Never touch content inside fenced code or inline code.
4. Ctrl+Shift+V → raw paste, no conversion.
5. Setting: Smart Paste on/off (default **on**).
- **Implemented (P6):** `core/paste.py` (BeautifulSoup + a markdownify subclass; math extracted before anything else, code blocks next, then the page's interface elements are dropped); `EditorPane._on_paste`; fixtures are reconstructed from each chat page's markup shape (`tools/gen_paste_fixtures.py`), real captures can be added with `PAPER_PILE_DUMP_PASTE=1`.
- Test fixtures: real clipboard HTML captured from ChatGPT, Claude, Gemini, DeepSeek in `tests/fixtures/paste/<source>_<case>.html` + expected `.md`. Cases: inline math, display math, code block, table, nested list, mixed.

### 4.11 AI (Ollama)
- `Provider` protocol: `chat(messages, stream) -> AsyncIterator[str]`, `embed(texts)`, `models()`, `health()`.
- `OllamaProvider`: host from config (default `http://localhost:11434`).
- Startup health check; status bar dot (green/red). If down → friendly banner in chat pane ("Ollama isn't running — start it with `ollama serve`"), app still fully usable.
- Composer (changed by the user, 2026-10-16): one rounded card holding attachment chips, a `+` menu, the input, the model picker (populated from `models()`, short name) and a round Send button. The `+` menu lists the open tabs (check on the current one; a click attaches the note as a chip), "Add more notes" (search), "Select from screen" (attaches the editor's selection, or hints to select), "Upload files" (text files up to 200 KB, read in memory, never saved) and an "Include open tabs" switch (shown as an "All open tabs (N)" chip). Editor selections attach themselves as chips (one unfolded at a time, graphics shown as code, removed only by ×). The old options row (switch + "Add all tabs") and the context summary line are gone.
- **Context building** (`core/ai/context.py`), filled in order until the token budget (configurable, default 6000 tokens; rough estimate chars/4):
  1. Selection (if any)
  2. Current note
  3. `@note` mentions in the chat message
  4. (option) all open tabs
  5. Linked notes (outgoing + backlinks, one hop) — truncated
- Chat: streamed tokens, markdown-rendered replies (math + mermaid render too), Stop button, per-message "Insert into note" and "Copy".
- `@` in chat input → note picker (fuzzy).
- Chat history kept per session (in memory) in phase 1. **Changed 2026-10-21 (user request):** each chat is also saved per vault as `<vault>/.paper-pile/chats/<id>.json` (`core/ai/chats.py`; title = first question, atomic write after every message; deleting moves it to `.trash/`).
- **Chat ⋮ menu** (user request 2026-10-21): a slim header row at the top of the chat pane: the open chat's title (its first question, or "New chat") on the left, a ⋮ button on the right. Items: *New chat* (disabled while empty or while a reply streams), *Memories* — the 5 latest saved chats (**one line: the title only, no time** — changed 2026-10-21, user request; a check on the open one, a trash icon on hover), the rest under *More chats (N)* with a search box — and *AI settings*, which opens the Settings tab on its AI section. Switching chats is disabled while a reply streams.
- **Settings → AI page order (changed 2026-10-21, user request):** connection rows (host, model, embed model, context budget) → *System instruction* → **Memories** → **Advanced** (an expansion, closed until opened; its open state is kept while Settings stays open). Help texts are a few words each.
- **System instruction** (renamed from "Extra instructions", 2026-10-21; `core/ai/instructions.py`): a segmented *Write* / *From a file* (`ai.instructions_from`). *Write*: a large box (`ai.instructions`, multi-line, up to 4000 chars, saved on blur, "N / 4000") that the user stretches by dragging its bottom-right corner (no Expand dialog, changed 2026-10-21) and *Write with AI* (describe the assistant in a few words → the model drafts the instruction into an editable box; *Write again*, *Use this*). *From a file*: `ai.instructions_file` — a note of the vault (picker) or any typed path to a `.md` / `.txt` (vault-relative or absolute; native window: *Browse*); read on every message, first 8000 chars, a missing file means no instruction. Sent in the system prompt of chat and AI commands.
- **Settings → AI → Memories** (user request 2026-10-21, `gui/components/memories.py`): *Save chats* switch (`ai.save_chats`), *Auto-delete after (days)* (`ai.keep_chats_days`, 0 = never; checked when the chat pane starts, older chats go to `.trash/`, never the open one), *Memories folder* (`ai.chats_folder`, "" = `<vault>/.paper-pile/chats`; shows the path, Copy, *Change* = the vault dialog's folder browser (`ask_folder`); a folder inside the vault is stored vault-relative; after a change it offers to move the existing chats — a name already taken there is never overwritten), a filter (words in title or messages) with *From* / *To* date boxes (typed `YYYY-MM-DD` or picked in our own calendar popup — a Quasar date in a rounded menu with the theme's colours, not the browser's date input), "N of M memories", *Delete shown (N)* (only while filtered) and *Delete all* — each confirmed, all to `.trash/` (also from a folder outside the vault) — and the list: one line per chat (title, day, trash on hover), the first 10 then *Show all (N)* / *Show less*. A click opens it as a rendered markdown document (`chat_markdown`: `# title`, date · count, `### You` / `### Assistant` per message, attachments in italics) with *Open in chat*, *Copy as Markdown*, *Save as note* (vault root, free name from the title, then opened) and *Delete*.
- **Settings → AI → Advanced** (user request 2026-10-21): *Temperature* (0–2, default 0.8), *Top-p* (0.05–1, default 0.9), *Context window* (`num_ctx`, 0 = the model's default), *Chat history sent* (`ai.history_turns`, default 12), *Keep model loaded (min)* (`keep_alive`, default 5). Passed as `GenerationOptions` to `Provider.chat(..., options=)`; Ollama gets `options` + `keep_alive`.
- AI slash commands use the same provider + context builder and stream into the editor at the cursor (`StreamInsert`).
- Vault-wide RAG (embeddings + `sqlite-vec`): **not phase 1**.
- **Implemented (P7):** `core/ai/{provider,ollama,fake,factory,context}.py`, `gui/components/chat.py`. AI slash commands: Summarize, Continue writing, Explain selection, Fix grammar (replaces the selection once complete), Ask… (dialog); selection-based ones are reached with **Ctrl+J / Alt+/** (typing `/` would replace the selection). Answers stream into the note and are one undo step; Stop in the notice.

### 4.12 Settings, theme, profile
- **Settings layout (2026-10-17):** Settings in the right pane has its own remembered width (`pane_widths["settings"]`, draggable 460–960 px). It always opens at ≥ 640 px (unfolded). Below 560 px the section list folds to an icon rail (search hidden, Restore defaults icon-only); below ~440 px of content each row puts its control under the text and the scope switch moves to its own line (CSS container queries). Help texts are one short line.
- **Hover and tooltips (2026-10-17):** every hover highlight is a rounded (`--pp-r-ctrl`) shape inset from the edges, tabs included. Tooltips only on controls that show no text (icon buttons, the Ollama dot, a truncated vault path); they are drawn by one small system (`gui/tips.py` `tip()`, `static/tips.js`, `data-tip` attribute) that keeps them 8 px inside the window — no Quasar tooltips, no native `title`; a folded settings section or an icon-only tab shows its name on hover only while folded.
- **Narrow right pane (2026-10-17):** the chat composer switches to its two-row layout whenever the text, or the placeholder of an empty box, would not fit on one line (re-checked on resize); the right-pane tabs show icons only (names in tooltips) when their titles do not all fit.
- **Footer (2026-10-17):** the status bar is no longer a full-width row: it sits on the right of a footer under the editor only (Backlinks toggle on its left; the list opens above it). Footer and profile row share `--pp-foot-h` (41 px) so their top lines meet; the chat pane runs to the bottom. When the left pane is folded, its icon column keeps Settings above the avatar at the bottom.
- **Pane tweaks (2026-10-21):** dragging the file tree's or the right pane's edge on past its narrowest width (by 48 px) folds that pane away (`static/panes.js` → `pp_pane_collapse`; its width is kept for reopening). The fold buttons show what a click does: `panel-left-close` / `panel-right-close` while open, `panel-left-open` / `panel-right-open` while folded (tooltips Hide/Show). The FILES row has 8 px of air above it. The chat's "+" is a circle like the send button.
- Bottom-left of left pane: avatar + name and a line-icon settings button (the ☀️/🌙 quick theme toggle was removed 2026-10-16; the theme is set in Settings → Appearance).
- Profile: local only (name, avatar image or initials). Name used in chat and optional `author:` front matter.
- Settings dialog sections:

| Section | Options |
|---|---|
| Appearance | Theme: Light / Dark / System; accent colour (a 6×2 grid of 12 presets, or any colour code — `#hex`, `rgb()`, `hsl()` — typed or picked in a colour field; stored as the preset name or `#rrggbb`, dark variant derived by `core/colors.py`); UI density (compact/comfortable) |
| Editor | Font family, font size and line height (a number between − / + buttons: 1 px / 0.1 steps within 8–40 px / 1.0–3.0; still typeable, ↑/↓ step too), code font (`editor.code_font_family`, default `monospace`: code blocks, inline code, code in tables, embeds and chat; presets are installed-font names with a monospace fallback, or any CSS list), word wrap, tab size, spell check, page view (`editor.page_view`, §4.17), default preview mode |
| Print | Paper size: A4 / Letter (`print.paper`, §4.17) |
| Vault | Attachments behaviour (fixed: hidden per-note), templates folder, daily-notes folder |
| AI | Ollama host, default chat model, embed model (future), context budget, system instruction (typed / AI-drafted / from a file); Memories: save chats, auto-delete after N days, memories folder, the memory browser; Advanced (folded): temperature, top-p, context window, chat history sent, keep model loaded |
| Paste | Smart Paste on/off |

- Storage: global `~/.config/paper-pile/config.toml` (via platformdirs), per-vault overrides `<vault>/.paper-pile/vault.toml`. Load order: defaults → global → vault.
- **Shape tokens (2026-10-17):** `--pp-r-popup` 12 px (menus, popups, dialogs, cards), `--pp-r-ctrl` 8 px (buttons, inputs, menu items, tiles, content blocks), `--pp-r-sm` 4 px (inline code, kbd, small chips); pills and circles stay pills/circles. Quasar menus, dialogs, tooltips, notifications, fields and buttons follow the same tokens.
- Theming via CSS variables; editor + preview + mermaid + chat all follow theme (Mermaid theme switches to `dark`).
- **Implemented (P8):** schema/validation in `core/settings.py`, dialog `gui/components/settings.py` ("Save for: All vaults / This vault", Restore defaults), theme `static/theme.js` + `gui/theme.py`, profile `gui/components/profile.py` + `core/profile.py`. **Ctrl+,** opens the settings.

### 4.13 Navigation & status
- Ctrl+P command palette, Ctrl+O quick switcher, Ctrl+Shift+F vault search, Ctrl+Shift+O outline: see §4.18.
- Status bar: word count, Ln/Col, save state, Ollama status.

### 4.14 Keyboard shortcuts (defaults)

| Key | Action |
|---|---|
| Ctrl+P | Command palette |
| Ctrl+O | Quick switcher |
| Ctrl+N | New note |
| Ctrl+W | Close tab |
| Ctrl+Tab | Next tab |
| Ctrl+Shift+Tab | Previous tab |
| Alt+W / Alt+PageDown / Alt+PageUp | Close / next / previous tab — fallbacks for web mode, where the browser reserves Ctrl+W and Ctrl+Tab |
| Ctrl+E | Cycle preview mode |
| Ctrl+B | Toggle left pane |
| Ctrl+L | Toggle AI chat |
| Ctrl+Shift+F | Vault search |
| Ctrl+Shift+O | Outline |
| Ctrl+Shift+V | Raw paste |
| Shift+Alt+F | Tidy note |
| Ctrl+Enter | Page break at the caret (§4.17; the editor's own key) |
| Ctrl+, | Settings |

**Implementation notes (S3):** a single capture-phase `keydown` listener on `window` (`addEventListener(..., true)`), `preventDefault()` on Ctrl/Meta combos, forwards `{key, ctrl, shift, alt}` to Python (`ui.on` + `emitEvent`). With Shift held `e.key` is uppercase (`"F"`, `"V"`): always compare `e.key.toLowerCase()`. Verified in the native Qt window: all 12 shortcuts above are delivered and Ctrl+W does not close the window.

---

### 4.5b Blocks and the caret (user request 2026-10-17)
- **Blank lines around blocks** (Settings → Editor → Advanced, on by default, `editor.block_spacing`): a table, image, embed, code / math / diagram block, callout, heading, list or quote inserted by a slash command, a paste/drop or the note picker goes on lines of its own with an empty line above and below (`core/spacing.py`; a quote next to a quote continues it; list items under a list item continue the list). Off: blocks still get their own lines, and lists still end with an empty line.
- **H1 divider** (user request 2026-10-21): an H1 (and only an H1) is drawn with a divider under it that looks exactly like a `---` rule (same colour and left/right edges), with space between it and the heading text. Drawing only: nothing is added to the file.
- **Lazy lines** (user report 2026-10-21): in markdown a line typed straight under a quote/callout or list line, without `>` or indentation, still belongs to that block. Live Preview draws such a line inside the quote bar / callout card / under the item's text, as every renderer will show it. **Enter on an empty quote or list line** that leaves the block for good keeps that line empty and moves the caret to a new line under it, so the next text starts a new paragraph. The **divider** is spaced like the other blocks (empty line above and below, caret below the rule); with the setting off it still gets an empty line under text (no setext heading).
- **Tidy note** (user request 2026-10-21): a floating round button at the bottom right of the editor (markdown notes only; also Shift+Alt+F and the ⋯ menu). Each side of the editor has its own floating tidy button for the note it shows: bottom right with one editor; in split view one per side, at the bottom right of that side. Settings → Editor → "Tidy note button" (`editor.tidy_button`, on by default) shows or hides these buttons; the shortcut and the ⋯ menu item always work lays the note out cleanly with `core/tidy.py`, as ONE undo step with the caret kept: one empty line between blocks (none at the start, one newline at the end), trailing spaces removed (two-space line breaks kept), one empty line at most inside lists/quotes, lazy quote/list lines get their `> ` / indentation, `#` headings get one space, a one-line setext heading becomes `#`/`##`, `***`/`___` become `---`, tables are aligned when no cell would be lost. Code, math and front matter are never touched; lines outside any block (link definitions, footnotes) are kept. Guarantee, tested on every fixture and doc: the rendered HTML is identical before and after, and tidying twice changes nothing.
- **Chat jump buttons** (user request 2026-10-21): floating "scroll to top" / "scroll to bottom" circles at the bottom right of the chat log, each shown only when there is more than 120 px to go that way (`static/chat.js`, smooth scroll in the page).
- **Click below a note that ends with a block** (anything but a paragraph): an empty last line is added and the caret goes there, so text is never typed into the table / heading / callout by accident.
- **Callouts** look like the properties block: a card (thin border, rounded corners, light tint) in the callout's colour — accent, green (tip/success/done/hint), orange (warning/caution/important/attention), red (danger/error/bug/failure) — with a rounded colour stick on the left.
- **Editor QA harness:** `uv run python tools/qa_editor.py` drives the real editor (offscreen native window, throwaway vault) through 293 checks (incl. "every drawn block fits the space the editor gave it" and notes with a properties block): arrow keys around every block type at the start / end / between text / next to another block, click below the end, a new line above the first block, slash-command spacing and the callout card.

### 4.15 Note menu (⋯) — user request 2026-10-17
A **⋯** button in the note header (§4.25; before P21: at the right end of the tab strip) opens a menu for the note on screen (each split side has its own):

| Group | Item | Behaviour |
|---|---|---|
| Edit | Find… (Ctrl+F) / Replace… (Ctrl+H) | CodeMirror's search panel, themed like the app; Replace opens it with the replace field focused |
| Edit | Tidy note (Shift+Alt+F) | Same as the floating tidy button (§4.5b) |
| View | Page view | Turns page view on (in the style used last: Page lines / Real pages) / off (check mark while on; same setting as Settings → Editor → Page view; §4.17) |
| View | Split right | Asks which note to show on the right (a picker: open tabs first, marked "Open"; typing searches every note), then shows a second editor. Each side has a floating chip with its note's name (the side being typed in is highlighted in the accent): clicking the name picks another note for that side, its ✕ closes that side (the other side's note stays). Clicking into an editor makes it the active one (tab bar, status, backlinks follow); picking a tab shows it in the active editor. The divider between the sides can be dragged (each side keeps ≥ 200 px; double-click: half and half; `static/split.js`). The same note in both editors stays in sync (edits mirrored without touching the other side's undo history). Not restored on restart (nor is the divider position). |
| File | Move to… | Folder picker (vault root + every folder); same as a drag in the tree: images follow, links are repaired |
| File | Merge into… | Pick another note; this note's body (front matter dropped) is appended to it under a blank line, its images move to the target's images folder (references rewritten), links to this note are repointed at the target, then this note goes to `.trash/`. Asks for confirmation. |
| AI → chat | Add to chat | Attaches the note to the chat composer |
| AI → chat | Summarize / Rewrite | Opens the chat, attaches the note and sends a fixed prompt ("Summarize this note." / "Rewrite this note …") |
| AI → chat | Write… | Opens the chat, attaches the note and puts "Write " in the composer for the user to finish |
| Share | Copy path / Copy full path | Vault-relative path / absolute path to the clipboard |
| Share | Export as Markdown | One `.md` with the note's images inlined as `data:` URIs |
| Share | Export as HTML | One self-contained `.html` (rendered markdown, images inlined, light styling; math stays as TeX and diagrams as code — no scripts) |
| Share | Export as PDF | Paged like the editor's page lines (§4.17) |
| Share | Open in default app | Shown, disabled ("Soon") — not implemented by request |

Exports: native window → a Save dialog; `--serve` → a browser download. Pure logic in `core/export.py` and `core/merge.py` (unit-tested). **Implementation:** `gui/components/note_menu.py` (presentation), `gui/components/note_actions.py` (dialogs, hand-offs), split view in `EditorPane` (two `Editor`s; `_editor` = the focused one; same-note edits mirrored with `Editor.sync_text`, outside the other side's undo history). The editor bundle keeps each editor's note path / events / doc id in a CodeMirror facet (`context.js` `runtimeFacet`), so two editors on one page never share state; HTML export: markdown-it only inlines PNG/JPEG/GIF/WebP `data:` images (SVG/BMP/AVIF stay links).

### 4.16 Tags — user request 2026-10-17
- **Two ways to tag a note**, both count:
  - inline `#tag` in the text: `#` at the start of a line or after a space, then letters / marks / digits / `_` / `-` / `/` (Unicode, so `#বাংলা` works), at least one of them not a digit (`#123` is not a tag); `#tag/sub` is a nested tag; never inside code, and `# Heading` (with a space) stays a heading;
  - the `tags` property in front matter: a YAML list (`tags: [a, b]` or a `- a` block) or a string (`tags: a, b` / `tags: a b`); a leading `#` is ignored.
- Tags compare case-insensitively (shown as written). Searching `#a` also finds notes tagged `#a/b`.
- **Chips:** inline tags show as chips in Live Preview (the raw `#tag` while the caret is in it); the `tags` row of the properties block shows one chip per tag — the `tags` property and every inline `#tag` of the note (display only: the file is not rewritten; a note with inline tags and no `tags` property still gets the row).
- **Click a chip** → a closable tab named after the tag (its icon is the `#`) in the right pane (beside AI chat / Calendar) listing every note with that tag (title, folder). One tag tab at a time; clicking another tag replaces it.
- **Click a note in that list** → a small menu: **Open** (in the active editor) or **Open in split** (in the right side of a split view; opens the split if needed).
- Rules in `core/tags.py` (unit-tested); tags indexed in `.paper-pile/index.db` (table `tags`, schema 3; rebuilt automatically). Inline rule shared with the editor grammar through `tests/fixtures/tag_cases.json` (checked by `check_sync.mjs` and pytest).

### 4.17 Page breaks, page lines and PDF export — user request 2026-10-21
Goal: the user sees where pages end **while editing**, and the exported PDF breaks exactly there, with the editor's look (fonts, heading sizes, callout cards, tables, code, KaTeX, Mermaid) on light paper.

**Syntax (file format).** Markdown has no standard. paper-pile writes `---/` (user decision 2026-10-21: short to type, close to a divider), alone on its line with an empty line above and below:
```markdown
---/
```
(Other markdown apps show `---/` as plain text. The HTML form other tools write, `<div style="page-break-after: always;"></div>`, is still read, so notes written elsewhere keep their breaks.)
A line is a manual page break when:
1. it is the whole line (up to 3 leading spaces, trailing spaces allowed): `---/`, or an HTML form (matching ignores case and spacing, `;` optional): `<div style="page-break-after: always">` / `<div style="break-after: page">` / `<div class="page-break">`, each with `</div>` on the same line;
2. it is at top level: not in a code fence/span, quote, list, table, front matter or math block;
3. the lines above and below are empty (or the file starts/ends) — otherwise it is part of the paragraph next to it (CommonMark also folds text into an HTML block). Inserting always adds the empty lines;
4. a break at the very start or end of the note does nothing, and consecutive breaks count as one (no blank pages).

`---` is never a page break (a divider / front matter / setext H2); `---/` is neither of those in any markdown reader. Rules in `core/pagebreak.py`, shared with the editor grammar through `tests/fixtures/pagebreak_cases.json` (checked by `check_sync.mjs` and pytest). The parser keeps `html=False`: it recognises only this line and renders `<div class="pp-page-break">` (HTML export: `break-after: page`; chat: a thin rule). Markdown export keeps the line as is.

**Inserting.** **Ctrl+Enter** (like Word: everything after the caret goes to the next page; it replaces a selection) and the slash command **Page break** (`page-break`; also found by "pagebreak", "new page", "print", "pdf") in the command registry, so the Ctrl+P palette lists it once P9.1 builds the palette from the registry. Both insert `---/` and always add the empty line above and below (whatever "Blank lines around blocks" says) and puts the caret on the line after the empty one, because text typed right under the break would turn it back into text.

**In the editor.**
- A manual break is a full-width line labelled "Page break" (the raw line while the caret is on it), in both themes, always shown.
- **Page view** is a mode the user turns on and off; the normal editor is unchanged until they do (user decision 2026-10-21). One setting, `editor.page_view`: **Off** (default) / **Page lines** / **Real pages**, a segmented choice in Settings → Editor → Page view. The ⋯ menu → View → **Page view** turns it on in the style used last (`editor.page_view_last`, Page lines until Real pages has been used; a check mark while on) and off again. Both places always agree; remembered across restarts; applies to every editor (both split sides). In either style:
  - the text column takes the paper's text width (so lines wrap as on paper);
  - **Page lines:** a dashed line labelled "Page N" is drawn between the two source lines where each automatic page starts.
  - **Real pages:** the note is drawn on sheets of paper (white sheets with a shadow on a grey desk; dark sheets in the dark theme), each as tall as the paper with its margins, a gap between sheets where a page starts, and the page number in the bottom margin. A sheet whose text is shorter than the page is padded to the full height; a sheet can grow while the caret shows a block's source (the editor then shows more than the paper does).
  - the page starts come from the print layout below (the same pages the PDF gets), worked out again ~500 ms after typing stops, from the live text (not the saved file);
  - the **properties block (front matter) is hidden**, as it is not printed: its lines are folded away and the caret cannot enter them. The file is not changed; turning page view off shows the block again.
  Turning page view off removes the page lines / sheets and restores the normal width and the properties block, with the caret and scroll position kept.

**Print layout (the single source of pages).** `core/printdoc.py` renders the note (live text) to a print HTML: front matter not printed, light colours, the editor's type scale and block styles (one shared print stylesheet), KaTeX and Mermaid rendered with the vendored scripts, every block and every source line inside a paragraph tagged with its source line (`data-line`). The paginator (`tools/editor_src/paginate.js`, run by the print page's script `print.js`, a second entry of the editor bundle) lays it out in a hidden frame at the paper's text width and moves the content into fixed page boxes (`@page { size: <paper>; margin: 0 }`, each box exactly one sheet with the margins inside it, page number centred at the bottom). Rules:
- pages break only between source lines (never inside a wrapped line), so every break has an exact spot in the editor;
- **empty lines are space** (user decision 2026-10-21): the editor shows every empty line, so the paper does too. Between two top-level blocks one empty line is the usual gap; each further empty line adds one line of space (markdown itself would merge them; HTML export still does). Pressing Enter therefore pushes what follows down, and onto the next page. Empty lines that would start a page (after the first) are dropped, so pushed text starts at the top of its page;
- a manual break starts a new page;
- a heading stays with the line after it;
- code blocks, tables, images, math, Mermaid, quotes and callouts are not split, unless one is taller than a page: then code splits between lines and tables between rows (header repeated); images, math and diagrams are scaled down to fit a page;
- paragraphs and lists split between source lines, keeping at least 2 lines on each side when they can.
Output: the page boxes (printed as is) and the list of `{line, page}` starts (sent to the editor). Paper: **A4** (210×297 mm) by default, **US Letter** in Settings → Editor → Page view (`print.paper`, under Page view since 2026-10-22); margins 20 mm.

**Known limit (follows from "break only between source lines"):** a paragraph written as ONE long source line (the usual way) is never cut: when it does not fit at the bottom of a page it moves whole to the next page, leaving a gap of up to one paragraph. Paragraphs of several source lines, lists, code and tables are cut normally.

**Implementation.** Print pages are served from memory at `/_pp/print/<key>` (`gui/printing.py`, newest 24 kept, behind the token gate in `--serve`). Page view (`tools/editor_src/pageview.js`, in the editor options) emits `print_layout` {docId, seq, text} ~500 ms after typing stops; `EditorPane` answers only for the editor that shows that note (a hidden split side gets nothing) with the page's URL; the editor loads it in its own hidden frame (`.pp-print-frame`) and maps the returned lines through any typing done meanwhile. Mermaid diagrams are cached by the page (`mermaidrender.js`), so the frame does not redraw them on every layout. Real pages: a widget at each page start draws the end of the sheet before (padding + bottom margin + page number), the desk and the top of the next sheet; a top widget and an end widget close the first and last sheet; `sizer` measures each page's text with CodeMirror's height map (widget heights known, so left out) and pads the sheet to the paper's height (changes ≤ 1 px ignored, a few corrections a second at most). Checked end to end by `tools/qa_print.py` (real app: page view toggle and styles, fixture notes, page lines / sheets = page starts, sheet heights, PDF text per page, properties, paper switch, Enter / Ctrl+Enter, typing cost).

**Export as PDF** (⋯ menu → Share). Native window: Save dialog, then the print page is loaded in an off-screen Qt WebEngine page and saved with `printToPdf` (`native_boot.print_to_pdf`, called through the window's method queue as `print_pdf`). `--serve`: the print page is loaded in a hidden frame with `?mode=print` and opens the browser's print dialog itself (a new tab would be stopped by popup blockers, as the call does not come from a click in the page); the user picks "Save as PDF" (margins default, scale 100 %). Both use the same page boxes, so pages match the editor's page lines.

### 4.18 Features, navigation & safety — user request 2026-10-22
**Feature switches** (Settings → General, a *Features* group at the top, shown in every view):
- **AI** (`features.ai`, default on). Off: the app never talks to Ollama (no provider, no health checks) and shows nothing AI: no AI chat tab, no *Ask AI* start button, no AI group in the ⋯ menu, no AI slash commands, no *Add to chat* (tree, ⋯ menu, block buttons only copy), no Ollama dot, no AI settings section, no *Write with AI*. Turning it on brings all of it back without a restart. How the AI reads the vault is out of scope (user has their own plan).
- **Calendar** (`features.calendar`, default on). Off: no Calendar tab; the Daily notes settings group is hidden.
- **Minimal settings** (`settings.minimal`, default **on**). On: each page lists only the essential settings (flag `essential` in `core/settings.py`): Features, Version, Vault, Writing language, Smart Paste, Mode, Accent colour, Font family, Font size, Wrap long lines, Check spelling, Page view, Paper size, Ollama address, Chat model, Save chats. Sections with nothing to show leave the list; hand-made panels (templates, memories browser, gallery folders, Advanced) are hidden. Search always finds every setting.
- The right pane shows only the tabs that are on (AI chat, Calendar, plus Settings / #tag / Outline while open). With AI and Calendar both off, the right pane folds away unless one of those tabs is open, and its toggle button only shows while it has something to show.

**Quick switcher** (Ctrl+O, replaces the recent-notes stand-in): a popup near the top (`gui/components/picker_popup.py`, shared with the palette) with a search box over every note of the vault, fuzzy (`core/picker.py` `switcher_notes` / `search_notes` over `core.commands.match_score`: exact > prefix > word start > substring > letters in order; the file name counts more than the folder). Empty query: recently opened notes first (`session.json` `recent_notes`, newest 20; renames follow). ↑/↓ move, Enter opens, Ctrl+Enter opens in the split, Esc closes; no match → *Create “query”*.

**Command palette** (Ctrl+P): the same popup over the app's commands (`gui/commands_palette.py`: name, shortcut, icon, action, extra search words; only commands that make sense now — e.g. no note commands without a note, no AI without AI), fuzzy-filtered, shortcut shown on the right.

**Vault search** (Ctrl+Shift+F, or the search button of the Files header): the Files pane's search mode searches the full text of every note (the SQLite FTS index, `Index.search`; the indexed body leaves out front matter and heading marks — `index.search_body`, schema 4); each hit shows the note name, folder and a two-line snippet with the words highlighted. Empty box: recently changed notes, as before. Clicking a hit opens the note with the editor's search panel on the first matched word, that match selected (a selection made by the search panel is never attached to the chat).

**Outline** (Ctrl+Shift+O, ⋯ menu, palette; since P14.5 a section under the file tree, see below — no longer a right-pane tab): listing the headings of the active note (indented by level; headings inside code blocks ignored — `core.parser.headings` / `section_at`, `gui/components/outline.py`). A click scrolls the editor to that heading and puts the caret there; the section holding the caret is marked.

**Outline in the Files pane (2026-10-22, user request; replaces the right-pane tab):** a collapsible *OUTLINE* section under the file tree (icon `list-tree`) with a draggable divider; open/closed and its height are remembered per vault (`session.json`). Ctrl+Shift+O (⋯, palette) unfolds the file tree if needed and opens the section, or collapses it if it is open.

**Slash menu, more ways in (2026-10-22, user request):** besides typing `/` and Ctrl+J / Alt+/: (1) a right-click in the note opens it at the click (inside a selection: for the selection, like Ctrl+J). The `/` it puts there is removed again if the menu closes without running a command. Opened this way the menu starts with *Cut* / *Copy* (with a selection) and *Paste* — the native window has no right-click menu of its own, and in web mode this one replaces the browser's. (2) Putting the caret right after a `/` that stands on its own (line start or after a space, followed by a space or the line end — not `and/or`, not in code) opens the menu; Esc closes it and it stays closed until the caret leaves and comes back.

**Tab menu (right-click a tab, 2026-10-22, user request):** Split right / Close split, Rename…, Move to…, Merge into…, Version history, Copy path, Show in file tree, Add to chat (AI on), Close, Close others.

**Note buttons beside ⋯ (2026-10-22, user request; in the note header since P21):** a split toggle (`columns-2` / close split) and, while AI is on, an AI button (`sparkles`) with Ask about this note, Summarize, Rewrite, Write….

**More of the same day (2026-10-22, user request):**
- *Outline on the folded rail:* while the file tree is folded away, an Outline button (`list-tree`) sits right above the Open vault button; it unfolds the tree with the Outline section open.
- *Many tabs:* tabs shrink (to 96 px, names cut with …) before they overflow; then the row scrolls with the mouse wheel and with ‹ › arrows on a cut-off edge (which also fades), and a list button (`chevrons-down` + the tab count) before the note buttons lists every open tab (the one(s) on screen marked; a click shows it). User's choice: shrink + scroll + list, with arrows.
- *Backlinks while split:* the footer has one Backlinks toggle per side, the right one at the split divider; the lists open together, side by side, each for its own side's note; a click opens the link on that side.
- *Line numbers:* Settings → Editor → *Show line numbers* (`editor.line_numbers`, default off, essential). In page view the page shrinks beside them. Counting starts after the properties block (its lines get no number; the first line under it is 1), in the gutter and in the status bar's Ln (*Properties* while the caret is inside them); Python still gets the real line numbers.
- *Dragging page breaks:* hold the left mouse button on a *Page N* line of page view (outside page view: on a page break line) and drop it on another line: the page now starts there. In page view the break lines themselves are not drawn (the page line or sheet edge below shows the break; the caret steps over them). A page started by a break moves that break (kept as written, with its empty lines; the one it leaves is dropped); a page the layout started gets a new break. A press without moving puts the caret on the page's first line. The editor draws the drag and sends the drop (`page_break_move`); `core/page_move.py` makes the text, refusing places where a break would not count (code, lists…). One Ctrl+Z undoes it.
  - *How far (2026-10-22, user request):* a page starts at least one line below the start of the page before it ("earliest"), and no lower than where that page would end by itself, full ("furthest"): for a break of the user's that place comes from a trial layout of the note without that break (asked when the drag starts); a page the layout started only moves up. Outside page view a break stays between its neighbouring breaks. The note scrolls while the pointer is near the editor's top or bottom edge.
  - *The rest moves on:* after the drop the note is laid out again; when page N now holds more than fits, the rest flows onto a new page (N+1…) and a message says how many pages the note has now (or that it fits on fewer).
- *Command palette button (user's placement):* at the bottom of the Files pane, Open vault · Command palette (`command` icon, Ctrl+P) · Settings sit together in one box styled like the Light / Dark switch; on the folded rail the same box stands upright, under the Outline button.
- *Settings → General:* Version and Vault come first (before Features); the Vault row is a normal settings row: name and folder (cut short, whole on hover) with *Change…* (the Open vault picker), which drops under the text when the pane is narrow and shows only its icon when narrower still.

**File tree keyboard:** the tree takes focus on click. ↑/↓ move, Shift+↑/↓ extend the selection, ←/→ fold / unfold a folder (← on a note goes to its folder), Enter opens, F2 renames, Delete moves the selection to the trash (one confirm), Ctrl+A selects every shown row, Esc clears.

**Trash** (palette, the vault context menu of the tree — right-click blank tree space): a popup listing what is in `.trash/` (newest first: name, original folder, when; a filter box). *Restore* puts it back at its old path (a free name like `Note (restored).md` if that is taken, its image links re-pointed) with its images; nothing is ever deleted for good from the app. `Vault.delete` now writes `.trash/<stamp>/.trash.json` (`{path, dir}`), because `.trash/<stamp>/a/b.md` alone cannot tell a deleted note `a/b.md` from a deleted folder `a`; older stamp folders (and conflict copies) list each note on its own (`core/trash.py`).

**Version history** (⋯ menu → *Version history*, palette): earlier versions of a note, kept in `<vault>/.paper-pile/history.db` (SQLite, separate from the rebuildable `index.db`).
- *When:* the note's text before the first save of an editing session (first save after opening it, or after 30 min without saving), and before every bulk change: AI writing into it, merge, tidy, restoring a version, reloading a change made outside the app.
- *Storage (diffs, not copies):* per note, the newest version is stored in full; every older one as a reverse line diff (`difflib`, JSON ops `keep n` / `replace n with lines`, zlib-compressed) against the next newer one, and a full copy every 25 versions. Each version keeps the SHA-256 of its text; a rebuilt version that does not match is shown as damaged, never as text. Identical text is not stored twice.
- *Thinning:* everything from the last 24 h; then one per day for 7 days, one per week for 30 days, one per month after that (the newest in each slot). Dropping versions re-encodes the note's chain. *Cap:* when the history passes 50 MB, the oldest versions go first.
- *Follows the note:* rename/move re-keys it; a deleted note keeps its history (restoring it from the trash brings it back).
- *Popup* (`gui/components/history_dialog.py`): versions newest first (when, why, lines a restore would add/remove); the selected one shown as a diff against the current note or as plain text; *Restore* replaces the note's text (an undoable editor change, after recording the current text), *Copy* copies it.

### 4.19 Motion — user request 2026-10-22
Short, quiet animations that show *where something went*. Render-only (CSS + the editor bundle); Python only passes the speed.

**Rules.** Only `opacity` and `transform` are animated, never a size CodeMirror measures (line heights, widget heights, pane widths), so clicks never drift and layout is final at once. Nothing runs while the user types in the moved text. Base durations: fast 100 ms (hover, fades), normal 160 ms (popups, chevrons, slides), flash 900 ms (the target highlight fades out). All durations = base × the speed factor.

**Setting: Animation speed** (`appearance.motion`, Settings → Appearance, essential): segmented *Off · Fast · Normal · Slow* (factor 0 / 0.6 / 1 / 1.6, default *Normal*). Applies live (no reload): `static/theme.js` sets `--pp-motion` (every CSS duration is `calc(base × var(--pp-motion))`) and `window.ppMotion`, which the editor bundle reads when an animation starts (`motion.js` `motionFactor`), so both split editors follow without a reconfigure. *Off* = no transitions, no smooth scroll, jumps still land with a static highlight that disappears on the next keystroke or click. While the setting is untouched and the OS asks for reduced motion (`prefers-reduced-motion`), it behaves as *Off*.

**Moves and jumps (editor):**
- *Page number moved* (page view): when a new layout moves the start of page N to another line, the **Page N** line (page-line style) or the page edge with its number (real-pages style) slides from its old screen position to the new one. Only the label is moved (`translateY`, from the old offset to 0, at most one screen); the space it takes is in place at once. The lines that crossed onto the other page get a soft accent tint that fades out (the *block jump*: you see which text went to the next/previous page). A changed page number cross-fades. The sheet padding in real-pages style changes instantly (it is measured).
- *Page break dropped* (`pagedrag.js`): on release, the line glides from the pointer to its final line.
- *Line / heading jump* (outline, wikilink to a heading, backlink, search result, `gotoLine`): smooth scroll when the target is within 3 screens (farther: jump to one screen away, then glide); the target line flashes with an accent background that fades out.
- *Block moved* (Alt+↑/↓, block drag): the moved lines slide in from where they were (`translateY`) and flash briefly.

**App chrome:** context menu and tooltips fade/scale in; chevrons (outline, backlinks, model picker, heading fold) rotate instead of swapping icons (the file tree redraws its rows, so its chevrons still swap); hover backgrounds and the tab close × fade; the task checkbox tick scales in; banners, chat jump buttons and new chat messages fade in; the chat shows pulsing dots until the first token.

**Not animated:** typing, CodeMirror decorations and folding, pane widths (Ctrl+B / Ctrl+L), sheet heights, drag in progress.

### 4.25 Note header, pins, small UI fixes — user request 2026-10-24 (P21)
User list of 12 items (numbering theirs, merged); questions answered: top row as tall as the Backlinks bar; pins both as tabs and in the tree; double-click on a pane's edge; header sections are `#` / `##`; icon colour only Default / Accent (no rounded-square style); creation date not shown (version history has it); kanban only as Mermaid's diagram.
- **Top rows** (tab strips, left pane's title row, ribbon top, window buttons) are `--pp-tab-h` = 41 px, the height of the footer / Backlinks bar; the tabs in them start 6 px lower (air above the tabs). Tab rows look like a browser's: inactive tabs sit on the row with a short divider between them, the active tab is outlined (top and sides, rounded top corners, its bottom corners ramping out into the row's line), open at the bottom and in the colour of what is below it (editor white, right pane grey), so it joins it, and the round + follows the last tab. The Backlinks bar's height is the standard: the note header, the Files header and the chat's title row are 41 px too.
- **Icons:** all are vendored Lucide (`static/vendor/lucide/icons.json`), served by the app (`/_pp/icon`, cached); nothing comes from the web, so nothing to replace. Every AI / chat entry point uses `sparkles` (chat tab, AI button, Add to chat, Ask, AI on/off); specific AI actions keep their own icons (Rewrite, Summarize…).
- **Icon colour** (Settings → Appearance, not essential): Default, or Accent — every line icon in the accent colour, except icons with a meaning of their own (status dots, ticks, danger) and icons on an accent background (send, Restore, avatar, selected day); note text is not touched. `appearance.icons`, body class `pp-icons-accent`.
- **Pinned notes** (session: `pinned`, in order): a pinned note's tab comes first (core `TabList` keeps pinned tabs first; a drag never mixes the groups), shows a pin and no ×, ignores middle-click, and reopens at every start even if it was closed. The tree lists pinned notes in a **Pinned** group above the folders. Pin / Unpin from the tab menu, the tree's right-click menu and the ⋯ menu. Renames and moves keep the pin; deleting the note unpins it.
- **New note buttons:** a + at the end of each folder row (on hover) makes `Untitled N` in that folder; a + after the tabs makes one in the vault's top folder.
- **Tab overflow arrows** are small rounded boxes inside their (opaque) areas.
- **Pane edges:** an 8 px band centred on the edge is tinted like the outline's divider while the pointer is on it (resize cursor) and while it is dragged; a double-click on a pane's edge folds that pane, and a double-click on the folded file tree's edge (beside the ribbon) opens it again. The folded right pane has no edge to click (the window's own resize strip is there): Ctrl+L / its button.
- **Note header** (one per editor side, `gui/components/note_head.py`; 41 px, its boxes level with the Files header's box; the arrows are plain buttons, no box; the side being typed in only has its title in the accent colour): ‹ › (chevron up / down) jump to the previous / next section start — sections begin at `#` and `##` (`core/sections.py`; ‹ goes to the start of the section on screen, or the one before when already there) — then the note's title (its `title` property, else its name) and the section at the top of the view, each cut short with … when long, and on the right the note's own split, AI and ⋯ buttons (they act on that side's note; in split view the split button closes that side and a click on the title shows another note there). The section follows scrolling (the editor reports the line at the top of the view). Replaces the note buttons in the tab strip and the floating name islands of split view.
- **Inline code in tables** is the same chip as in text (`pp-code`).
- **Last edited:** the properties box shows a read-only "edited" row (the file's time: today 14:05, yesterday …, Oct 12 …) that is not written into the file; Settings → Editor → "Last edited" (`editor.last_edited`, on) hides it. Notes without properties show none.
- **Tree:** 4 px between a folder's chevron and its icon.
- **Chat:** a selection (or block) sent with a message is kept with that message (`SavedTurn.quotes`) and shows as the same chip as in the composer; a click unfolds its text.
- **Note picker** (split's *Open on the right* / *Show here*, *Merge into…*): the palette's look and place (top, borderless search with the title as placeholder, ×, same rows).
- **`/kanban`:** inserts a Mermaid `kanban` diagram (columns with cards), drawn like the other diagrams.

### 4.24 Memory — user request 2026-10-24 (P20)
User: the app feels heavy; wants it lighter, platform-independent work first ("go for 1"), engine changes (system WebKitGTK, browser app mode) later. Measured on the user's machine after ~2 h: page renderer 1.3 GB RSS, Qt window process 514 MB, Python server 105 MB; `.venv` 722 MB (PyQt6 520 MB). Goal: find what grows over a session and stop it, with no visible change; disk size is left to the later engine options.
- **Measured, not guessed:** `tools/mem_soak.py` (dev tool) drives a long session (open / switch / close tabs, popups, notes with math, diagrams, tables, images) on a throwaway vault and prints JS heap, DOM nodes, listeners and process RSS per round.
- **Dialogs leave nothing behind:** every dialog is a `paper_pile.gui.dialog.Dialog` (never `ui.dialog`): NiceGUI's hidden "canary" element (whose finalizer holds the dialog) is deleted with it, so a closed dialog is freed in the page and on the server. Dialogs made anew each time and only closed (note picker, Ask AI) are deleted when hidden; the crash-recovery dialog (once per crash) stays as it is.
- **No piling timing entries:** Tailwind's in-browser compiler adds a `performance.mark` / `measure` on every rebuild and never clears them; `static/marks.js` clears them every 30 s.
- **Later (needs a screenshot comparison):** run without Tailwind (`ui.run(tailwind=False)`): only `w-full` is a Tailwind-only class, but Tailwind's Preflight reset would go too.

### 4.23 Performance — user request 2026-10-24 (P19)
User: startup, scrolling, moving panes, opening / closing / switching tabs, popups and new notes feel laggy; "keep the UI as it is". Measured offscreen on a generated 2 000-note vault (`tools/perf_ui.py`): switch tab ~770 ms (browser ~160 ms), close tab ~850 ms, new note ~2.4 s, startup ~31 s to the first text — the rest was the server's event loop being busy or blocked. No visible change; only when and where the work runs.
- **No vault walk per tab switch:** the names wikilinks may use (`set_known_notes`) come from the index, are cached, and reach the editor only when the set of notes changed.
- **The index lock is never held during disk work:** `Index.sync` / `update_note` walk, stat, read and parse outside the lock and take it only for one short write transaction. A row that changed since the snapshot (a save indexed it meanwhile) is not overwritten with the older read; a "gone" file is only removed if it is still missing.
- **One stat per file per walk:** `Vault.walk_notes` uses the directory entries (`os.scandir`) instead of an extra `is_symlink()` per file.
- **Cheap word count:** `body_start` finds the front matter by scanning lines, not by a markdown parse of the whole note.
- **Calendar on tab switch:** `day_marks` lists each daily-notes folder once and re-reads a note only when its mtime changed (cache in the pane); the month grid is rebuilt only when what it shows changed (month, today, marks, selected day, settings).
- **Session file on tab switch:** debounced like the pane widths (`SAVE_DELAY_S`), flushed when the page disconnects (window closed), instead of a write + fsync on every switch.
- **Backlink snippets:** the source note's text is cached by the mtime the index has for it (`Backlink.mtime`), so listing backlinks reads only notes that changed.
- **Startup:** last session's tabs open before the index sync (from last run's index); the sync of what changed while the app was closed runs afterwards off the UI thread and then refreshes links and backlinks. With no index yet, the known-note list falls back to one vault walk.
- **Measured, not guessed:** `tools/perf_ui.py` (dev tool) times startup and the actions above and prints frame stats for scrolling and pane toggles.
- Environment (not code, user's side): on WSL keep the repo, `.venv` and vaults on the Linux file system (on `/mnt/*` imports took 30.8 s instead of 3.0 s and a vault walk 45× longer), and use a distro whose Mesa has the `d3d12` driver (the RHEL 10.1 distro renders with llvmpipe, i.e. without the GPU).

### 4.22 Popups, window, line numbers — user request 2026-10-23 (P18, re-applied in part)
P18 was reverted as a whole, then these parts were asked back; the note buttons stay in the tab strip and the split backlinks still open together.
- **Double-click on a tab row** (tabs or the empty space beside them) never maximizes the window; other top rows still do.
- **Tab arrows:** their hover tint is laid over the pane colour, so the area stays opaque.
- **Picker (palette, quick switcher):** opens and closes without animation; a × in its top right; shortcuts as key caps (one rounded box per key).
- **Slash menu:** the side (below / above the caret) is decided once from the menu's full size (`.pp-slash-wrap`, a transparent box as tall as the menu can get); the menu stays invisible until Python's first results, so it appears at its real size and never jumps.
- **Line numbers** count after the properties block (see P14 *Line numbers*).

### 4.21 Tabs, tool boxes, settings, palette — user request 2026-10-22 (second round)
- **Tab overflow:** while a tab row overflows, a ‹ and a › each get their own 26 px area at the row's edges, split from the tabs by a vertical line (the row is padded by them, so no tab hides underneath); a click brings the next hidden tab on that side fully into view — one tab per click; an arrow with nothing more on its side is dimmed.
- **Tool boxes:** Files header (search · new folder · new note), the folded rail's same three, and the note buttons (split · AI · ⋯) sit in one box each, like vault · palette · settings (`pp-seg pp-tools`, 16 px icons).
- **Settings:** boxes (§6 row rules); groups everywhere — General: Features, Language, *Startup and files*, Paste, Images, Daily notes, Templates, *Advanced*; Editor: Font, Layout, Writing, Page view (with Paper size), Advanced; AI: Model, Context, Memories, Advanced (with the unused embedding model).
- **New settings:** Reopen last tabs (`general.restore_tabs`, on), Ask before deleting (`general.confirm_delete`, on), Readable line length (`editor.readable_width`, off: 46em column outside page view), Highlight current line (`editor.highlight_line`, off), Word count (`editor.word_count`, on: the status bar's words · Ln · Col). General → Advanced: *Rebuild search index* (full settings).
- **AI chat:** "AI can make mistakes. Check important information." under the chat box.
- **Command palette:** groups with headings (Notes, Tabs, Editing, Export, AI, View, App; a query orders groups by their best match). Added: today's daily note, rename, show in file tree, copy full path, close other tabs, new chat, rewrite, write with AI, line numbers / wrap / readable width / current line on-off, animations on / off, rebuild search index.

### 4.20 Icon and small UX fixes — user request 2026-10-22
From the icon / UX survey (same day). **Icons:** one Lucide set everywhere (heading fold chevron, tab scroll arrows and table *+* buttons were text glyphs or a hand-drawn SVG); sizes only from the 14 / 16 / 18 px tokens (no 13 / 15 px, no icon wider than its box); one close button for dialogs and panes (`icons.close_button`: 16 px × in a 30 px button — Settings, Version history, Trash, Gallery, Memories); menu check marks are `check`, 14 px, accent colour; row icons 16 px; the corner radius of hover buttons from the tokens. **UX:** the tree's 🔎 says what it does (*Search in all notes*); tooltips warm up (after one has shown, the next shows at once for 0.8 s); visible keyboard focus (`:focus-visible` ring); hover-only delete buttons (memories, saved chats) reachable by Tab and Enter; a bigger tab × target; an empty vault shows a **New note** button in the tree; the status bar shows nothing while no note is open (no "Ready") and *Saved* has a "Saved at 14:32" tooltip (the file's time); a folded heading's *…* says how many lines it hides.

## 5. Data formats

**SQLite schema (`.paper-pile/index.db`)** — cache only:
```sql
notes(id INTEGER PK, path TEXT UNIQUE, title TEXT, mtime REAL, hash TEXT)
links(src_id INT, dst_raw TEXT, dst_path TEXT NULL, kind TEXT, line INT)
notes_fts USING fts5(path, title, body)
meta(key TEXT PK, value TEXT)   -- schema_version
```
- On open: compare mtime/hash, re-index changed files. `Rebuild index` command drops and rebuilds.

**session.json** (`core/session.py`): `{ "tabs": [...paths], "active": path|null, "pane_widths": {"left": 260, "right": 340}, "panes_open": {"left": true, "right": true}, "mode": "live"|"source" }`. Read tolerantly (bad/missing fields fall back to defaults individually); written atomically; a write failure is logged, never fatal.

---

## 6. Phases & tasks

Status lives in TRACKER.md. Each task: do it → verify acceptance → update TRACKER.
Order matters: risky spikes come first.

**Model guidance (🧠 = use Opus).** The session runs on `opusplan` (Opus in plan
mode, Sonnet otherwise). Tasks marked 🧠 are highly specialized (CodeMirror 6
internals, or data-corruption risk). For these: **design in plan mode (Opus)**,
and if the implementation gets stuck after 2 failed attempts, switch with
`/model opus` and finish on Opus, then switch back. Every unmarked task is fine
on Sonnet. Only mark a task 🧠 when it is genuinely this specialized.

| 🧠 task | Why |
|---|---|
| P0.4 🧠 | CM6 as a NiceGUI element: view/state/extension model, paste + keydown hooks, first live-preview decorations |
| P0.5 🧠 | KaTeX/Mermaid as CM6 widget decorations (block widgets, cursor-aware reveal, offline, theme re-render) |
| P2.4 🧠 | Full Live Preview: cursor-aware syntax hiding, replace/line/widget decorations, tables, clickable tasks; hardest code in the project |
| P3.5 🧠 | Rename-safe rewrite across the vault: must not corrupt notes (code fences, aliases, anchors, relative paths) |
| P4.2 🧠 | Slash popup inside CM6: caret-positioned tooltip, trigger rules (not in code/URLs), key handling coexisting with live-preview decorations |

### P0 — Foundation
| ID | Task | Acceptance |
|---|---|---|
| P0.1 | `uv init`, pyproject (deps pinned, script entry `paper-pile`), ruff/mypy/pytest config | `uv run paper-pile --help` works; `uv run pytest` runs (0 tests ok) |
| P0.2 | Repo skeleton per §3, empty modules with docstrings | tree matches §3 |
| P0.3 | `core/events.py` pub/sub + `core/config.py` (defaults, load/merge/save TOML) | unit tests for merge order + save round-trip |
| P0.4 🧠 | **Spike S1 — editor component.** Build minimal CM6 bundle with esbuild, wrap as custom NiceGUI element; prove: load text, change event → Python, set text from Python, insert at cursor from Python, keydown hook for `/`, paste event with html+image → Python, **and live-preview decorations (hide `**`/`#` off-cursor, one KaTeX widget)**. Check first whether NiceGUI's built-in `ui.codemirror` allows custom extensions; if yes, prefer it. | Demo page does all 6 things; decision logged; PLAN §2/§4.5 updated with chosen approach |
| P0.5 🧠 | **Spike S2 — widget rendering.** Mermaid + KaTeX (vendored) as CM6 widgets inside the editor; theme switch re-renders mermaid | Demo renders a mermaid diagram + inline/display math inside the editor offline (network disabled) |
| P0.6 | **Spike S3 — native mode.** `ui.run(native=True)` with pywebview[qt] on Ubuntu; keyboard shortcuts reach the app (Ctrl+P, Ctrl+W not swallowed) | Window opens, shortcuts verified; fallbacks logged if any are swallowed |

### P1 — Shell & vault
| ID | Task | Acceptance |
|---|---|---|
| P1.1 | `cli.py`: vault arg, last-vault memory, `--serve` with token + 127.0.0.1 bind | all 4 CLI forms in §4.1 work |
| P1.2 | `core/vault.py`: list tree (hide dot entries), read/write (atomic), create, rename/move, delete→trash, duplicate | unit tests on tmp vault incl. trash + atomic write |
| P1.3 | 3-pane layout with resizable/collapsible panes, empty chat panel, status bar stub | manual QA: resize, collapse, widths persist |
| P1.4 | Tree component + context menu + drag-move | manual QA |
| P1.5 | `core/watcher.py` → events → tree refresh | creating a file from terminal appears in tree < 1 s |

### P2 — Editor, tabs, preview
| ID | Task | Acceptance |
|---|---|---|
| P2.1 | Editor component (from S1) wired to open file, autosave (debounce + atomic), recovery buffer | edit → file on disk updates; kill app mid-edit → recovery offered |
| P2.2 | Tabs per §4.4 (no preview tab), restore session | manual QA checklist §4.4 all pass |
| P2.3 | `core/parser.py` markdown-it setup + dollar math rule + front matter | unit tests: tables, tasks, footnotes, `$5 and $10` not math |
| P2.4 🧠 | Live Preview decorations (headings, emphasis, lists, tasks, quotes, tables, links, code, math/mermaid widgets) + Source mode toggle | manual QA: syntax hides off-cursor, reappears on cursor |
| P2.5 | External-change handling (reload / conflict banner) | edit open file from terminal → correct behaviour both clean and dirty |
| P2.6 | `.txt` plain mode | .txt opens without preview/slash |

### P3 — Links & index
| ID | Task | Acceptance |
|---|---|---|
| P3.1 | Wikilink markdown-it plugin (`[[a]]`, `[[a\|b]]`, `[[a#h]]`) | unit tests |
| P3.2 | `core/index.py` schema, incremental index, FTS, rebuild | unit tests; 1,000-note synthetic vault indexes < 5 s |
| P3.3 | `core/links.py` resolve + click-to-navigate + create-on-missing; Ctrl+click new tab | manual QA |
| P3.4 | Backlinks pane with snippets | manual QA |
| P3.5 🧠 | Rename-safe link rewriting across vault + toast | unit test: rename updates wikilinks + md links in N files |

### P4 — Slash menu
| ID | Task | Acceptance |
|---|---|---|
| P4.1 | `core/commands.py` registry, decorator, actions, fuzzy match, recents | unit tests |
| P4.2 🧠 | Notion-style popup in editor JS per §4.8 (look + keys + trigger rules) | manual QA vs reference screenshot; not triggered in code/URLs |
| P4.3 | Implement non-AI phase-1 commands + note picker | each command inserts correct markdown |
| P4.4 | Edit tables in the rendered cells: `core/tables.py` (parse, format, ops) + `tablewidget.js` + `table_op` events | unit tests (ops round-trip); browser QA: type in cells, Tab/Enter/arrows, add/delete row/column, align, undo |

### P5 — Images
| ID | Task | Acceptance |
|---|---|---|
| P5.1 | `core/assets.py` save (hash name), reference format, lifecycle table §4.9 | unit tests for every lifecycle row |
| P5.2 | Paste / drag-drop / `/image` → save + insert | manual QA all 3 sources |
| P5.3 | Live-preview drag-resize → rewrite width | width persists in source, other markdown untouched |
| P5.4 | Tree hides `.*.assets`; vault ops call assets lifecycle | rename note in tree → images still render |

### P6 — Smart Paste
| ID | Task | Acceptance |
|---|---|---|
| P6.1 | Collect fixtures (ask user to paste samples from ChatGPT/Claude/Gemini/DeepSeek, or capture via a debug "dump clipboard HTML" command) | ≥ 4 sources × 4 cases in `tests/fixtures/paste/` |
| P6.2 | `core/paste.py` html_to_md + normalize per §4.10 | all fixture tests pass |
| P6.3 | Wire into editor paste; Ctrl+Shift+V raw; setting toggle | manual QA |

### P7 — AI
| ID | Task | Acceptance |
|---|---|---|
| P7.1 | Provider protocol + OllamaProvider + health check + status dot | unit tests with mocked client; banner when Ollama down |
| P7.2 | Chat pane: model picker, streaming, stop, markdown render, copy, insert into note | manual QA |
| P7.3 | Context builder + token budget + `@note` picker + "include open tabs" toggle | unit tests for ordering/truncation |
| P7.4 | AI slash commands with `StreamInsert` | `/summarize`, `/continue`, `/explain`, `/fix`, `/ask` work, Stop cancels |

### P8 — Settings, theme, profile
| ID | Task | Acceptance |
|---|---|---|
| P8.1 | Theme system (CSS vars, light/dark/system, accent palette, density); editor/preview/mermaid/chat follow | switching theme updates everything live |
| P8.2 | Settings dialog §4.12 + persistence (global + vault) | values survive restart; vault overrides global |
| P8.3 | Bottom-left profile block + quick theme toggle | manual QA |

### P9 — Navigation & polish
| ID | Task | Acceptance |
|---|---|---|
| P9.1 | Ctrl+P palette, Ctrl+O switcher (§4.18) | fuzzy, keyboard-only usable |
| P9.2 | Vault search (FTS) with snippets (§4.18) | hits with highlighted snippets; click opens with the query found (real app) |
| P9.3 | Outline panel (§4.18) | click heading → jumps; caret's section marked |
| P9.4 | Status bar complete | word count, Ln/Col, save state, ollama dot |
| P9.5 | Shortcut table §4.14 all wired | each verified |
| P9.6 | Full manual QA pass + README (install, run, shortcuts) | checklist below all ✅ |

### P14 — Features, navigation & safety (user request 2026-10-22, §4.18)
P9.1–P9.3 and P9.5–P9.6 are built in this phase (order: P14.1, P9.1, P9.2, P9.3, P14.2, P14.3, P14.4, P9.5, P9.6).

| ID | Task | Acceptance |
|---|---|---|
| P14.1 | Feature switches (AI, Calendar) + Minimal settings | each switch hides/shows its parts at once (real app); AI off → no Ollama request; minimal shows only essential rows; tests |
| P14.2 | File tree keyboard | every key in §4.18 works with real key events; tests |
| P14.3 | Trash popup + restore | restore puts a note (with images) and a folder back, free name on clash; core tests; real app |
| P14.4 🧠 | Version history (diff chain) | core: record/rebuild/thin/cap/rename tests incl. damaged diff; popup restore is undoable; real app |
| P14.5 | Outline in the Files pane | section under the tree, collapsible + resizable, state remembered; Ctrl+Shift+O; right-pane tab gone (real app) |
| P14.6 | Tab menu + note buttons (split, AI) | every item works on the right-clicked tab; buttons follow split state and the AI switch (real app) |
| P14.7 | Slash menu on right-click and on a lone `/` | right-click opens it at the click, inserted `/` removed on close, Cut/Copy/Paste; caret after a lone `/` opens it, not after `and/or`; qa_editor passes |
| P14.8 | Outline button on the folded rail | above Open vault; opens tree + outline (real app) |
| P14.9 | Many tabs: shrink + scroll + list | no tab under the note buttons; wheel / ‹ › scroll; list activates a tab (real app) |
| P14.10 | Backlinks per split side | two toggles (right one at the divider), side-by-side lists, own note each (real app) |
| P14.11 | Line numbers setting | on/off live; no sideways scroll in page view (real app) |
| P14.12 | Drag page breaks / page lines | move a break, add one from a page line (up only), click still reveals; core tests; qa_editor passes |
| P14.13 | Settings: Version + Vault first, Change… | order and button work (real app) |
| P14.14 | Page view: break lines hidden, drag limits, rest onto new pages | no break line drawn; down stops where the page is full, up stops below the previous page; auto-scroll; message when the page count changes (real app); qa_editor passes |
| P14.15 | Vault row adapts to the pane width | Change… inside the pane at every width, never over the path; after fold/unfold (real app) |
| P14.16 | Command palette button | in the vault · palette · settings box, row and folded rail; each opens its thing (real app) |
| P14.17 | `--debug` window log | every window change logged with state, size, screen, zoom, taskbar strips |

### P15 — Motion (user request 2026-10-22, §4.19)
| ID | Task | Acceptance |
|---|---|---|
| P15.1 | Motion tokens + **Animation speed** setting | `--pp-dur-*` × `--pp-motion` in app.css; Off/Fast/Normal/Slow live in the app and both split editors; OS reduced motion → Off while untouched; Off = zero running transitions (script check); core settings test |
| P15.2 🧠 | Jump: smooth scroll + target flash | outline / wikilink heading / backlink / search land with a flash that fades; far jumps don't scroll through the whole note; Off = static highlight cleared on next key/click; state in the runtime facet (no module globals); qa_editor passes |
| P15.3 🧠 | Page number moves + block jump tint | page-line and real-pages styles: label slides old → new position, crossed lines tinted, number cross-fades; no measured size animated (clicks hit the right line during the slide, CDP check); typing during a layout shows no animation on the caret line; qa_editor passes |
| P15.4 | Break drop glide + block move slide | page break released mid-gap glides to its line; Alt+↑/↓ lines slide + flash; Off = none |
| P15.5 | Popups: context menu, tooltip, banners, chat jump buttons | fade in/out via classes; a fading-out menu never takes clicks (real-click `elementFromPoint` check) |
| P15.6 | State polish: chevrons rotate, hover fades, tab ×, checkbox tick, chat dots + new message | one chevron + `pp-open` class (no icon swap round trip); dots gone on first chunk; NiceGUI tests pass; manual pass in the native window on WSL with no jank |

### P16 — Icon and small UX fixes (user request 2026-10-22, §4.20)
| ID | Task | Acceptance |
|---|---|---|
| P16.1 | Icons: one set, token sizes, one close button, one check mark | no text glyph / hand SVG icons left; no off-scale size in app.css; every dialog × is `close_button` (real click closes) |
| P16.2 | Small UX fixes (§4.20 list) | each works in the real app; empty-vault button has a NiceGUI test |

### P17 — Tabs, tool boxes, settings, palette (user request 2026-10-22, §4.21)
| ID | Task | Acceptance |
|---|---|---|
| P17.1 | Tab overflow arrows with own areas + one tab per click | dividers; first tab not under ‹; three › clicks = three more tabs; ‹ brings one back (real clicks) |
| P17.2 | Tool boxes (files header, rail, note buttons) | one box each (real app) |
| P17.3 | Settings boxes + groups, Paper size under Page view, no Print page | rows only inside boxes on every page; nothing overflows a box from 1400 to 600 px; rows settle (no flip); core tests |
| P17.4 | New settings (restore tabs, confirm delete, readable width, current line, word count, rebuild index) | each changes the app live / on next start; core tests |
| P17.5 | Chat disclaimer | under the chat box (real app) |
| P17.6 | Palette groups + missing commands | headings; new commands run (real app: line numbers) |

### P18 — Popups, window, line numbers (user request 2026-10-23, §4.22)
| ID | Task | Acceptance |
|---|---|---|
| P18.3 | No maximize on tab-row double-click | no `maximize` from tabs / the empty tab row (real double-clicks) |
| P18.4 | Opaque tab-arrow hover | gradient over the pane colour |
| P18.5 | Picker: no animation, ×, key caps | fully shown at once; × closes; caps drawn |
| P18.6 | Slash menu side decided once | near the bottom: opens above at once, position never changes (per-frame check) |
| P18.7 | Line numbers after the properties | gutter starts at 1 under the block; status bar Ln agrees |

### P19 — Performance (user request 2026-10-24, §4.23)
| ID | Task | Acceptance |
|---|---|---|
| P19.1 | `tools/perf_ui.py` timing harness | prints startup, tab switch/close, new note, palette, settings, context menu, scroll + pane frame stats on a throwaway vault (isolated XDG dirs) |
| P19.2 | Known note names from the index, sent on change only | tab switch does no vault walk; links to missing notes still styled after create / delete / rename |
| P19.3 | Index lock only around writes | sync / update_note do disk work unlocked; a concurrent save's newer row is kept (test); a re-created file is not removed (test) |
| P19.4 | Walk without extra stat per file | same notes found as before (symlink rules unchanged, tests) |
| P19.5 | Cheap `body_start` | same result as the parser on the fixtures (test); no markdown parse |
| P19.6 | Before / after numbers | perf_ui run recorded in TRACKER; tests + qa_editor green |
| P19.7 | Calendar: folder listing + mtime cache, redraw only on change | dots / open-task dot / selected day right (real app, default `.daily-notes`); unchanged notes not re-read (test) |
| P19.8 | Session save debounced, flushed on disconnect | a tab switch right before quitting is in session.json (real app) |
| P19.9 | Backlink snippets cached by indexed mtime | `Backlink.mtime` is the file's (test); snippets unchanged |
| P19.10 | Tabs before the startup sync | backlinks / link styles right after the background sync, incl. notes and links added while closed (real app) |

### P20 — Memory (user request 2026-10-24, §4.24)
| ID | Task | Acceptance |
|---|---|---|
| P20.1 | `tools/mem_soak.py` soak harness | per-round JS heap / nodes / listeners / RSS (renderer, window, server) on a throwaway vault |
| P20.2 | Find and fix what grows | named causes in TRACKER; growth per round near zero after warm-up; tests + qa_editor green |
| P20.3 | `Dialog` without the canary leak | deleted dialogs leave no element and are garbage-collected (test); DOM nodes / server RSS flat in the soak |
| P20.4 | Clear Tailwind's timing entries | no `PerformanceMark` / `Measure` growth in heap snapshots; heap flat in the soak |
| P20.5 | Quick switcher lists the vault once per popup | no vault walk per keystroke; results unchanged |

### P21 — Note header, pins, small UI fixes (user request 2026-10-24, §4.25)
| ID | Task | Acceptance |
|---|---|---|
| P21.1 | Top rows 41 px | tab strip = footer height (real app) |
| P21.2 | Spark icon for AI / chat | chat tab, AI button, Add to chat, Ask use `sparkles` |
| P21.3 | Icon colour setting (Default / Accent) | Accent colours icons, not send / status / note text (real app) |
| P21.4 | Pinned notes | pinned first, pin and no ×, reopen at start, tree group, rename keeps / delete drops (tests + real app) |
| P21.5 | + on folder rows and after the tabs | new note in that folder / the vault top (real app) |
| P21.6 | Rounded tab overflow arrows | arrows show as boxes when tabs overflow (real app) |
| P21.7 | Pane edges: highlight while dragged, double-click folds / unfolds | real-app checks |
| P21.8 | Note header per side | sections `#`/`##` follow scrolling, ‹ › jump, title / section cut with …, per-side split / AI / ⋯ (tests + real app) |
| P21.9 | Inline code chip in tables | same class and colour as in text (real app) |
| P21.10 | "edited" row in properties + setting | today / yesterday / date, hidden by the setting (tests + real app) |
| P21.11 | Gap between chevron and folder icon | 4 px |
| P21.12 | Sent selections unfold in the chat | quote kept in the saved chat (test); click unfolds (real app) |
| P21.13 | `/kanban` (Mermaid) | inserts a kanban block that renders (test + real app) |

### P10 — Note menu (⋯) (user request 2026-10-17)
| ID | Task | Acceptance |
|---|---|---|
| P10.1 | ⋯ button + menu; Find/Replace; Copy path; Add to chat; Open in default app (disabled) | each item works on the active note; search panel themed in both themes |
| P10.2 | AI → chat: Summarize, Rewrite, Write… | chat opens with the note attached; Summarize/Rewrite sent, Write… prefilled and focused |
| P10.3 | Move to… | note moves, images follow, links repaired, tab follows |
| P10.4 | Merge into… (`core/merge.py`) | merged text, images, incoming links, source in trash; unit tests |
| P10.5 | Export as Markdown / HTML (`core/export.py`) | self-contained files; native Save dialog, web download; unit tests |
| P10.6 | Split right | two editors, focus decides the active one, same-note sync, close split; slash/AI/links work in both |

### P11 — Tags (user request 2026-10-17)
| ID | Task | Acceptance |
|---|---|---|
| P11.1 | `core/tags.py` + parser rule + index table | fixture cases agree in Python and Lezer; index finds notes by tag (nested included) |
| P11.2 | Chips in the editor (inline + properties block) | chips in both themes; click reports the tag |
| P11.3 | `#tag` tab in the right pane | closable; lists every tagged note; follows saves |
| P11.4 | Open / Open in split | both work from the list |

### P12 — Page breaks & PDF (user request 2026-10-21, §4.17)
| ID | Task | Acceptance |
|---|---|---|
| P12.1 | `core/pagebreak.py` + parser rule + Lezer node | `pagebreak_cases.json` cases agree in Python and Lezer (code/quote/list/front matter excluded, empty-line rule, leading/trailing/consecutive); HTML export emits `break-after: page`; Markdown export unchanged |
| P12.2 | Manual break in the editor + `/page break` (palette: with P9.1, from the registry) | line widget in both themes, raw on the caret line; insert adds the empty lines; `tools/qa_editor.py` passes |
| P12.3 🧠 | Print layout: `core/printdoc.py` + `static/paginate.js` | fixture notes (long paragraph, tall code block, long table, image taller than a page, Mermaid, math, manual breaks) paginate by the §4.17 rules; no page box overflows (browser check); `printdoc` unit tests |
| P12.4 | Export as PDF (native `printToPdf`, `--serve` print tab) | the PDF's per-page text equals the paginator's pages for the fixture notes; native Save dialog checked by hand |
| P12.5 🧠 | Page view (⋯ menu + Settings toggle) | off by default; the ⋯ item and the Settings switch toggle the same setting and show its state; on: page lines sit on the same source lines where the PDF's pages start (fixture notes), text column = paper text width, properties block hidden and unreachable by the caret; off: everything back as before (caret + scroll kept); remembered across restarts; works in both split sides; typing stays smooth on a 1000-line note |
| P12.6 | Settings → Print: paper A4 / Letter | switching re-paginates the editor's page lines and the PDF |
| P12.7 | `---/` page break; Ctrl+Enter inserts it | `---/` cases in the shared fixtures agree (Python + Lezer); the HTML forms still read; slash command and Ctrl+Enter insert `---/` with empty lines (caret below) |
| P12.8 | Empty lines print as space | extra empty lines between blocks add one line each on paper; Enter pushes text onto the next page; empty lines at a page top dropped; printdoc tests + qa_print fixture |
| P12.9 | Page view setting Off / Page lines / Real pages | segmented choice in Settings; ⋯ toggles the last style (Page lines first); old `true`/`false` values read as Page lines / Off |
| P12.10 🧠 | Real pages in the editor | sheets as tall as the paper (padded), gaps where pages start, page numbers, margins; page starts = PDF; caret, clicks and scrolling unaffected (`qa_editor` + `qa_print` pass); both themes; split |

### P13 — Window, folders, images, split (user request 2026-10-21)
Spec (one place; the feature sections point here):
- **Window buttons:** maximize/restore is the same size as minimize/close (small icon), and its icon shows the state: `square` while normal, `copy` (two squares) while maximized — following the real window (double-click on the title area, OS snap), not a click counter.
- **Popups in the native window (P13.15):** `static/menus.js` re-places a Quasar menu whenever its size changes (menus filled by Python on `before-show` grow after Quasar placed them) and lifts menus and the tree context menu above `--pp-inset-bottom`; the editor's CodeMirror tooltips get the same space through `tooltips({ tooltipSpace })`.
- **Notifications in the native window:** every `ui.notify` (toasts like "Copied", errors) is visible inside the window's work area, above the footer, in both themes: Quasar's toast lists are offset by the taskbar insets of a maximized WSL window (`--pp-inset-*`) and the footer / tab-row height.
- **Scrollbar vs. pane edges:** where a scrollbar and a pane-resize edge (file tree | editor, editor | right pane, the split divider) meet, each keeps its own grab area: the resize strip sits outside the scrollbar (never on top of it), so dragging a scrollbar never resizes a pane and the resize cursor shows only on the strip.
- **Mode buttons in Settings:** above *Restore defaults* in the settings sidebar, the Light / Dark / System buttons (the `appearance.theme` setting) — a horizontal row while the sidebar is unfolded, a vertical column of icons while folded. The setting's label "Theme" becomes **Mode** (Settings → Appearance and search).
- **Settings → General layout (changed 2026-10-21, user request):** groups Version, Vault (path), Language, Paste, **Images** (Gallery button, folder, Clear), **Daily notes** (folder, Clear, *Show in file tree*, date format, template), **Templates** (folder, Clear, *Show in file tree*, *Your templates*). The memories folder is set only under Settings → AI → Memories. Folder rows are labelled *Folder*; the switches *Show in file tree*.
- **Settings rows (2026-10-22, user request; revised the same day):** no divider between rows — one only above each section heading (and the folded Advanced). Descriptions are a few words. A row's text keeps its natural width; when text and control do not fit side by side the control drops under the text (never a description wrapped beside a box) and its field stretches up to the next button (`pp-set-stacked`, set by `static/tabs.js` from the settled layout of each row). Buttons never put their text under their icon: a group that does not fit shows icons only, with the text as a hover tip (`pp-icons-only`).
- **Settings boxes (2026-10-22, user request, replaces the row rules above):** every group is a rounded box under its title (as in Obsidian); thin lines split the rows inside a box, nothing outside it (no divider above titles). Settings without a group form a box with no title. A row puts its control under its text only when its box is narrower than 400 px — a CSS container query on the box (`ppbox`), so the layout depends on width alone and cannot flip; switch rows never stack (`pp-set-row-inline`). `pp-set-stacked` and its JS are gone; `pp-icons-only` stays. No Print page: Paper size sits right under Page view (Editor → Page view).
- **Panes while Settings is open (2026-10-22):** dragging the right pane's edge past its minimum only resizes (never folds Settings away); folding or unfolding the file tree keeps Settings' on-screen width (the editor takes or gives the room), so Settings never grows, shrinks or flips between its wide and narrow forms.
- **Daily-note template (2026-10-22, user request):** the *Template* field (Daily notes) takes a note path typed in, or picked from a list whose first entries are the notes of the default daily-note templates folder `<templates folder>/daily` (`.template/daily`, created on open); *Browse* in the native window (a note inside the vault). It is copied into each new daily note as before.
- **Daily notes look like their template (2026-10-22, user request):** notes in the daily-notes folder and in the templates folder never get the automatic `title:` property (auto-title), so a daily note opens exactly as its template and a template never carries a title into other notes. When a day is opened from the calendar and its note still holds only what the app made (the plain `# date` heading or the current template, with or without an auto-added `title:`, `daily.untouched_daily`), it is made again from the current template; the old text is stashed in `.trash/` first, and a note open in a tab or written in by the user is never changed.
- **Your templates** (General → Templates; like System instruction): a *Write* / *From a file* switch. *Write*: pick an existing template or *New template* (+ a name), edit it in a large box stretched from its corner, *Write with AI* (describe it; the draft goes into the box), *Save* (creates `<templates folder>/<name>.md` or saves the open one), *Delete* (to the trash, after a warning). *From a file*: a vault note or a typed path to any `.md` / `.txt` (native: *Browse*), *Add as template* copies its text into the templates folder under its own name (`Name 1`… when taken) and opens it in *Write*. Core: `core/templates.py` (`list_templates`, `new_template`, `import_template`, `template_draft_messages`).
- **Vault folders** (Settings → General, one group each): Memories (`ai.chats_folder`), Images (`vault.images_folder`), Daily notes (`vault.daily_notes_folder`), Templates (`vault.templates_folder`). Defaults: `.memory`, `.image`, `.daily-notes`, `.template` (vault-relative); all four are created in every vault when it is opened (empty, harmless). A value the user already set wins over the new default. Each row: the folder (pick another folder inside the vault, or type one; dot folders allowed), a **Clear** button (moves everything inside to `<vault>/.trash/` after a warning that names the folder and how many files; the folder stays). Memories may also be outside the vault (P7.7). Old default chats (`.paper-pile/chats/`) move once into `.memory/` when no memory folder was chosen (never overwriting).
- **Tree and vault:** the four app folders are ordinary vault folders at the top level (`vault.PUBLIC_DIRS`: their notes are listed, opened, indexed and watched; every other dot entry stays out of reach). The file tree hides `.image` and `.memory` (and the chosen images folder) and shows `.template` / `.daily-notes` unless their switch is off (*Show daily notes / templates in the file tree*: `vault.show_daily_notes`, `vault.show_templates`; on by default). When the daily-notes/templates folder setting points elsewhere, the switch applies to that folder. A folder setting accepts a normal folder or one of the four app folders; the memories folder may also be absolute (`/…`, `~/…`).
- **Images → `.image`:** pasted, dropped and uploaded images go into the images folder (content-hash names as before); the note refers to them relative to its own folder (`.image/a3f9.png`, `../.image/a3f9.png`). Moving or renaming a note re-points those references; deleting a note leaves shared images alone. Existing per-note `.<stem>.assets/` folders keep working unchanged (their lifecycle stays as before).
- **Image gallery** (Settings → General → Folders → Images → *Gallery*; `core/gallery.py`, `gui/components/gallery.py`): a popup listing every image of the vault (images folder + per-note asset folders) grouped by day (file date, newest first), thumbnails in a grid; settings in the popup: thumbnail size (S/M/L), sort newest/oldest, filter *All / Used / Unused*, search by note name. Click an image: a details column beside the grid with a large view, its name, size, dimensions, date, path and the notes that use it (click opens the note), *Copy markdown* and *Insert into note* (path relative to the open note), *Move to trash* (warns only if notes still use it). Unused images have a dashed outline. The toolbar choices are kept while the gallery is open.
- **Split view:** the tab of the note on the right side sits in its own group that starts exactly at the split divider and follows it while dragged (`static/split.js` keeps `--pp-split-left`); the left group holds every other tab. Each side's note is marked: the side being typed in as the active tab, the other more softly (`pp-tab-shown`). A tab click shows that note on the side of its group. **Drag and drop** (`static/notedrop.js`, capture only → `EditorPane._on_note_drop`): a note dragged from the file tree or from a tab can be dropped on either editor side (opens it there); on a single editor the left half opens it there and the right half opens it in a split (an empty editor just opens it). The drop target is highlighted; the drop is taken before CodeMirror (no path typed into the note); folders and outside files are left alone (image drops still work).

| ID | Task | Acceptance |
|---|---|---|
| P13.1 | Window buttons | maximize/restore icon = minimize/close size; icon follows the real window state (checked in the native window) |
| P13.2 | Notifications visible in the native window | a toast is fully inside the window, above the footer (native window, CDP check + screenshot) |
| P13.3 | Scrollbar vs. resize edges | at each pane edge, a press on the scrollbar scrolls and a press on the strip resizes (real mouse events) |
| P13.4 | Mode buttons in Settings + "Mode" label | buttons work and show the current mode; horizontal unfolded / vertical folded; label "Mode" |
| P13.5 | Vault folders + Clear + tree switches + chat move | four settings with defaults, created on open, Clear → trash after a warning, switches show/hide `.template`/`.daily-notes` in the tree; core tests |
| P13.6 🧠 | Images in `.image` + reference rewrite | new images land in the images folder; refs re-pointed on move/rename (tests); old asset folders unchanged |
| P13.7 | Image gallery | grouped by day, size/sort/filter/search, details with users, copy/insert/trash; real-app checks |
| P13.8 | Split tab row + drag & drop | right pane tabs start at the divider; drag from tree/tab to either side / single editor opens it (real mouse drag) |
| P13.9 | Your templates (Write / From a file) | write, edit, AI-draft, save, delete and add-from-file work in the app; core tests |
| P13.10 | General regrouped; gallery details widen; folded Mode buttons | groups Images / Daily notes / Templates, no memories row, Gallery before the field; details column toggles wide; folded buttons centred and full width |
| P13.11 | Settings dividers + narrow layout; daily-note template path | dividers only above section headings; in a narrow pane help text never squeezed, field rows keep [button] field [Clear] on one line, switches beside their text; `.template/daily` created, listed first in the Template field, typed path saved |
| P13.12 | Settings polish: panes, concise text, stacked fields, icon-only buttons | Settings never folds by dragging, keeps its width when the file tree folds (900 / 1100 / 1500 px windows, per-frame check); no description wraps beside a box, stacked fields stretch, no icon above text, no overflow (General / AI / Editor at 480 / 650 / 900 px) |
| P13.13 | Daily notes follow their template | no `title:` added to daily notes or templates on open; an untouched daily note is re-made from the current template (old text stashed); a written-in one is never changed; other notes still auto-titled |
| P13.14 | Tree multi-select (user request 2026-10-22) | Ctrl+click toggles, Shift+click range, selection box from blank tree space; dragging a selected row moves all of them; group context menu (Add to chat / Delete N) |
| P13.15 | Popups stay on screen (user report 2026-10-22) | every menu / popup (Quasar menus incl. ones Python fills on open, tree context menu, editor slash/autocomplete) lies fully inside the window's visible area, above the taskbar strip of a maximized WSL window |

### Phase-1 final QA checklist
- [ ] Works fully offline (network off) except AI if Ollama is remote
- [ ] Rename a note with images + 5 backlinks → nothing breaks
- [ ] Paste a math-heavy ChatGPT answer → renders correctly
- [ ] Mermaid renders in both themes
- [ ] 10 tabs open, restart → restored
- [ ] Ollama stopped → app usable, clear banner
- [x] Delete note → recoverable from `.trash/` (Trash popup, P14.3: restored with its images, real-app checks)
- [ ] `--serve` reachable only on 127.0.0.1 and only with token
- [ ] Export as PDF: native window (Save dialog → file) and `--serve` (browser print dialog → Save as PDF); the pages match page view's page lines
- [ ] Native window on Wayland (default Qt backend): every §4.14 shortcut works (run `tools/spike_native.py`, press each, check the log). S3 injected keys only on the X11 backend; Wayland-native launches fine but its keys need this manual check

---

## 7. Deferred (not phase 1)
Vault RAG with `sqlite-vec` ·
graph view · split panes · tags/front-matter queries · daily notes & templates UI ·
git sync · TUI (Textual, reusing core) ·
RHEL/server packaging · multi-user/teams · cloud AI providers.

---

## 8. Risks
| Risk | Mitigation |
|---|---|
| Live Preview decorations (now phase 1) are the costliest part; cursor-aware hiding, widgets and `/` menu must coexist | Prove in S1/S2 before building on it; build incrementally (headings/emphasis first, widgets last) |
| Custom CM6 element in NiceGUI is harder than expected | Spike S1 first; fallback: CodeMirror 5 UMD (no build step, has show-hint addon) — log if used |
| pywebview swallows shortcuts | Spike S3; fallback key bindings or browser mode |
| PDF pages drift from the editor's page lines (fonts not loaded, rounding, the browser's print adding a blank sheet) | One paginator owns the pages: it fills fixed page boxes measured after `document.fonts.ready`, images decoded and Mermaid drawn; boxes a hair under one sheet with `overflow: hidden`; P12.4 compares per-page PDF text with the paginator's output |
| Chatbot HTML changes | Fixture tests; easy to add new fixtures |
| Rename rewriting corrupts notes | Atomic writes, tests, write to trash backup before bulk rewrite |
| Slow local models | Streaming, Stop, small default context budget |
