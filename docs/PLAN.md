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
- **Implementation (P1.3, `gui/layout.py`):** two nested px-sized Quasar splitters (outer: left | rest, inner: center | right with `reverse`), status bar under center + chat. Defaults 260 px / 340 px; limits while open: left 180–480, right 280–640 (dragging stops at the limits; collapse is by Ctrl+B / Ctrl+L or the two toggle buttons at the status-bar ends, not by dragging). A collapsed pane is exactly 0 wide, keeps its last width, and is disabled for dragging. Widths and open/closed state are saved per vault in `.paper-pile/session.json` (resize debounced 0.4 s, toggles immediately) and restored on every page load. Empty states only: the tree (P1.4), tabs/editor (P2), chat (P7) and the profile block at the bottom of the left pane (P8.3) plug into these slots.
- Editing modes (single pane, Obsidian-style): **Live Preview** (default for every note, new or existing: markdown syntax hides on non-cursor lines, rendered inline) / **Source** (raw markdown). Toggle Ctrl+E. No split preview pane.
- Clean, minimal, Cursor-like: thin borders, no heavy chrome, monospace editor font.

### 4.3 Dir tree
- Shows `.md` and `.txt` files + folders. Hides dotfiles/dot-folders (`.paper-pile`, `.trash`, `.*.assets`).
- Context menu: new note, new folder, rename, delete (→ trash), duplicate, reveal in file manager.
- Drag to move file/folder (move = rename → links + assets updated).
- **`core/vault.py` contract (P1.2):** `Vault(root)` takes vault-relative POSIX paths only. Absolute paths, `..`, backslashes, any dot-component (`.trash`, `.paper-pile`, `.*.assets`) and paths resolving outside the vault (symlink escapes) raise `InvalidPathError`. Files must be `.md`/`.txt`. Writes are atomic (`fsutil.atomic_write_bytes`: temp + fsync + replace, mode kept) and preserve CRLF; non-UTF-8 files raise instead of being decoded lossily. `create_note`/`create_folder`/`rename`/`duplicate` never overwrite (`ExistsError`). `list_tree(rel)` returns one level (lazy), folders first then notes, case-insensitive. `delete` moves to `.trash/<YYYY-MM-DDTHH-MM-SS-µs>/<original relative path>` (nothing is unlinked). `duplicate` makes `<name> copy`, `<name> copy 2`, … Asset folders and link rewriting are layered on by P3.5/P5.4.
- Lazy-loads large folders. Live-updates from watcher events.
- **Implementation (P1.4, `gui/components/tree.py` + `static/tree.js`):**
  - Rows are flat and indented by depth; a folder's children are listed (via `Vault.list_tree`) only while it is expanded, and expanded folders are remembered for the session (not persisted yet). `FileTree.refresh()` re-lists from disk and is what the watcher (P1.5) calls.
  - Single click on a folder toggles it; single click on a note selects it and publishes `tree.open`. No preview tab (see §4.4).
  - Context menu (right-click, on a row or on the empty area): folder → New note, New folder, Rename, Duplicate, Delete; note → Rename, Duplicate, Delete; empty area → New note, New folder; **Reveal in file manager is added in native mode only** (it would open a window on the server in `--serve` mode). The menu is teleported to `<body>`; Escape or an outside click closes it.
  - Names go through `core.vault`: `validate_name` (no `/`, `\`, leading dot, empty, >255 bytes), `note_filename` (adds `.md` unless `.md`/`.txt` typed). New-note/folder dialogs propose `Untitled` / `New folder` (made unique). Rename shows a note's name without its extension and keeps the extension unless one is typed. Delete asks for confirmation and moves to `.trash/` (§4.9 lifecycle covers assets later). Duplicate → `<name> copy`.
  - Drag & drop: drop a note or folder on a folder row to move it there, or on the tree background to move it to the vault root; dropping on a note does nothing. Moves never overwrite; a folder cannot go into itself or a descendant; refusals show a toast.
  - Event bus topics (published on `MainLayout.bus`): `tree.open(path)`, `vault.renamed(old, new)` (rename or move; a folder path covers its children), `vault.deleted(path, trashed)`. Tabs (P2.2) subscribe to these.
  - **Live updates (P1.5, `core/watcher.py`):** one `VaultWatcher` per process (`watchdog`/inotify, recursive) publishes `vault.fs_changed(events=[FsEvent…])` on an app-level bus; each open page's `MainLayout` subscribes (and unsubscribes on disconnect) and calls `FileTree.refresh()` once per batch. `FsEvent(kind, path, is_dir, old_path)` with kind `created|deleted|modified|moved`, vault-relative POSIX paths. Dropped before publishing: hidden paths (`.trash`, `.paper-pile`, `.assets`, atomic-write temp files), non-note files, and folder "modified" noise. A move into `.trash/` is reported as `deleted`, out of it as `created`; renaming a note to/from a non-note extension is `deleted`/`created`. Raw events are coalesced over a 150 ms window that starts at the first event (a terminal change shows in the tree in ~0.2 s). `core` stays UI-free: the owner passes `dispatch` (the GUI uses `loop.call_soon_threadsafe`) so delivery happens on its own thread. The app's own writes also echo back as events (harmless for the tree; **P2.5 must recognise its own saves**, e.g. by content hash, and not treat them as external edits). If the OS refuses to watch (inotify limit) the app logs a warning and runs without live updates.
  - Not in P1.4: keyboard navigation, F2/Delete keys, multi-select, persisted expansion, virtualised rows (the flat rows are rebuilt on every expand/refresh, not benchmarked on very large expanded folders).

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
  - **Tables:** a real `<table>` block widget (alignment from the delimiter row, inline markdown inside cells); editing is in the source, which appears while the caret is in the table (no inline cell editing in phase 1).
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
- **Rename-safe:** renaming/moving a note rewrites every `[[...]]` and `(...md)` reference to it across the vault, in one operation, with a summary toast ("updated 7 links in 4 notes").

### 4.8 Slash command menu (`/`)
- Trigger: typing `/` at line start or after whitespace. Not inside code blocks/inline code, not in URLs.
- Notion-style popup at the caret: search field placeholder "Type to search", grouped sections, icon + label + optional subtitle/badge + right-aligned markdown hint, footer "Close menu · esc".
- Fuzzy filter on name + aliases; empty groups hidden; recently used float to top (top 5, persisted).
- Keys: ↑/↓, Enter apply, Esc close (keeps literal `/`), Backspace past `/` closes.
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
| Basic blocks | text, h1–h4, bulleted list, numbered list, todo, quote, divider, callout |
| Code & math | code block, math block, inline math |
| Diagrams | mermaid (flowchart), sequence, gantt |
| Media | image (file picker), table (3×3) |
| Links | link to note (note picker), embed note |
| Insert | date, time, template (if templates folder set) |
| AI | summarize, continue writing, explain selection, fix grammar, ask… |

### 4.9 Images (traceless)
- Storage: hidden sibling folder per note: `notes/mamba.md` → `notes/.mamba.assets/`.
- Filename: first 12 hex of SHA-256 of bytes + original extension (dedupe, no collisions). PNG for pasted bitmaps.
- Reference inserted: `![image|<width>](.mamba.assets/a3f9c1d2e4b0.png)` — standard markdown path, width in alt (Obsidian convention).
- Sources: clipboard paste, drag-drop, `/image` picker.
- Resize: in live preview, drag image corner → rewrite only the `|<width>` number in the source.
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
- Test fixtures: real clipboard HTML captured from ChatGPT, Claude, Gemini, DeepSeek in `tests/fixtures/paste/<source>_<case>.html` + expected `.md`. Cases: inline math, display math, code block, table, nested list, mixed.

### 4.11 AI (Ollama)
- `Provider` protocol: `chat(messages, stream) -> AsyncIterator[str]`, `embed(texts)`, `models()`, `health()`.
- `OllamaProvider`: host from config (default `http://localhost:11434`).
- Startup health check; status bar dot (green/red). If down → friendly banner in chat pane ("Ollama isn't running — start it with `ollama serve`"), app still fully usable.
- Model picker in chat header, populated from `models()`.
- **Context building** (`core/ai/context.py`), filled in order until the token budget (configurable, default 6000 tokens; rough estimate chars/4):
  1. Selection (if any)
  2. Current note
  3. `@note` mentions in the chat message
  4. (option) all open tabs
  5. Linked notes (outgoing + backlinks, one hop) — truncated
- Chat: streamed tokens, markdown-rendered replies (math + mermaid render too), Stop button, per-message "Insert into note" and "Copy".
- `@` in chat input → note picker (fuzzy).
- Chat history kept per session (in memory) in phase 1.
- AI slash commands use the same provider + context builder and stream into the editor at the cursor (`StreamInsert`).
- Vault-wide RAG (embeddings + `sqlite-vec`): **not phase 1**.

### 4.12 Settings, theme, profile
- Bottom-left of left pane: avatar + name, ⚙️ settings, ☀️/🌙 quick theme toggle.
- Profile: local only (name, avatar image or initials). Name used in chat and optional `author:` front matter.
- Settings dialog sections:

| Section | Options |
|---|---|
| Appearance | Theme: Light / Dark / System; accent colour (6–8 preset palette); UI density (compact/comfortable) |
| Editor | Font family, font size, line height, word wrap, tab size, spell check, default preview mode |
| Vault | Attachments behaviour (fixed: hidden per-note), templates folder, daily-notes folder |
| AI | Ollama host, default chat model, embed model (future), context budget |
| Paste | Smart Paste on/off |

- Storage: global `~/.config/paper-pile/config.toml` (via platformdirs), per-vault overrides `<vault>/.paper-pile/vault.toml`. Load order: defaults → global → vault.
- Theming via CSS variables; editor + preview + mermaid + chat all follow theme (Mermaid theme switches to `dark`).

### 4.13 Navigation & status
- Ctrl+P command palette (all commands incl. settings actions), Ctrl+O quick switcher (fuzzy note open), Ctrl+Shift+F vault search (FTS5, results with snippets).
- Outline panel (headings of current note) — toggle, can live in left pane as a tab.
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
| Ctrl+Shift+V | Raw paste |
| Ctrl+, | Settings |

**Implementation notes (S3):** a single capture-phase `keydown` listener on `window` (`addEventListener(..., true)`), `preventDefault()` on Ctrl/Meta combos, forwards `{key, ctrl, shift, alt}` to Python (`ui.on` + `emitEvent`). With Shift held `e.key` is uppercase (`"F"`, `"V"`): always compare `e.key.toLowerCase()`. Verified in the native Qt window: all 12 shortcuts above are delivered and Ctrl+W does not close the window.

---

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
| P9.1 | Ctrl+P palette, Ctrl+O switcher | fuzzy, keyboard-only usable |
| P9.2 | Vault search (FTS) with snippets | manual QA |
| P9.3 | Outline panel | click heading → jumps |
| P9.4 | Status bar complete | word count, Ln/Col, save state, ollama dot |
| P9.5 | Shortcut table §4.14 all wired | each verified |
| P9.6 | Full manual QA pass + README (install, run, shortcuts) | checklist below all ✅ |

### Phase-1 final QA checklist
- [ ] Works fully offline (network off) except AI if Ollama is remote
- [ ] Rename a note with images + 5 backlinks → nothing breaks
- [ ] Paste a math-heavy ChatGPT answer → renders correctly
- [ ] Mermaid renders in both themes
- [ ] 10 tabs open, restart → restored
- [ ] Ollama stopped → app usable, clear banner
- [ ] Delete note → recoverable from `.trash/`
- [ ] `--serve` reachable only on 127.0.0.1 and only with token
- [ ] Native window on Wayland (default Qt backend): every §4.14 shortcut works (run `tools/spike_native.py`, press each, check the log). S3 injected keys only on the X11 backend; Wayland-native launches fine but its keys need this manual check

---

## 7. Deferred (not phase 1)
Vault RAG with `sqlite-vec` ·
graph view · split panes · tags/front-matter queries · daily notes & templates UI ·
export (PDF/HTML/single-file base64) · git sync · TUI (Textual, reusing core) ·
RHEL/server packaging · multi-user/teams · cloud AI providers.

---

## 8. Risks
| Risk | Mitigation |
|---|---|
| Live Preview decorations (now phase 1) are the costliest part; cursor-aware hiding, widgets and `/` menu must coexist | Prove in S1/S2 before building on it; build incrementally (headings/emphasis first, widgets last) |
| Custom CM6 element in NiceGUI is harder than expected | Spike S1 first; fallback: CodeMirror 5 UMD (no build step, has show-hint addon) — log if used |
| pywebview swallows shortcuts | Spike S3; fallback key bindings or browser mode |
| Chatbot HTML changes | Fixture tests; easy to add new fixtures |
| Rename rewriting corrupts notes | Atomic writes, tests, write to trash backup before bulk rewrite |
| Slow local models | Streaming, Stop, small default context budget |
