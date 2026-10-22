# paper-pile

A local, Obsidian-like markdown note app: a clean three-pane window (files · editor · side pane)
over a folder of plain `.md` / `.txt` files, with optional built-in local AI through
[Ollama](https://ollama.com). Everything runs on your machine and works offline.

Your notes stay ordinary files. The app's own data (search index, session, version history) lives
in `<vault>/.paper-pile/` and can be deleted at any time; nothing is ever deleted for good — a
deleted note goes to `<vault>/.trash/`.

## Features

- **Live-preview editor** (CodeMirror 6): headings, tables you edit in place, math (KaTeX),
  Mermaid diagrams, images (paste / drop / resize), code blocks, callouts, task lists, tags,
  page breaks, optional line numbers. Ctrl+E switches to
  the raw source.
- **Links**: `[[wikilinks]]`, backlinks (one list per side while split), rename-safe (links and images follow a renamed note).
- **Find things**: quick switcher (Ctrl+O), full-text search over every note (Ctrl+Shift+F),
  command palette (Ctrl+P), outline of the current note under the file tree (Ctrl+Shift+O),
  tags.
- **Slash menu**: type `/`, right-click in the note (with Cut / Copy / Paste on top), or put the
  caret after a `/` that stands alone — blocks, templates, links, embeds, page breaks, AI
  commands.
- **Tabs**: many tabs shrink, then scroll (mouse wheel, ‹ › arrows) and the list button shows them
  all; right-click a tab to split, rename, move, merge, see its history, copy its path or
  close others; the buttons beside ⋯ split the editor and (with AI on) ask the AI about the note.
- **Safety**: autosave with crash recovery, outside edits detected (conflicts never overwrite),
  **version history** of every note (⋯ → Version history, restore with one click, Ctrl+Z undoes
  it), a **Trash** you can restore from (Ctrl+P → Open trash).
- **Side pane**: AI chat, calendar with daily notes, settings.
- **Print / export**: page view (page lines or real pages; drag a *Page N* line to start that page
  elsewhere — as far as the pages allow; the rest flows onto new pages), export as PDF, HTML or
  Markdown.
- **Smart Paste**: tidy markdown from web pages and AI chat answers (Ctrl+Shift+V pastes raw).

### Turning things off

Settings → General → **Features**:

- **AI** — off: no chat, no AI commands, and the app never contacts Ollama.
- **Calendar** — off: no calendar tab or daily-note settings.
- **Minimal settings** (on by default) — Settings lists only the essentials; turn it off to see
  every option. Search in Settings always finds everything.

## Install

Linux (and Windows through WSL2 / WSLg). Needs Python ≥ 3.12 and [uv](https://docs.astral.sh/uv/).

```bash
git clone <this repo> paper-pile && cd paper-pile
uv sync
```

The native window uses Qt WebEngine (installed by `uv sync`) on Qt's default Wayland backend. If
you force the X11 backend (`QT_QPA_PLATFORM=xcb`), install the xcb libraries Qt needs, e.g. on
Ubuntu: `sudo apt install libxcb-cursor0 libxcb-icccm4 libxcb-keysyms1 libxcb-xkb1
libxkbcommon-x11-0 libxcb-image0 libxcb-render-util0`.

For AI, install and start [Ollama](https://ollama.com) and pull a model (`ollama pull gemma4:12b`,
or any chat model — pick it in the chat's model menu). The app works fully without it.

## Run

```bash
uv run paper-pile ~/notes        # open ~/notes as the vault in a native window
uv run paper-pile                # reopen the last vault (asks for one the first time)
uv run paper-pile --serve ~/notes [--port 8080]   # web mode: prints a 127.0.0.1 URL with a token
```

Web mode only listens on `127.0.0.1` and needs the printed token. Browsers keep some keys for
themselves there (Ctrl+W, Ctrl+Tab, Ctrl+N): use the Alt alternatives below.

## Keyboard shortcuts

| Key | Action |
|---|---|
| Ctrl+P | Command palette |
| Ctrl+O | Quick switcher (Ctrl+Enter opens in the split) |
| Ctrl+Shift+F | Search in all notes |
| Ctrl+Shift+O | Outline of the note |
| Ctrl+N | New note |
| Ctrl+W / Alt+W | Close tab |
| Ctrl+Tab / Alt+PageDown | Next tab |
| Ctrl+Shift+Tab / Alt+PageUp | Previous tab |
| Ctrl+E | Live preview ↔ source |
| Ctrl+B | Show / hide the file tree |
| Ctrl+L | Show / hide the side pane |
| Ctrl+, | Settings |
| Shift+Alt+F | Tidy the note |
| Ctrl+Enter | Page break at the caret |
| Ctrl+Shift+V | Paste without Smart Paste |
| Ctrl+F / Ctrl+H | Find / replace in the note |
| `/` or right-click | Slash menu |

In the file tree (click it first): ↑/↓ move, Shift+↑/↓ select, ←/→ fold/unfold, Enter opens,
F2 renames, Delete moves to the trash, Ctrl+A selects all, Esc clears. Ctrl+click and
Shift+click select several notes; drag on empty tree space to draw a selection box.

## What is in a vault

| Path | What |
|---|---|
| `*.md`, `*.txt` | your notes (folders as you like) |
| `.image/` | pasted / dropped images |
| `.daily-notes/`, `.template/` | daily notes and note templates (shown in the tree; switchable) |
| `.memory/` | saved AI chats |
| `.trash/` | everything deleted (restore from Ctrl+P → Open trash) |
| `.paper-pile/` | the app's own data: search index, session, `history.db` (version history) |

Settings are in `~/.config/paper-pile/config.toml`; a vault can override them in
`<vault>/.paper-pile/vault.toml` (Settings → *Apply to: This vault*).

## Development

```bash
uv run pytest -q                                  # tests
uv run ruff check --fix && uv run ruff format     # lint / format
uv run mypy paper_pile/core                       # types of the UI-free core
tools/build_editor.sh                             # rebuild the editor bundle (needs Node)
uv run python tools/qa_editor.py                  # editor checks in a real window (~6 min)
```

`CLAUDE.md` has the project rules, `docs/PLAN.md` the spec, `docs/TRACKER.md` the status and
history of decisions.
