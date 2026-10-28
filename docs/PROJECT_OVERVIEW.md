# paper-pile — Project overview

## About
A local, Obsidian-like markdown note app for Linux. It has a clean three-pane window (files, editor,
side pane) over a folder of plain `.md` / `.txt` files, with optional local AI through Ollama.
It works fully offline. Notes stay ordinary files, and the app's own data (`.paper-pile/`) can be
deleted and rebuilt at any time.

## Target users
- Linux users (bare Ubuntu or WSL2) who write notes, docs or research in markdown
- Developers and students who want rich markdown (math, diagrams, tables) without a cloud account
- Privacy-minded users who want AI help that runs only on their own machine

## Problem it solves
Linux has no modern, polished markdown documenting tool with everything built in. You can use
plain editors (no live preview, links or search), or apps that are cloud-first, closed or
Electron-heavy and need plugins for basic features. paper-pile ships it all in one local app:
live preview, wikilinks, search, history, export and optional private AI.

## Install
Needs Python ≥ 3.12 and [uv](https://docs.astral.sh/uv/).
```bash
git clone <repo> paper-pile && cd paper-pile && uv sync
uv run paper-pile ~/notes          # without AI (default)
uv run paper-pile --ai ~/notes     # with AI (needs Ollama + a model)
uv run paper-pile --serve ~/notes  # web mode on 127.0.0.1
```
**Without AI:** AI is off unless you start the app with `--ai`. Without that flag the app never
loads the AI libraries or contacts Ollama, and Ollama does not need to be installed. You can also
turn AI off in Settings → General → Features.

## Highlighted features
- **Live-preview editor:** headings, editable tables, KaTeX math, Mermaid diagrams, images
  (paste, drop or resize), callouts, tasks, tags, Source mode (Ctrl+E)
- **Links:** `[[wikilinks]]`, embeds, backlinks; links and images update when a note is renamed
- **Find:** quick switcher (Ctrl+O), full-text search, command palette (Ctrl+P), outline
- **Slash menu:** blocks, templates, links, page breaks, AI commands
- **Tabs and split view:** pinned tabs, drag and drop, side-by-side notes
- **Safety:** autosave, crash recovery, conflict detection, version history, Trash
  (nothing is hard-deleted)
- **Print and export:** page view, page breaks, PDF, HTML and Markdown export
- **Smart Paste:** clean markdown from web pages and AI answers
- **Local AI (optional):** chat with notes as context, `@vault`, AI edits shown as a diff to apply,
  saved chats and memories, AI access set per vault
- **Calendar:** daily notes from templates
- **Polish:** themes (light and dark, accent colour), frameless window, per-monitor scaling on WSL

## Timeline
| Date | Work |
|---|---|
| Oct 13 | Planning docs |
| Oct 14 | P0–P3: setup, vault, 3-pane UI, file tree; editor with Live Preview; wikilinks, index, backlinks |
| Oct 15 | P4–P5: slash menu, editable tables, image assets, embeds |
| Oct 16 | P6–P8: Smart Paste, Ollama AI chat, themes, settings, calendar |
| Oct 17 | Frameless window, icons, note menu, split view, tags; baseline 818 tests green |
| Oct 20 | Light and dark rendering sweep; window kept above the Windows taskbar |
| Oct 21 | P12–P13: page breaks, print/PDF, saved chats, memories, AI settings, app folders |
| Oct 22 | P13–P17: switcher, palette, search, outline, trash, version history, motion |
| Oct 23 | P18 reverted, then partly re-applied; maximize bug cause found |
| Oct 24 | P19–P21: performance (tab switch 758 → 342 ms), memory leaks fixed, note header, pins |
| Oct 25 | Settings polish |
| Oct 28 | P22: optional AI (`--ai`), AiEngine, `/compact`, AI access per vault, AI edits as a diff |
| Oct 29 | P22: selection bar, edit modes, suggested prompts, `@vault` |

**Status:** 1,209 tests passing, editor QA 358/358.
