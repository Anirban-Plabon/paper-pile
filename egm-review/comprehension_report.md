# Stage 6 — Comprehension Test

Target: `docs/PLAN.md`. FeatureRange: 1..614, DetailedRange: 615..936. No extra context; the reviewer read only the target. Reviewer: egm-comprehension. Status: completed.

## What this proposes

paper-pile is a local, file-based markdown note app: a 3-pane NiceGUI/CodeMirror window, plain `.md`/`.txt` files, a slash menu, Smart Paste, and Mermaid and KaTeX rendering. AI comes from a local Ollama server. It is only available when the app is started with `--ai`, and the `features.ai` switch can then turn it on or off live. All AI logic sits behind one `AiEngine` in `core/ai/`. On the first AI use in a vault, the user grants read access to that vault. That grant, plus paths the user allows outside the vault, is stored in `~/.config/paper-pile/ai_access.json`. The chat and the AI slash commands build a prompt in a cache-friendly order: a fixed system prompt, then earlier turns, then the newest message with its notes in front. The engine streams the reply back. Changes the AI wants to make to a note are shown as an inline red/green diff that the user accepts or rejects (`ai.edits`: Ask first / Apply at once / Read-only). Supporting features: context-window sizing, compaction into a "Summary so far", suggested prompts, `@vault` search, regenerate/edit-last, sources and reasoning display, and saved chats ("Memories").

## How the existing system works, per this document

P7 delivered a `Provider` protocol (`chat/embed/models/health`) with an `OllamaProvider`, a chat pane (streaming, Stop, Insert into note, Copy), a context builder with a 6000-token default budget and a fixed order (selection → current note → `@mentions` → open tabs → linked notes), and AI slash commands that stream text in at the caret (`StreamInsert`). P22.1, P22.2, P22.6, P22.7 and P22.9–P22.12 are marked implemented. They put the engine in core, add the `--ai` start flag, the access policy, edit proposals, the selection bar and the chat extras. P22.3–P22.5 and P22.8 (context sizing, caching, compaction, edit permission) are described in §4.26 but not marked implemented. Chats are saved per vault as JSON. A status-bar dot and a banner show whether Ollama is reachable.

The reviewer could not settle one point from the document: whether the open note (and open tabs) are sent with every chat message by default (see finding 1).

## Findings

**1. 🔴 Blocker: what is sent to the model automatically is unclear (L306–312, L533, L537–538).**
The P7 fill order (selection → current note → @mentions → open tabs → linked notes) conflicts with the chip composer ("a check on the current one") and with L533, where the engine reads "the open note and the open tabs". The new 60 % budget then replaces the 6000-token rule.

Open questions:

- Is the current note sent with every chat message, even without a chip?
- Are linked notes still added?
- Which source is cut first when the budget is exceeded, and how? "Truncated" is never defined.

Fix: add one authoritative "Prompt assembly" subsection, with an example payload, and mark the P7 list as superseded.

**2. 🟡 Major: earlier notes are described two ways (L538).**
L538 says earlier notes stay inline in their original turn (a stable prefix), and also that they are re-sent after the new message's notes. Both cannot be true without sending the notes twice. The caching effect after compaction or trimming is also not said.

**3. 🟡 Major: "The AI never writes into a note" has unexplained exceptions (L321, L323, L529).**
Continue writing, Summarize and Explain stream directly into the note, even in *Ask first* mode. This needs saying plainly, with the reason.

Also unspecified:

- what happens if the user types during the stream
- what Stop leaves behind
- whether chat's *Insert into note* goes through the diff in Ask first mode

**4. 🟡 Major: stale and contradictory statements.**

- L323: Fix grammar "replaces the selection". L530: it "shows a proposal".
- L465: vault reading is "out of scope". §4.26 specifies it.
- L526: "AI is a separate install". L527 reverses this.
- L251: `CommandContext` holds "ai provider", but commands now go through `AiEngine`.
- L812: the mode names "Ask / Auto-accept in open note / Read-only" differ from the spec, and "in open note" suggests an undescribed scope.
- L465 vs L527: what the `features.ai` default means without `--ai` is unclear.

**5. 🟡 Major: outside-path content has no rule against the context budget (L531, L533).**
The caps (2000 files, 200 KB) are not reconciled with the 60 % rule; an 8k window leaves about 15 KB. Which files win, and does the user see what was dropped? Path detection ("names a full path") is vague: what about code spans, several paths, or paths with spaces?

**6. 🟡 Major: saved text or live text?**
Does the AI read the open note from disk (NoteCache) or from the live editor buffer? With 1 s autosave they can differ. This changes both the answer and whether a proposal is immediately out of date.

**7. 🟡 Major: §5 has no AI data formats.**
§5 is missing:

- the chat JSON (`SavedTurn` fields, `summary`, `summarized`)
- `ai_access.json`
- the `ai.*` settings keys and defaults
- `history.db`

Chats contain note text, so this is also a privacy gap.

**8. 🟡 Major: no AI risks in §8.**
Missing:

- prompt injection from vault, outside or uploaded files
- a remote `ai.host` sending notes off the machine
- a model ignoring the edit format, so `locate` fails
- compaction losing facts
- an 8k cap too small for real notes

**9. 🟡 Major: no AI failure paths.**
The user-visible behaviour is unspecified for:

- Ollama going down mid-stream
- a missing or not-pulled model, or no models at all
- a timeout
- `AccessDeniedError` in chat

**10. 🟡 Major: undefined terms.**

- `GenerationOptions`, `SavedTurn`, `FakeProvider` / factory
- the "block" attachment and "block button"
- "Select from screen", "the notice"
- "Writing language": what language, and where does it come from?
- how an `@note` appears in the sent text
- "Memories" vs "no long-term memory" (L541): say that saved chats are never sent unless reopened

**11. 🟡 Major: features that look missing.**

- A context preview before sending (the summary line was removed)
- A model saved per chat
- `think` on/off, and whether reasoning counts against the window
- Partial results on Stop
- Retry or backoff when Ollama comes back
- What each AI command sends (e.g. Continue writing: the text before the caret, the whole note, or the selection?)
- A remote-host warning

## 🟢 Nits

- **12**: compaction mixes "messages" and "turns". "Prompt's room" is not tied to the window maths.
- **13**: `ai.context_budget` 6000 can never bind under the 8k cap (60 % ≈ 3.7k).
- **14**: §7 and §4.4 still list split panes and daily notes/templates as deferred; both are built.
- **15**: section and phase order is hard to follow (§4.26 before §4.25, P22 before P21, P18.1/18.2 missing). Gather all AI rules into one section, or cross-link them.
- **16**: "opusplan" and `/model opus` (L620–625) are tooling jargon, not product terms.

**Reviewer's summary:** the AI pieces are each specified, but you can't follow the flow end to end from this document. The most useful single fix is one authoritative "AI request lifecycle" subsection: trigger → access check → assembly (with an example payload) → stream → where the output lands per `ai.edits` mode → what is stored.
