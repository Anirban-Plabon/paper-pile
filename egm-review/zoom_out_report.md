# Stage 5 — Initial Zoom Out Review

Target: `docs/PLAN.md` (full file, lines 1–936). Context: `docs/TRACKER.md`, `CLAUDE.md`. Focus: AI work.
Reviewer: egm-zoom-out (zoom-out-standard). Status: completed.

The reviewer read the persona, the standard, all of PLAN.md, CLAUDE.md and TRACKER.md (Current focus, Open issues, AI rows and decisions). Where the plan names code, it checked that code in `paper_pile/core/ai/` (15 modules) and `paper_pile/gui/components/chat.py`.

**Verdict:** the objective is clear, so context sufficiency passes. The AI scope is mostly well built: one engine, a permission gate, access scope, and context and caching rules. The gaps are of three kinds:

- The AI spec is spread over several sections that disagree with each other.
- The retrieval / embeddings story has no decision.
- Failure modes, local-hardware behaviour, and how a real local model's output becomes an edit are not specified.

On the YAGNI side, there are too many AI entry points and settings.

## 🔴 Blockers

**B1. Retrieval / semantic search has no decision. The plan says four different things.**
L303 (`embed(texts)` in the Provider protocol), L322 ("Vault-wide RAG… not phase 1"), L341 ("embed model (future)"), L465 ("How the AI reads the vault is out of scope"), L541 ("Not now: … embeddings / vector search"), L592 ("Advanced (with the unused embedding model)"), L920 (§7 "Vault RAG with sqlite-vec"). TRACKER L16 also lists "the user's AI-with-notes plan" as next.

The problem:

- `Provider.embed` is implemented in ollama.py, fake.py and factory.py, and the embed-model setting ships. Neither has a consumer.
- L465 says vault reading is out of scope, but §4.26 then specifies an access scope and `@vault` search.
- A reader cannot tell whether `@vault` FTS is the retrieval design or a stopgap.

Make one decision, then do one of these:

- (a) Declare FTS `@vault` the phase-1 retrieval. Remove `embed()` from the protocol, remove the embed-model setting, and delete L465.
- (b) Write a real embeddings section. It needs to cover:
  - chunking by heading/section (`core/sections.py` exists)
  - where vectors live (a rebuildable table in `index.db`, or `sqlite-vec` as a pinned dependency)
  - incremental re-embedding on save and watcher events, off the UI loop
  - invalidating everything when the embed model changes (store the model name and dimension in `meta`)
  - filtering every hit through `AccessPolicy.may_send`
  - the cost of a first full-vault embed on local hardware (progress, pause)
  - hybrid ranking with FTS

## 🟡 Majors

**M1. The AI spec is split across sections and contradicts itself; §4.11 is partly superseded but not marked.**

- L307–312: the context order and the "default 6000 tokens, chars/4" rule are superseded by L537 (window-derived budget) and by L538 (the new prompt layout).
- L303: the protocol lacks `context_length()`. It also omits `GenerationOptions`, which L320 mentions.
- L305: says "startup health check". The code polls every 30 s and has a Retry button.
- §3 (L80–83): lists 3 files under `core/ai/`. There are 15.
- §4.26 sits before §4.25…§4.20.

Fold §4.11 and §4.26 into one AI section, with "superseded by" notes and an updated §3 tree.

**M2. The plan contradicts its own invariant, "the AI never writes into a note".**
L529 says this, but in the same paragraph insert-at-caret commands (Continue writing, Summarize, Explain) keep streaming into the note under *Ask first*.

Not specified:

- what happens when the user types, switches tab, closes the note, or the file changes on disk during a stream
- whether a stopped or failed stream leaves partial text, and whether that is still one undo step
- whether a version-history snapshot is taken before streaming

Either state the exception ("insertions stream; replacements are proposals"), or route inserts through a proposal too.

**M3. Failure modes of a local model are underspecified.**
Only "Ollama isn't running" is covered. Missing:

- Ollama dying mid-stream: is the partial answer kept, saved, or marked as failed?
- The model not pulled: the code has a `ollama pull` hint, the spec does not.
- The configured model deleted, or no model on first run.
- The 300 s timeout on CPU-only machines.
- A failed compaction call.
- An empty or garbage edit proposal.

Add an "AI failure modes" table (event → what the user sees → what is persisted). Add a real-model QA line too: all P22 acceptance was verified with FakeProvider, and TRACKER L9 still waits on a real-model pass.

**M4. How real model output becomes an edit is unspecified.**
L529–530 and L534. Small local models add preambles, code fences, quotes and `<think>` tags, and they rewrite unrelated lines. L530 handles only "a reply that is one code block".

Specify:

- the edit-prompt contract (return only the replacement text)
- post-processing (strip one fence or preamble, drop reasoning)
- what to do when the reply's size is implausible
- fixtures captured from real models, like the Smart Paste fixtures in L300

**M5. Token estimation (chars ÷ 4) is unsafe for non-Latin text.**
L307 and L537. The app supports Bangla, and Bengali text takes far more tokens per character than ¼. Ollama silently cuts the start of an over-long prompt (L537), and the start is the system prompt and the summary.

Fix: calibrate per model from `prompt_eval_count`, or apply a safety factor for non-ASCII text. Add a test with a Bengali note against a small window.

**M6. Local-hardware behaviour is unspecified.**

- **Cold start**: add a "Loading model…" state, using `load_duration` or `/api/ps`.
- **`num_ctx` stability**: a request with a different `num_ctx` reloads the model. Chat, commands, compaction and Write with AI must send the same `num_ctx` and `keep_alive` per model.
- **Concurrency**: allow one active generation at a time (or a queue), and make Stop abort the HTTP stream.
- **Thinking models**: say whether `think` is off for edits and compaction, and whether reasoning counts toward the budget and saved history.
- **Memory**: say whether "AI off" or closing the app unloads the model (`keep_alive: 0`).

**M7. Privacy holes in the access model.**

- **Remote host**: `ai.host` is free-form, so note text can leave the machine in plaintext. Warn on a non-loopback host, or record the host in the grant.
- **Copies in saved chats**: saved chats in `<vault>/.memory/` can copy outside-folder text and `ai: false` attachments into the vault. Specify what a chat file stores.
- **Revoking**: say whether revoking a grant purges that content from saved chats and from re-sent `SavedTurn.notes`.
- **Prompt injection**: *Apply at once* plus `@vault` or outside text can steer an edit that nobody reviews. One line in §8 Risks is enough.

**M8. File types don't fit the vault model.**
`ai.file_types` (L531, e.g. `.py`) vs L155: the vault only knows `.md`/`.txt`. A vault `.py` file cannot be listed, @-mentioned or found. Either restrict the setting inside the vault, or specify the read path and its size cap.

**M9. Too many AI entry points, and the same names do different things.**
"Summarize", "Rewrite" and "Explain" exist as slash commands (which stream into the note) and as menu, palette and chip actions (which send to chat). There are also many more triggers. Define one verb table (action → where output goes → which edit mode applies) and trim the duplicates.

**M10. AI settings sprawl.**

- `ai.context_budget` is now only a cap, and its 6000 default is stale.
- The embedding-model row is unused.
- `ai.history_turns` overlaps the token-based history.

Drop these settings or explain when a user would change them.

## 🟢 Nits

- **N1 (L538–539)**: sticky notes re-sent after the new message break prefix caching. Keep them attached to their original turn.
- **N2 (L539)**: the compaction summary has no hard cap, and summary-of-summary can drift. Also state which model and options it uses.
- **N3**: first-run behaviour with no model is unspecified, and the picker lists embedding-only models.
- **N4**: the status dot needs a "model missing / loading" state.
- **N5**: say that images are never sent to the model, or plan vision support.
- **N6**: the shortcut table lacks Ctrl+J, Alt+/ and `/compact`.
- **N7**: the QA checklist needs AI lines: a real-model pass, a long chat in a small window, a non-Latin note, grant ask and revoke, and zero requests when AI is off.
- **N8**: the P22 "Implemented" paragraphs list internal function names. Move them to TRACKER.

## Missing AI features to decide on

- Retrieval: FTS only, or embeddings (B1)
- An output-cleaning contract for edits (M4)
- A model-loading state, one generation at a time, and a Stop that really stops (M6)
- Persistence privacy rules (M7)
- Token calibration (M5)
- Explicitly out, and right to keep out: agents, web access, cross-chat memory, cloud providers
