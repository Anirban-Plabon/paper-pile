# paper-pile — Plan v2: PDFs, OCR and vectorless agentic RAG

> v2 scope (user 2026-11-03). v1 (`docs/PLAN.md`) can still change; everything about PDFs
> lives here. Same rules as v1 (CLAUDE.md): `core/` has no UI imports, plain files are the
> truth, the AI harness only talks to `Provider`, nothing is fetched from a CDN, `--serve`
> keeps working.
>
> **Status: planning.** No tasks, no code. §13 lists the areas still to be discussed before
> tasks are written; anything marked *provisional* may change there.

---

## 1. Goal

Read reports, manuals and real books (up to ~500 pages) and answer questions about them
with page citations, on local models:

- **OCR + vectorless agentic RAG.** No embeddings, no vector store. The model navigates
  the document the way a person does (contents → chapter → section → pages), helped by
  keyword search (SQLite FTS5).
- **Vision model kept.** Figures, charts, graphs and screenshots are read by a vision
  model; tables can be checked against the page image.
- **Never freezes, never breaks halfway.** Long work runs in the background, resumes
  where it stopped, and a bad page never stops a job.

### Decided so far (user 2026-11-03)

| Topic | Decision |
|---|---|
| Retrieval | Vectorless: tree + FTS5, no embeddings |
| Models | gemma 12B (agent + vision); OCR: MiniCPM-OCR-1.0 first, Unlimited OCR 2 to compare |
| Languages | Documents are English only |
| File types | `.md` on by default (can be turned off); `.txt`, `.pdf` off until enabled — existing vaults too |
| Small / large | By estimated tokens vs this machine's window, not MB |
| Small PDFs | Loaded on open, OCR included, in memory only, gone at app close |
| Large PDFs | **Load** button on the tree row; cached on disk |
| Cache | Expires 7 days (default, per-vault setting) after last use; pinned kept; full deletion |
| First build | Questions about the open PDF only; answers in the chat only |
| Selection / screenshots | Selection in the PDF opens the Ask box; screenshots (inline button or pasted) to the Ask box and the chat |
| Hand fixes | Later |

## 2. Models and machines (to be confirmed by the eval, §9)

| Role | Model | Notes |
|---|---|---|
| Agent, summaries, figure / chart / screenshot reading | gemma 12B (vision) | One model for reasoning and vision, so the only model swap is with OCR |
| OCR (first candidate) | [MiniCPM-OCR-1.0](https://huggingface.co/openbmb/MiniCPM-OCR-1.0) | ~1.3B, Apache-2.0; Ollama / llama.cpp GGUF / vLLM; markdown + HTML tables + LaTeX; Chinese and English only (OK: documents are English). Test whether the bare model via Ollama is as good as with its own SDK (layout step) |
| OCR (challenger) | [Unlimited OCR 2](https://huggingface.co/baidu/Unlimited-OCR-2) | ~3B, MIT, released 2026-10-27; SGLang / vLLM (Ollama only via community quants); reads many pages in one request (cross-page context: split tables) — the unit of work becomes a window of ~10 pages |

- Every model is a **setting** (agent model, OCR model), reached through `Provider`
  (rule #7). No model or backend is fixed in the pipeline.
- **Machines:**
  - this PC — WSL sees 7 GB RAM, 12 cores, no NVIDIA GPU: build and test the pipeline
    with small models and `fake.py`;
  - a PC with 32 GB RAM + 8 GB GPU — quality and speed numbers. gemma 12B does not fully
    fit on 8 GB and cannot stay loaded next to the OCR model → work is ordered **per
    model**, not per page (§6).
- **Parallel AI calls** are a setting: 1 for Ollama by default, more for vLLM / SGLang
  (*provisional*, §13.1).

## 3. File types and visibility

- One setting, **Accepted file types**, with three types: `.md` on by default (the user
  can turn it off), `.txt` and `.pdf` off until turned on in Settings. Applies to existing
  vaults too (`.txt` no longer shows unless turned on). More types later, one at a time.
- An accepted type shows in the folder tree **and** may be read by the AI — one switch
  for both (today's AI `file_types` list in `core/ai/access.py` already defaults to `.md`).
- PDFs become real vault files: shown in the tree, opened in a viewer (pdf.js vendored
  under `static/vendor/`, no CDN), renamed / moved / deleted to `.trash` like notes.
  Today `core/vault.py` and the watcher only know `.md` / `.txt` — that contract changes.

## 4. Small and large PDFs

"Large" = what the model finds hard to read or slow to answer from, measured in
**estimated tokens**, not MB (a 2 MB file can be 500 text pages, a 30 MB scan 20 pages).
A PDF with no text layer is estimated from its page count until it has been OCR'd.

- **Small:** the estimated tokens fit this machine's measured window
  (`core/ai/window.py`). Loaded for the AI **automatically when opened in the viewer**,
  through the same pipeline as a large PDF (OCR of scanned pages included) — just fast
  because it is small. Kept **in memory only**, dropped when the app closes. Its text
  goes to the model whole, like a long note; no tree or agent loop needed.
- **Large:** does not fit. Not loaded by itself: a **Load** button on its row in the
  folder tree loads it for the AI. Its data is cached on disk (§5).
- The limit follows the machine automatically (the 8 GB PC calls more PDFs large).
- **Load = load for the AI**, not open: a large PDF opens and scrolls in the viewer
  without loading. Asking about an unloaded large PDF → the AI says it is not loaded,
  with the Load button.

## 5. The cache (large PDFs)

### 5.1 Where

```
<vault>/.paper-pile/docs/<sha256 of the pdf, first 16 chars>/
  meta.json             format version, page count, printed-page map, state of each stage,
                        models used, last use, pinned
  pages/0001.md         one file per page: text layer or OCR markdown (front matter: source, model)
  tree.json             the tree: structure + summaries, no page text
  figures/0042-1.json   figure / chart description (vision model)
```

- Keyed by **content hash**, not path: rename / move needs nothing, the same PDF twice
  shares one store, hours of work are never lost to a path change.
- `index.db` only maps path → hash and holds the FTS rows; it is rebuilt from these files
  in seconds (rule #2).
- One file per page: the page is the unit that is saved and resumed; writes are atomic.
- Only derived data — no hand fixes yet (§11) — so full deletion on expiry loses nothing
  the user made.

### 5.2 Lifetime

- Expires after a period **the user chooses** (per-vault setting, default **7 days**),
  counted from **last use** (opening the PDF or asking about it), not from creation.
- **Pinned** PDFs are always kept loaded. After unpinning, the last-use clock applies.
- On expiry: **full deletion** — nothing left behind to make the app heavier. The row
  shows the **Load** button again.
- PDF renamed / moved: nothing happens. `index.db` rebuilt: nothing happens.
- PDF deleted to `.trash`: cache kept while the PDF is in `.trash` (restore is instant);
  removed when no PDF with that hash is left in the vault or `.trash`, or on expiry.
- PDF changed (new hash): pages whose content did not change are copied from the old
  store; the old store is then removed.

## 6. Ingestion (loading a PDF)

Runs in a **worker process** (not NiceGUI's loop, not a thread: PDF work holds the GIL)
— *provisional*, §13.1. The app only receives progress events. Database writes in small
batches (never hold `Index._lock` long). Pages rendered one at a time and released.
Small PDFs run the same stages into memory instead of the disk store.

| Stage | What | AI | Usable after it |
|---|---|---|---|
| 1 | Text layer per page (`pypdfium2`), FTS rows, tree from the PDF's bookmarks if any | No | Search and questions on text pages |
| 2 | OCR of pages with no / almost no text: page → image → OCR model → markdown | OCR model | Scanned pages answerable |
| 3 | Tree: bookmarks → printed contents (mapped with the printed-page offset) → OCR headings; then a summary per node, bottom-up | gemma | Navigation |
| 4 | Figure / chart descriptions (printed caption first; vision model when there is none, or when the agent opens the figure) | gemma (vision) | Figures answerable |

- **Per-page state** (pending / done / failed / needs vision) in `meta.json`: a crash,
  restart or close resumes at the next pending page.
- **One bad page never stops the job:** timeout + one retry, then marked failed with the
  reason; at the end "497 pages OK, 3 failed — Retry?".
- **Per model, not per page:** all OCR first (only the OCR model loaded), then all gemma
  work — no model reload on every call on the 8 GB machine.
- **Priority:** a question the user asks goes before background ingestion; Pause / Cancel.
- **Keys decide what is redone:** each result stores the hash of what it was made from
  (page content + model + prompt version), so only what changed is redone. Changing the
  model in Settings reruns nothing by itself: the PDF is marked "made with an older
  model" and Rebuild is offered.
- Every call checks its size against the measured window before sending; anything too
  big is split, never cut silently. OCR on tables with repeated rows can loop — the
  repeat-penalty and loop lessons from v1 apply.
- From extraction the tree needs: headings and levels, printed vs PDF page numbers,
  running headers / footers removed, tables as markdown, contents and index pages read
  correctly.

## 7. Tree format (`tree.json`)

```json
{
  "id": "4.2.1",
  "kind": "section",
  "title": "Torque settings",
  "level": 3,
  "pages": [88, 91],
  "printed": ["72", "75"],
  "source": "bookmarks",
  "summary": "Torque values for …",
  "summary_key": "a91f…",
  "labels": ["Table 4.2"],
  "refs": ["table:4.3", "page:112"],
  "children": []
}
```

- `kind`: section | table | figure | front | appendix | index. Tables and figures are
  children of their section, so "Table 4.2" resolves to a node with pages.
- `source`: bookmarks | toc | headings | model.
- **Stable ids:** the printed section number when there is one, else a path of title
  slugs (`ch4/safety-checks`) — never iteration order, so citations and saved chats
  survive a re-load.
- **Cross-references linked at ingestion:** "see Table 4.2", "Section 9.1", "p. 112"
  (through the printed-page map) are resolved to node ids / pages.
- The agent sees the tree one level at a time (titles + summaries), never the whole
  tree in the prompt.

## 8. Asking about a PDF

### 8.1 Scope of the first build

- Questions are about **the open PDF only**. No vault-wide search ("which PDF has this?")
  yet (§11).
- Answers go to **the chat only**. "Insert into a note" comes later (§11).
- **Selection works in the PDF too:** text selected in the viewer (pdf.js text layer)
  opens the same Ask box popup as a selection in a note, and can be sent to the chat.
- **Screenshots** go to the Ask box popup and to the chat; the vision model reads them.
  Two ways in:
  - a **dedicated screenshot button inline** in the popup (and the chat input): drag a
    region over the PDF page; the crop is taken from the page as the app draws it;
  - an **outside screenshot** (taken with another tool) pasted or dropped into the popup
    or the chat. Capturing the desktop outside the app from inside it is not planned:
    Wayland / WSLg do not allow it without a portal.
- Screenshots need **image support in `Provider`** (`ChatMessage` is text-only today;
  `ollama.py` and `openai_compat.py` gain images). This moves "images sent to vision
  models" from v1's Deferred list into v2.

### 8.2 The agent (per question, large PDFs) — *provisional*, §13.3–13.4

A fixed state machine with a hard step cap (about 6–10 steps and a page budget):
**plan → read → verify → answer**. Written in `core/ai/` for now; LangGraph is still open
(§13.2).

Tools:
- `open(node)` — the node's children with their summaries.
- `read(pages)` — page text sized to the window; includes the end of the page before and
  the start of the page after (paragraphs and tables split at page breaks); lists the
  node's resolved cross-references.
- `find(words)` — FTS5 keyword search; a search with no hits retries with any of the
  words (as `index.py` does for notes); returns page + node.
- `look(page | figure)` — the page image or crop to the vision model; used when the
  question is about numbers / specs in a table or about a figure, not on every hit.
- `answer(text, pages)` — ends the loop; citations required.

Every step is a **JSON decision whose ids are an `enum` of ids that exist** (as
`core/ai/plan.py` does), so a small model cannot invent a section. Only the final answer
is long text.

## 9. Eval (`tools/ai_eval/`) — first sketch, §13.5

- **OCR:** 20–30 hard pages from the user's own documents (scanned page, dense table,
  table split over two pages, math, two columns, chart page) with hand-checked text.
  Score per model: text accuracy, tables right, pages per second on the 8 GB PC, failure
  / loop rate.
- **Agent:** 2–3 real documents (a manual, a report, a scanned book), ~30 questions with
  known answer pages. Score: right page read, answer right, steps, seconds per question.
  A held-out set, as for the intent eval.

## 10. Open questions

None on the decided parts. The larger areas still open are in §13.

## 11. Later (not in v2's first build)

- Questions across all PDFs in the vault ("which PDF contains this?"): a step above the
  trees that picks the document.
- Answers inserted into a note, with links to the cited pages.
- Hand fixes: rename a heading, fix a level or the printed-page offset, correct a page's
  OCR text; only the changed node and the nodes above it re-summarised. When they come,
  decide how they survive expiry (rule #4: user data is never hard-deleted).

## 12. Rough cost (estimates, to be measured)

8 GB PC, 500-page scanned book: OCR ~10–30 min; summaries + figure descriptions with a
GPU/CPU-split gemma 12B ~1–3 h (background, resumable). A question: ~3–8 model calls,
~1–2 min.

## 13. Areas to discuss later (before tasks are written)

Planning sessions still to come (user 2026-11-03). Each ends with decisions written into
the sections above and a Decision log entry in `docs/TRACKER.md`.

### 13.1 Threads, processes and concurrency — where yes, where not
- Today: one NiceGUI event loop; AI calls are async `httpx` and already do not block it;
  heavy sync work on the loop is what freezes the UI (CLAUDE.md gotcha on `Index._lock`).
- To decide: what goes to a process pool (PDF parsing, page rendering), a thread
  (file I/O, SQLite writes), or stays async (AI calls); one shared job runner for
  ingestion, priority between a question and background work, cancel / pause; how many
  parallel AI calls per backend; memory limits for in-memory small PDFs (how many at once).
- Where **not** to add threads (the UI path, anything touching NiceGUI elements, the
  editor), and how to measure (`tools/perf_ui.py --loop-debug`).

### 13.2 LangGraph — adopt or not
- Earlier view: it would bring visible flow + checkpoint / interrupt, at the cost of
  `langchain-core`, slower imports on WSL, and pressure toward its model clients (rule #7:
  plain `httpx`, no backend library). Option: LangGraph as orchestrator only, nodes
  calling our `Provider`.
- To decide: whole harness, only the RAG agent, or none; how its checkpoints fit rule #2
  (cache vs source of truth); test and eval impact.

### 13.3 How agent loops are redefined
- The current AI harness is a fixed pipeline, not a free loop: understand → plan → edit
  → guards → placement (`understand.py`, `plan.py`, `edit_run.py`, `guards.py`).
- To decide: one shared loop framework (state, step cap, resume, JSON decisions with
  `enum` ids) used by both the edit pipeline and the RAG agent, or separate code; what
  "step", "tool" and "state" mean in this codebase.

### 13.4 RAG agent loop vs current agent loop
- How the PDF agent (§8.2) relates to the existing Ask box / chat flow: who routes a
  question to it (the request-understanding step in `understand.py`?), how its steps and
  citations show in the chat, how Stop / retry / options work, how screenshots and
  selections enter it, and how the small-PDF path (whole text, no loop) is chosen.

### 13.5 Eval planning at large scale
- Beyond §9: size and kinds of document sets, how answers are judged (exact, by page, by
  a judge model), held-out sets per version, timing per machine (this PC vs the 8 GB PC),
  OCR and agent scored separately and end to end, and running it repeatably (scripts,
  stored results, comparison between models and prompt versions).

### 13.6 Also worth a session
- **Prompt injection from PDFs:** v1's risk table relies on "no tools or agents (the
  model can only answer)". A tool-using agent reading untrusted PDF text changes that
  risk; tools must stay read-only and the answer must never act.
- **`--serve` mode:** the PDF viewer, Load progress and screenshots must work in the
  browser too (rule #8).
- **PDF viewer UX:** tree row (Load button, progress, pinned, "older model"), viewer
  layout next to the editor, citation links that open the PDF at a page.
- **`Provider` image API:** message shape for images, size limits, which backends and
  models accept images, what the UI does with a text-only model.
