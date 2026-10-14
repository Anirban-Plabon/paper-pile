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
uv sync                          # install deps
uv run paper-pile .              # run native window on current dir as vault
uv run paper-pile --serve ~/n    # web mode on 127.0.0.1
uv run pytest -q                 # tests
uv run ruff check --fix && uv run ruff format
```

## When unsure
Ask the user a **short** question instead of guessing on anything that changes the spec, file format, or data safety. For pure implementation details, pick the simplest option, log it in the Decision log, and continue.

## Gotchas
<!-- Append one line per durable lesson: `- <area>: <lesson>` -->
- (none yet)
