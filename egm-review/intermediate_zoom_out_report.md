# Stage 8 — Intermediate Zoom Out

Target: `docs/PLAN.md`, full file. The document is unchanged since Stages 5–7. Reviewer: egm-zoom-out. Status: completed.

The main context checked Z-1 in the code: nothing in `paper_pile/` reads `done_reason` or sends `num_predict`. In `core/ai/engine.py:691` the selection (`given`) is added to the prompt without being counted against the budget.

**Verdict:** context sufficiency passes. Together, the earlier reports would add about 40 changes, and at least a third of them are YAGNI for a single-user local app. The AI design is sound: one engine, a consent gate, edits as diffs, FTS instead of vectors. It needs contract fixes at the edges, not new subsystems.

**Answer to the author's question:** no big features are missing. What is missing are rules for:

- cut-off replies
- oversize selections and notes
- exfiltration through the chat
- non-Latin token counts

The one feature gap that matters is `@vault` sending whole notes into a budget that holds about one (Z-2).

## Part 1 — Earlier proposals to drop or simplify (YAGNI)

- **🟡 Y1. Don't write an embeddings section.**
  - Declare FTS `@vault` the phase-1 retrieval.
  - Remove `embed()` (L303) and the embed-model setting (L341, L592).
  - Delete the L465 sentence.
  - Keep §7's Vault RAG line as the only deferral.
- **🟡 Y2. Drop per-model token calibration.** Instead: non-ASCII characters count 1 token each, ASCII chars ÷ 4. One line plus a Bengali test.
- **🟢 Y3. Cut M6 (local hardware) to two rules:**
  - every call sends the same `num_ctx` and `keep_alive` per model;
  - one generation at a time, and Stop closes the HTTP stream.

  Drop the `/api/ps` loading state and unloading the model when AI is turned off.
- **🟢 Y4. Drop:**
  - purging saved chats when a grant is revoked
  - storing the host in each grant
  - a stronger *Apply at once* warning
  - undo on unopened notes (instead, say Apply at once works on the open note only)
  - `ai: false` for `.txt` files
  - the pasted-log path worry
- **🟢 Y5. Drop:**
  - a context preview before sending
  - the model saved per chat or per turn
  - retry/backoff when Ollama returns (the 30 s poll and Retry exist)
  - throttled streaming re-render, until it is measured
- **🟢 Y6. Keep only two decision records:** FTS vs embeddings, and the 8k cap.
- **🟢 Y7. Don't restructure.** Replace the stale AI lines (L307–312, L315, L320, L321, L323, L465, L526) with "see §4.26" and update the §3 `core/ai/` tree. Renumbering can wait.
- **🟢 Y8. One line each:**
  - **Proposals** are in memory only. They are dropped on close, reload or restart, and a new one replaces the old one in the same note.
  - **Outside grants**: refuse `/` and `~` themselves, skip hidden files and folders, and walk off the UI loop.

## Part 2 — Remaining gaps, in priority order

| # | Sev | Gap | Smallest fix |
|---|---|---|---|
| P1 | 🔴 | Remote images in chat replies leak notes (verified) | Apply the L209 rule to chat output and add CSP `img-src 'self' data: blob:`. Two sentences in §4.26 and one §8 row |
| P2 | 🔴 | `vault.toml` can redirect or widen the AI (verified) | Make `ai.host`, `ai.instructions_file`, `ai.prompts_file`, `ai.chats_folder` and `ai.edits` global-only. Warn once when the host is not loopback |
| P3 | 🔴 | A cut-off reply becomes a destructive edit | Z-1 below |
| P4 | 🟡 | "The AI never writes into a note" is false (L529) | State the exception (see below). Align the mode names in L812 |
| P5 | 🟡 | Prompt assembly is defined in several places | L537–538 is the only definition. Answer: is the note implicit; live buffer vs disk; earlier notes stay in their turn. Mark L307–312 as superseded |
| P6 | 🟡 | Non-Latin undercount | Y2's rule |
| P7 | 🟡 | No failure behaviour | A five-row table (below). Fix compaction's `transcript[-limit*4:]`, which drops the old summary |
| P8 | 🟡 | No AI formats in §5 | Field lists for the chat JSON and `ai_access.json`; `ai_access.json` wins for `file_types` and `exclude` |
| P9 | 🟢 | No AI QA lines | Real-model pass, Bengali note in 8k, zero requests without `--ai`, grant and revoke |
| P10 | 🟢 | Auto chips from `ai: false` notes | No automatic chip from a refused note |

The P4 exception, as rules:

- Insert-at-caret commands stream into the note and are one undo step. A version is kept before the stream (L502).
- Typing in that note, switching tabs or pressing Stop ends the stream and keeps what arrived.
- Replace-type edits are always proposals.
- *Read-only* refuses both kinds.

The P7 failure table:

| Event | What happens |
|---|---|
| Ollama down | banner, with text that depends on the host |
| Model missing | `ollama pull` hint |
| Mid-stream error | the partial reply is kept and marked "stopped" |
| Compaction fails | trim, with no retry until N new turns |
| Access denied | a notice; the message stays in the box |

Size of the change: about eight paragraph edits in §4.26, three rows in §8 and two schemas in §5. No new modules.

## Part 3 — What every earlier reviewer missed

**🔴 Z-1. A cut-off reply is treated as a complete edit (L529–530, L537; `engine.py:674–709`, `commands_builtin.py:380–396`). Verified.**
Fix grammar and the selection *Edit* send the whole selection without a size check, and turn the reply into a proposal that replaces the whole selection. No `num_predict` is sent, and `done_reason` is never read.

With a large selection, the reply stops early, or Ollama cuts the start of the prompt (the "only the corrected text" rule goes first). The proposal then shows the tail of the user's text as deleted:

- One *Accept all* removes it.
- Under *Apply at once*, it is removed without review.

Stop during Fix grammar has the same problem.

Three rules fix it:

1. A replace edit runs only when 2 × selection tokens + the prompt fit the window. Otherwise show "Selection too long for this model; select less."
2. A reply that did not end with `done_reason == "stop"` (length, Stop, error) never becomes a proposal or an applied edit.
3. A replace edit falls back to *Ask first* when the reply is shorter than half the original.

**🟡 Z-2. `@vault` sends whole notes into a budget that holds about one (L535, L537, L540).**
The notes share is 60 % × (8192 − 2048) ≈ 3.7k tokens, about 15 KB of English and much less in Bengali. Hits 2–3 are cut or left out, and hit 1 is cut from its end, which often removes the matching passage.
Fix: send the matching section of each hit (`core/sections.py` already splits notes), capped at about ⅓ of the notes share each. This is the real "ask my vault" gap, and it needs no embeddings.

**🟡 Z-3. The user isn't told which note was cut (L537).**
The context line says "(some cut)" in small muted text. So Summarize on a long note summarizes only its start and looks complete.
Fix: name what was cut, e.g. "Context: note (first 40 %) · 3.6k / 8k".

**🟢 Z-4.** The cache prefix also changes when `ai.instructions_file` is edited (it is re-read each message) and when compaction runs. Say the prefix is stable "until the instruction file or the summary changes".

**🟢 Z-5.** The 8k automatic cap has no recorded reason, although current models allow 32k–128k. Record the RAM/VRAM reason, and that `ai.num_ctx` raises the cap. Z-2 and Z-3 follow from it.

## Priority list

1. Z-1, P1, P2: data safety and privacy.
2. P4 (write contract), P5 (one prompt-assembly definition).
3. Z-2 (section-level `@vault`), Z-3 (name what was cut): the only feature-level changes worth making now.
4. P6, P7, P8.
5. Y1 (drop `embed()` and the embed-model setting), and the Y7 stale-line pass.
