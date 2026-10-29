# Stage 9 — Implementation Readiness Test

Target: `docs/PLAN.md` DetailedRange 615..936 (§6 Phases & tasks, §7, §8). Context: TRACKER, CLAUDE.md, code and tests.

Reviewers (all completed):

- egm-implementation-readiness (implementation-readiness-standard)
- egm-codebase-details (implementation-readiness-standard)
- egm-style

Tags: **R** = readiness, **C** = codebase details, **W** = style.

**Key context:** no AI task is open. Every P7 and P22 row is ✅ in TRACKER. The only AI work left is the real-model pass (TRACKER L9). So the findings fall into three groups:

- acceptance criteria too loose to show the shipped behaviour is right
- requirements of done tasks that the code does not meet
- AI tasks, QA lines and risks that don't exist

The main context checked these claims in the code:

- C-1 / R-M3: `keep_version(..., "before AI")` is called only in `_run_stream` (`editor_pane.py:1314`); `propose_edit` and `propose_in_note` (1386, 1410) never call it.
- C-14: `revoke` (`access.py:113`) deletes the whole record, and `grant_now` writes a new record with an empty `exclude`.
- C-17: `/compact` (`chat.py:899`) runs before the access check in `send`.

## 🔴 Blockers: PLAN text that P7/P22 point to contradicts the code (C-5 … C-10)

| # | PLAN says | Code says |
|---|---|---|
| C-5 | L531: settings keys `ai.file_types` / `ai.exclude`; vault `.py` files are readable | Neither key exists; they are `Grant` fields in `ai_access.json` (`access.py:46-50`). The vault only yields `.md`/`.txt` (`vault.py:28`), so other types apply only to outside paths |
| C-6 | L529: `EditProposal` with the original text's hash | `Proposal(id, path, start, old, hunks)` (`proposals.py:28`) stores the full old text; `locate` re-finds it |
| C-7 | L303: `chat(messages, stream) -> AsyncIterator[str]` | `chat(messages, *, model, options) -> AsyncIterator[str \| Reasoning]`, plus `context_length()` and `host` |
| C-8 | L315/L319: chats in `.paper-pile/chats` | The default is `<vault>/.memory` (`chats.py:28`) |
| C-9 | L320: `num_ctx` 0 = the model's default | 0 = automatic (≤ 8k), always sent. The `factory.py:77` docstring is also stale |
| C-10 | L542: per-turn `context` field | Not in `SavedTurn` (`chats.py:45-54`) |

## 🟡 Majors

### Requirements of done tasks that the code does not meet

- **C-1 / R-M3. Chat *Apply to note* and *Apply at once* save no "before AI" version (P22.7 L811, spec L529). Verified.**
  Fix: call `keep_version` inside `propose_edit`, which covers every path. Add it to the acceptance and test it.
- **C-2. Rewrite does not go through the diff (L529).**
  The ⋯ Rewrite sends a chat message with a note link, and `edit_from_reply` needs exactly one selection quote. There is no Rewrite slash command.
  Decide the region (the whole body via `parser.body_start`) and the entry point.
- **C-3. P22.6's acceptance (L810) overstates the protection.**
  Automatic selection chips from `ai: false` or excluded notes are sent (`chat.py:775-783`, `engine.py:443`). This was a deliberate decision (TRACKER L472), but PLAN was never updated.
  Decide whether an automatic chip counts as "picked".
- **C-4 / R-M4. P22.2's claim "one engine; the UI only draws" is partly false.**
  The GUI still owns:
  - the edit-mode policy (`editor_pane.py:1366-1493`, `chat.py:461`)
  - the Read-only refusal (`editor_pane.py:1302`)
  - the note-menu prompt texts (`note_actions.py:33-37`)

  P22.8 has only "1 settings test", and a TUI would have to re-implement this.
  Fix: move the decision into core, e.g. `AiEngine.edit_action(mode, kind) -> propose | apply | show_only | refuse`, and unit-test every cell of the mode × entry-point matrix (streaming commands, Fix grammar, selection Edit, chat Apply/Insert).

### Undecided rules

- **R-M2. A chat preamble can land in the note.**
  `edit_from_reply` (`engine.py:626`) uses the whole reply unless it is exactly one code block. Real models say "Sure, here's…". Under *Apply at once* that goes into the note.
  Pick one rule:
  - the prompt asks for bare text or one fenced block
  - preamble and closing lines are stripped
  - Apply is offered only for a single block

  Add tests with a preamble reply.
- **R-M7 / C-16. Compaction failure.**
  "Falls back to trimming" (L539) is untested, and `FakeProvider` cannot fail. On a provider error, `/compact` shows "Nothing to summarize yet" (`chat.py:1034`). Undecided:
  - Does Stop cancel the compaction call?
  - Is a "Summarizing…" state shown?
- **R-M8. Behaviours with no spec and no task:**
  1. Provider failure mid-stream: the half-written text stays in the note. Keep it, remove it, or roll back to "before AI"?
  2. Two AI operations at once (chat plus a command, or both split sides): allow, queue or refuse?
  3. No model or a missing model: the code has messages (`ollama.py:144,156`, `chat.py:257`), the spec does not.
  4. `--serve` plus outside grants: a token-holding browser session can make the server read local paths. Confirm or restrict.
  5. Token accuracy: "never exceeds" (P22.3) is proven only against the estimate. Compare with `prompt_eval_count` on CJK, Bengali and code.

### Missing verification

- **R-M1 / W-12 / C-15. No real-model task or AI QA lines.**
  Every P22 row was checked with the fake AI. Add **P22.13 Real-model pass** with named models: a small instruct model, a thinking model, and one with a window under 8k. Give a pass/fail line for each of:
  - `show` returns a context length
  - `num_ctx` is honoured
  - `message.thinking` reaches the folded Reasoning (`ollama.chat` never passes `think=`, C-17)
  - compaction stays ≤ 200 words
  - Fix grammar and Edit return bare text
  - Stop cancels a real stream

  Add QA lines to L905–915:
  - without `--ai`: no AI anywhere
  - first use asks for access
  - diff → Accept → one Ctrl+Z
  - Read-only refuses writes
  - a long chat compacts
  - the context line matches the window
  - `@vault` never returns excluded notes
  - `/compact`
  - the outside-path prompt

  Replace "clear banner" (L911) with the banner text.
- **C-16. Test infrastructure is undocumented.** `FakeProvider` behaviour (echo after `DIVIDER`, `calls`, `up`, `max_context`, `thinking`), `PAPER_PILE_FAKE_AI_REPLY` / `_THINKING`, and the autouse XDG/env fixtures in `tests/conftest.py`.

### Stale or untestable task rows

- **W-1 / C-12. The P7 table (L696–702)** lacks P7.5–P7.7, which are done (TRACKER L96–98). P7.3 and P7.4 are superseded by P22.3 and P22.7. Mark them, and point P7.3 at §4.26.
- **W-2.** P7.2 says "manual QA" with no list, and P7.4 says "works". Neither is pass/fail.
- **W-3.** P14.1 (L726) assumes the AI switch always works. Note that it only works with `--ai` (P22.1).
- **W-4 / R-N4.** P22.1 (L805): "with the hint" should quote the two messages. Cover `PAPER_PILE_NO_AI` and `PAPER_PILE_FAKE_AI`.
- **W-5.** P22.6 (L810):
  - "outside paths never reach the model" should be "ungranted outside paths".
  - The title still says grants are made in Settings; since 2026-10-29 they are made in the chat.
  - "rows look like the existing ones" is subjective.
  - Untested: `ai: false`, `fnmatch` excludes, the 2000-file / 200 KB caps, a moved vault asking again, the "AI can read: …" line.
- **W-6 / C-17.** P22.8 (L812):
  - The mode names should match the spec (*Ask first / Apply at once / Read-only*).
  - "in open note" is false, because `propose_in_note` opens the note first.
  - Give the expected result per mode.
- **W-7.** P22.9 (L813): "keeps today's chips" will go stale. "Once" is ambiguous. Untested: the *Not now* path, the same text twice making one chip, Esc.
- **W-8 / R-N5.** P22.11 (L815): "each works" → ↻ replaces only the last answer (the file holds one), ✎ restores the message and its chips, sources open the note, reasoning is folded and not saved in `text`.
- **W-9.** P22.5 (L809): state the base for 60 %, the last 4 messages kept, ≤ 200 words, the trimming fallback, and the marker and "nothing to fold" text.
- **W-10.** P22.7 (L811) lacks: the before-AI version, chat *Apply to note*, a visible "out of date" mark, and the split view with the same note on both sides (CLAUDE.md gotchas).
- **W-11 / R-N7.** The 🧠 table lists only P0–P4. P22.2 and P22.7 are marked but have no reason. P22.6 (data exposure) arguably qualifies.

### Plan sections

- **W-13 / R-N3 / C-13. §7 is stale.**
  - Built since: split panes, daily notes/templates, tags.
  - Missing: the §4.26 "Not now" list, the "install without `ollama`" item, the unused `Provider.embed` / `ai.embed_model`.
- **W-14 / R-M6 / C-14. §8 has one AI risk, and its mitigation is stale.** Missing:
  - prompt injection (worse under *Apply at once*)
  - a remote `ai.host`
  - Ollama's silent truncation
  - auto-applied edits
  - outside grants in `--serve`
  - Ollama API drift (`show` keys, `thinking`, `num_ctx`)
  - VRAM pressure from a manual `num_ctx`
  - chars ÷ 4 on CJK and code
  - **a revoke followed by re-Allow wiping "Never read" exclusions (verified)**
  - an unbounded `NoteCache._texts`
- **C-11.** Undocumented AI surface:
  - the §3 tree
  - `--ai` and `--debug` in the §4.1 CLI
  - §5 chat JSON and `ai_access.json`
  - the settings Context group and Access panel
  - the L465 "out of scope" sentence
  - the fake-AI env variables

## 🟢 Nits

- **W-15**: chip count, ≤ 6 vs 3–4; "shown only while empty" is untested.
- **W-16 / R-N6**: `@vault` "top hits" vs "3 best". Also: ranking basis, zero hits, the index still syncing.
- **W-17**: P22.4 "quote" is undefined, and cache invalidation is untested.
- **W-18**: P22.3 acceptance lacks the ¼ reserve (≥ 512), the 60 % notes share and the 8k cap.
- **W-19**: P22.2 "work as before" names no baseline.
- **W-20 / R-N1 / R-N2 / C-17**: P22 sits before P21, and P22's order is only in TRACKER.
- **W-21**: "(real app)" is never defined; define it once in §6.
- **C-17**: an `ai: false` `@vault` hit takes one of the 3 slots and is then dropped (`engine.py:463` filters by `may_read` only).
- **C-17**: `/compact` skips `confirm_access`, so it still sends the transcript after a revoke (verified).

## Reuse for future AI work (C-18)

- `parser.front_matter` instead of `yaml.safe_load` in `access.says_private`.
- `parser.body_start` to strip front matter from context (saves tokens; also the whole-note Rewrite region).
- `parser.headings` / `section_at` / `sections.section_heads` to cut at section boundaries instead of `context._cut`. This also fits section-level `@vault` (Stage 8, Z-2).
- The index `links` table instead of re-parsing links in `context._outgoing`.
- `NoteCache` and `AiEngine.read_note` / `readable_paths` for every AI read; never `Vault.walk_notes`.
- `Index.search(..., any_words=True)` for search features.
