# AI edits that stay correct: plan for paper-pile (P26, with changes to P25)

> Status: **approved** (2026-10-30) with the user's answers in §13. This is the spec of P26 (PLAN §4.29).

## 0. In one paragraph

The model decides **what** to change and **where**. Python decides **how** the change goes in and whether it is **safe**.

An edit runs in short steps:
1. Python builds a numbered **block map** of the note (`B1`, `B2`, …).
2. A small **plan** call returns JSON. The JSON schema only allows block ids that really exist, so the model cannot invent a location.
3. One small **write** call per planned block returns plain text, with no JSON around it.
4. Python **applies** each text to a known block range and runs deterministic **guards**: no added headings or front matter, protected tokens kept, block kind kept, change size, language.
5. Python **checks for existing content** in the note and in the vault, and runs a **consistency sweep** over lists, tables and counts.
6. Everything is shown as **one proposal** with several hunks. Each hunk has a reason label, word-level highlights and warnings.

Nothing here is a handler for one special case. The plan step is general. The guards and sweeps are general Markdown rules. Both have deterministic fallbacks.

---

## 1. What other tools do, and what we take

| Tool / source | What they found | What we take |
|---|---|---|
| **Aider edit formats** ([formats](https://aider.chat/docs/more/edit-formats.html), [udiff](https://aider.chat/docs/unified-diffs.html)) | `whole` (the whole file again) is simple and reliable but costly. `diff` (search/replace) and `udiff` are cheap but break more often. Aider needs "flexible patching" to apply them: with it switched off, errors went up about 9×. Unified diffs reduced "lazy" placeholder output in GPT-4 Turbo (benchmark 20 % → 61 %). | Weak models do best when they write a **whole unit**. We make the unit a **block** (a paragraph, a list item, a table), not a file. So "whole" is cheap, and the model never has to write a diff. |
| **Aider leaderboard, small models** (secondary: [llm-stats](https://llm-stats.com/benchmarks/aider), [modelfit](https://modelfit.io/tools/aider/)) | Local 7B–14B models are usually run with `whole`. Qwen2.5-Coder-14B reached 100 % correct format in `whole`. Guides say small models often break search/replace blocks. | Do not ask a small model for search/replace or diff output. |
| **Aider architect/editor** ([post](https://aider.chat/2024/09/26/architect.html)) | Splitting "decide the solution" from "write the edit" helped most models, even when the same model does both (GPT-4o-mini 55.6 → 60.2 %). | We split into **plan** and **write**, using the same local model for both. |
| **Cursor instant apply** ([blog](https://cursor.com/blog/instant-apply)) | Models are bad at diff output, so Cursor rewrites the full file with a fine-tuned apply model plus "speculative edits". | We have no apply model, and we don't need one: block offsets are known, so Python does the apply. |
| **Continue / Relace / Morph** ([Continue](https://blog.continue.dev/instant-apply-with-relace), [apply role](https://docs.continue.dev/customize/model-roles/apply), [Morph](https://docs.morphllm.com)) | Search/replace failed in more than 10 % of cases; "lazy output + apply model" failed in under 2 %. Find blocks cost 1.5–2× more tokens. Search/replace breaks on whitespace and quote differences. | Never ask the model to copy the old text exactly. It names a block **id**, and Python knows the exact text behind that id. |
| **Anthropic text editor tool** ([docs](https://platform.claude.com/docs/en/agents-and-tools/tool-use/text-editor-tool)) | `str_replace` needs exactly one match. With zero or several matches it returns an error and the model tries again. | The same rule for our `locate`: one match, else the change is out of date. A guard failure gets one retry with concrete feedback. |
| **OpenAI apply_patch / Codex** ([forum](https://community.openai.com/t/responses-api-patches-function-align-your-prompting-with-the-ais-internal-instructions/1372597)) | Patches use context lines and `@@` scope lines, never line numbers. Codex had to add a "lenient" parser because models do not always write valid patches. | No line numbers. Expect format slips and handle them in Python. |
| **Zed Zeta** ([blog](https://zed.dev/blog/edit-prediction)) | The model rewrites a marked *editable region* around the cursor and gets surrounding context it must not change. | The write prompt shows context marked "do not write" and one region to rewrite. |
| **Ollama structured outputs** ([docs](https://docs.ollama.com/capabilities/structured-outputs)) | A JSON schema in `format` constrains generation token by token. Ollama advises also putting the schema in the prompt and using temperature 0. Users report preambles and schema slips on some models (gpt-oss, Qwen 3.x) ([report](https://www.glukhov.org/post/2025/10/ollama-gpt-oss-structured-output-issues/)). | JSON with `enum` ids for the plan, temperature 0, schema also in the prompt, and still validate in Python. |
| **"Let Me Speak Freely?"** (EMNLP 2024, [arXiv 2408.02442](https://arxiv.org/abs/2408.02442)) | Strict formats (JSON mode worst) hurt reasoning and free text. They can *help* classification-like tasks. | The plan is classification-like (pick ids and actions), so JSON fits it. The **new text is plain text**, never a JSON string. Markdown inside JSON also needs escaping, which small models get wrong. |
| **Obsidian Smart Composer, other plugins** ([repo](https://github.com/glowingjade/obsidian-smart-composer)) | Suggest an edit, apply it with one click, inline diffs with Accept / Reject. No public detail on how they locate edits. | Our existing inline diff stays the user-facing model. |

No public internals were found for Copilot Next Edit Suggestions, Notion AI or the Obsidian Copilot "composer", so they are not used here.

---

## 2. The user's concerns: where each one is handled

| Concern | Answer (section) |
|---|---|
| 1. A title is injected into a selection that had none; other structure is added | The write prompt shows the heading only as context marked "do not write". Guard **G1** removes a leading heading the target did not have, or retries. **G2** removes front matter, fences and wrappers. Cleanup removes commentary. (§4.5, §4.6) |
| 2. "Add a section" must go to the right place | The plan picks an anchor block with `add_after` / `add_before`. Python **snaps** it to a legal place: a section boundary for a new section, the same heading level as its siblings, never between a heading and its first paragraph. Fallback: the best-matching section. (§4.4) |
| 3. One request needs changes in many places | The plan sees the target **plus related blocks**: blocks that share key terms, sibling lists and tables, and counts. It must list *every* block needed for consistency. A deterministic **consistency sweep** then catches lists, tables and counts that were missed and offers "Update it too". (§4.3, §4.4, §4.8) |
| 4. The content already exists, fully or partly | The plan has an `already_there` field and must edit the existing block instead of adding a copy. A deterministic **shingle check** runs on every added text against the note, and against the vault through full-text search. Shown as "Already in this note …" or "Similar text in [[note § heading]]". (§4.7) |
| 5. There are many cases; the solution must be general | One pipeline for all change commands. The model does the semantic part (plan and text). Python does the mechanical part (apply, guards, sweeps), with general Markdown rules. No per-case handlers. (§3) |
| (a) A whole line is marked for a one-word fix | Word-level marks inside each hunk. (§4.9) |
| (b) Broken Markdown | **G3** protected tokens, **G4** code and math blocks masked, **G6** block kind kept, heading levels kept. (§4.6) |
| (c) Over-editing | **G5** change-size check against the expected size of the request; one retry; a warning, and no auto-apply. (§4.6) |
| (d) A long note does not fit the window | Section-by-section regions in one proposal that fills up as sections finish. (§5) |
| (e) Ticked options conflict | Each option has a `group`. Some groups allow only one choice (like a radio button). (§8) |

---

## 3. Command kinds (changes P25.1)

| Kind | Commands | Result |
|---|---|---|
| `change` | Rewrite, Change tone, and free "rewrite / add / change …" messages in the Ask box | The edit pipeline (§4) produces a proposal (diff). *Apply at once* and *Read-only* still apply (§4.9). |
| `answer` | Summarize, Explain, Outline | Streamed into the note under the target (§6). |
| `shown` (**new**) | Translate | Streamed into the answer area: the mini chat, or the chat pane. **Replace**, **Insert below** and **Copy** buttons push it into the note (§7). |

`core/ai/commands.py` (P25.1) gets `kind: Literal["change", "answer", "shown"]`. `run_command` sends `change` to `core/ai/edit_run.py`, `answer` to the existing stream-insert path (with §6 placement), and `shown` to the mini chat / chat.

---

## 4. The edit pipeline (change commands)

All new modules go in `paper_pile/core/ai/` (no UI imports). The orchestrator is `EditRun` in `core/ai/edit_run.py`. It reports progress through a callback, and the UI draws it.

```
Stage 0 target + intent (no model)
  → Stage 1 plan (1 JSON call; skipped on the fast path)
  → Stage 2 write (1 text call per planned block)
  → Stage 3 apply + guards (Python; ≤ 1 retry per block)
  → Stage 4 existing content (Python + full-text search)
  → Stage 5 consistency sweep (Python)
  → Stage 6 present one proposal
```

### 4.1 Stage 0: target and intent (deterministic)

- **Target** comes from `command_target` (P25.1): the selection, or the note body. It is fixed when the command is picked. The text snapshot is fixed when the run starts.
- **Intent** (`core/ai/intent.py`, `edit_intent(command_id, instruction, option_groups) -> Intent`):
  - `scope`: `"text"` (change only the target) or `"note"` (may touch other blocks).
  - `size`: `"small"` (fix), `"medium"` or `"large"` (rewrite or tone).
  - `asks_structure`: true when the instruction names a heading, title or section.
- Rules, from the command and short word lists (hints, not handlers):
  - Change tone → text / large.
  - An option of group `fix`, or the words grammar, spelling, typo, punctuation, proofread → text / small.
  - The words formal, casual, shorter, longer, simpler, clearer, concise, tone, rephrase → text / large.
  - A markdown form for the target (quote, blockquote, bold, italic, bullet, numbered, checklist, code block, callout, strikethrough) without an add word → text / large (2026-10-31: "put it in quote" needs no plan).
  - Anything else → `note` / medium.
- A wrong guess costs little. `note` only adds one plan call, and the plan may still choose just the target.
- **Fast path:** `scope == "text"` skips Stage 1. The target blocks become one region, and Stage 2 runs once. So Rewrite and Change tone of a selection stay **one model call**.

### 4.2 Block map and anchors

Ways the model could name a location:

| Option | Small-model reliability | Precision | After edits | Tokens | Verdict |
|---|---|---|---|---|---|
| Line numbers | Poor: models miscount | Line | Break | Low | No |
| Quoted unique text (`str_replace`) | Medium: small models paraphrase and change whitespace, so a fuzzy matcher is needed | Any span | Good (re-find) | High (1.5–2×) | Only inside Python (`locate`) |
| Heading paths | Good | Section only | Good | Low | Shown in the map for orientation |
| **App block ids + JSON `enum`** | **Very good: the decoder cannot output an id that does not exist** | A block. Items and rows through kind-aware inserts (§4.5). Words through the word diff. | Ids belong to one run's snapshot; regions are re-found by text at apply time | Low | **Chosen** |

**`core/blocks.py`** is a new public module. It moves `tidy._blocks` there, and `tidy.py` uses it too, so there is one block splitter.
- `top_blocks(text) -> list[RawBlock]` returns top-level blocks from the markdown-it tokens.
- **List items** at the top level become their own blocks. Nested items stay inside their parent item.
- A **table** is one block.
- Lines in no block become `raw` blocks.

**`core/ai/blocks.py`** adds the AI view:
```python
@dataclass(frozen=True, slots=True)
class Block:
    id: str               # "B7" (in document order, for this run only)
    kind: str             # heading paragraph item table quote code math hr html raw front_matter
    start: int; end: int  # code points in the snapshot (end = after the last char, no trailing \n)
    line: int             # 1-based
    level: int            # heading level; list depth for items; else 0
    path: tuple[str, ...] # heading path, e.g. ("Hosting", "Options")
    list_id: str | None   # items of one list share it ("L3")
    fixed: bool           # code, math, mermaid, front matter: never rewritten unless asked

def block_map(text: str) -> list[Block]
def render_view(blocks, text, full: set[str], budget: int) -> str   # the note view (§4.3)
```
Front matter is `B0`. It is fixed and shown only as `[B0] properties: title, tags`. AI edits to properties are out of scope (open question 4).

### 4.3 What the model sees: context and the 8k budget

`core/ai/edit_context.py`, `note_view(text, blocks, target, instruction, budget) -> NoteView`.

**Full text** is shown for:
1. The target blocks.
2. **Related blocks**, found deterministically:
   - **Key terms.** `query_words(instruction + target)` with light stemming (lowercase, strip a final `s` / `es`). Blocks that hold ≥ 2 key terms, or 1 term in a heading, are related.
   - **Siblings.** Every list or table whose item keys overlap the target's list or table, or whose items hold key terms. An item key is the first bold, link or code span, or the first table cell, or else the first 4 words.
   - **Counts.** Blocks with a number (a digit, or the English words one to twenty) within 3 words of a key term.
   - **Neighbours.** The block before and after each target block.
   - **The section heading** of each target.

Every other block is **one outline line**: `[B23] item: Docker — runs the app in a …`, with its first ~10 words. Long runs far from anything related are folded into one line: `[B40–B77] 38 blocks under "## Budget"`. All headings are always listed, so the model sees the note's structure.

**Vault hits.** `Index.search(" ".join(key_terms), any_words=True)` gives at most 3 readable notes other than the current one (checked with `read_note`). Each is shown as `best_section` cut to ~150 tokens, labelled `[V1] notes/x.md § Options`. Plan calls only.

**Budget per plan call at 8192 tokens.** All shares scale with `window` (`EditBudget.for_window(window)`). If the estimated total goes over, outline lines are dropped first, then vault hits, then related blocks from the farthest away. Target blocks are never dropped. A target over its share switches to the section-by-section path (§5).

| Part | Tokens |
|---|---|
| Answer room (`num_predict`) | 512 |
| System prompt + edit rules | ~600 |
| Task + instruction | ~150 |
| Target blocks (full) | ≤ 1800 |
| Related blocks (full) | ≤ 1800 |
| Outline lines | ≤ 1600 |
| Vault hits | ≤ 450 |
| Margin for the rough token estimate | ~1200 (15 %) |

**Shared prefix.** Messages are built as `[system][user: "The note, as numbered blocks:\n<view>"]` followed by the task as the last message. Plan and write calls use the **same first two messages**. Ollama keeps the KV cache of the last prompt in a slot and evaluates only the new suffix. On CPU this is the difference between seconds and minutes. P26.15 measures the cache hits: Ollama reports `prompt_eval_count`, exposed in `Finish`.

When `prefix + write suffix + reply_room(block) > window`, a write call drops the view and uses a compact prompt instead (§4.5).

### 4.4 Stage 1: plan (one call, JSON with a schema)

**Call settings:** `format = <schema>`, `think = False`, `temperature = 0`, `num_predict = 512`. `AiEngine.ask_json(messages, schema) -> dict | None` streams, joins, and parses with `json.loads`.

**Task message:**
```
Task: {instruction}
The user selected blocks B7–B9. | The user selected nothing (the whole note).

Plan the edit. Do not write the new text yet.
Rules:
- Change as few blocks as possible, but every block that must change so the note stays
  consistent: lists, tables, counts ("three options"), summaries, introductions, tables of
  contents.
- If what the task adds is already in the note, do not add it again. Put that block in
  "already_there". If it is incomplete, add a "change" for that block instead.
- New content goes where a careful editor would put it: in the section it belongs to, after the
  last related block, in the note's own order. Add after a list item or table to extend that
  list or table.
- Set "new_section" to true only when the task asks for a new section or heading.
- "why" is a short phrase for the user, like "add the option to the table" or "update the count
  in the intro".
- If the task is messy, can be read in more than one way, or asks for several things at once,
  rewrite it as 2-4 short, clear requests in "options" (each one complete on its own, in the
  user's language) and leave "edits" empty. A clear task gets no options.
- If the task is unclear and options would not help, write one short question in "question"
  and leave "edits" empty.
Answer with JSON only, matching this schema: {schema as compact JSON}
```

**Schema.** `IDS` is the list of non-fixed block ids. `VIDS` is the vault hit ids. `"why"` comes first in each item, because a reason written first steers the choice that follows.
```json
{"type":"object","properties":{
  "already_there":{"type":"array","maxItems":3,"items":{"type":"object","properties":{
      "block":{"enum":["...IDS", "...VIDS"]},
      "amount":{"enum":["all","part"]}},
    "required":["block","amount"]}},
  "edits":{"type":"array","maxItems":6,"items":{"type":"object","properties":{
      "why":{"type":"string","maxLength":80},
      "action":{"enum":["change","add_after","add_before","delete"]},
      "block":{"enum":["...IDS"]},
      "new_section":{"type":"boolean"}},
    "required":["why","action","block","new_section"]}},
  "options":{"type":"array","maxItems":4,"items":{"type":"string","maxLength":120}},
  "question":{"type":"string","maxLength":160}},
 "required":["already_there","edits","options","question"]}
```

**Validation and snapping in Python** (`core/ai/plan.py`, `parse_plan`, `snap`):
- Unknown ids are dropped. If Ollama ignored the schema, the first `{…}` in the text is parsed.
- At most 6 edits. Duplicates are merged: `change` wins over another `change` on the same block, and `add_*` edits are kept apart.
- **New section** (`new_section: true`):
  - The anchor moves to the **end of the anchor's section**, before the next heading of level ≤ L.
  - The new heading level is the level of sibling sections: the anchor section's level, or 2 when the note has no headings (1 only if every heading is level 1).
  - `add_before` on a heading stays at that heading.
- **Add without a new section:**
  - The anchor kind sets the content kind: item → new list items, table → new rows, other → paragraphs.
  - An anchor on a heading moves to after the section's last block.
  - An anchor on a fixed block moves to after it.
- **`delete` outside the target** is allowed but gets a `warn` issue (§4.6).
- **`options` with no edits** (only when the run may offer them: Ask box requests; a text-only request on the fast path never reaches the planner, so it gets none) (2–4 items; 1 item = that request runs at once; more than 4 = cut): the run stops and the options are shown in the **options box** (PLAN §4.28: a checkbox each, "Your own: …", Apply N) as the AI's message in the Ask box or chat. Apply runs once more with the ticked options (and own words) as the instruction and **options switched off**, so a run never asks twice. Options and edits together → the edits win. Off when the run already came from the options box.
- **`question` with no edits:** the run stops. The question is shown as the AI's message in the Ask box or chat. The user's reply re-runs with "Answer: …" added to the task.
- **`already_there` with `all`** and no edits: no proposal. A notice "Already in this note: …" with [Show] (§4.7).

**Fallbacks** (no model needed):

| Case | Fallback |
|---|---|
| JSON still invalid after one retry (temperature 0, outline halved) | Deterministic plan |
| Selection, plan failed | One `change` on the target. Bar note: "Changed only the selected text; the AI could not plan other places." |
| No selection, the task adds content | `add_after` the last block of the best section (`best_section` scoring on key terms; else the end of the note) |
| `ai.edit_planning = "selection"` (§9) | Skip Stage 1 always |

### 4.5 Stage 2: write (one plain-text call per edit)

**Order.** The edit on the target first, then `add_*`, then other `change`s. Each later call gets "Already written for this task:" with the earlier new texts (≤ 400 tokens). This way the intro's count update knows the new option's name.

**Settings.** `think = False`. Temperature `min(ai.temperature, 0.3)` (low temperature limits over-editing). `num_predict = reply_room(block)` for a change, 600 for an add (at most 1500).

**Common system rules** (appended to `system_head`; the same text in every edit call, to keep the prefix stable):
```
You edit one part of a markdown note. Reply with only the new text of that part: no
introduction, no comments, no code fence around it, no heading unless the part is a heading.
Keep the language of the note. Keep links, images, code, math and #tags exactly as written.
```

**Change message:**
```
Task: {instruction}
This change: {why}
Where it is (context, do not write it): {heading path, "Hosting › Options"}
Before it (context, do not write it):
{previous block, ≤ 60 words}
The text to rewrite [B8]:
<<<
{block text, code/math blocks replaced by ⟦KEEP 1⟧ lines}
>>>
After it (context, do not write it):
{next block, ≤ 60 words}
Already written for this task: {…}
Keep exactly: [[Hosting plan]], `docker run`, $x^2$, https://…, #infra
Reply with the new text for [B8] only.
```

**Add messages.** Python adds a style hint for the anchor's kind (per Markdown kind, not per case):
- **Item:** "Write only the new list item(s) for this list. Start each with `- ` like its items, for example: `- **Fly.io** — …`." The example is the first sibling, cut short.
- **Table:** "Write only the new row(s) for this table. Each row has exactly 3 cells: `| … | … | … |`. The header is: `| Name | Price | Notes |`."
- **Section:** "Write the new section. Start with one heading line at level 2 (`## `), then its text. No other heading of level 1 or 2."
- **Paragraph:** "Write only the new paragraph(s)."

**Compact prompt.** Used when the shared prefix plus the answer does not fit. The same as above without the note view; the heading path and neighbours carry the context.

**Python merge** (`core/ai/write.py`, `merge_new(block, action, text) -> str`):
- **Items:** force the sibling marker and indent. Renumber an ordered list from the anchor. If the previous block is a list with the same marker and the new text is meant as a separate list, use the other bullet character (`-` and `*` start different lists in CommonMark).
- **Rows:** `split_row` each line; pad or cut to the column count with a `warn`. If the original table was aligned (`format_table(parse_table(t)) == t`), insert the rows and re-run `format_table`.
- **Blank lines:** exactly one blank line between blocks. The original trailing newline is kept.

**Masking.** Fenced code, `$$` math and mermaid blocks inside a target become `⟦KEEP n⟧` lines before sending, and are restored after. Inline tokens are **checked, not masked**: a wikilink's words carry meaning the model needs, and small models often mangle placeholders inside sentences.

### 4.6 Stage 3: apply and guards (deterministic)

`core/ai/guards.py`, `check(ctx: GuardContext, old: str, new: str) -> list[Issue]` and `repair(...) -> (str, list[Issue])`.

`Issue(kind, severity, message, data)`. Severities:
- `fixed`: repaired. Shown as a small grey note.
- `warn`: shown on the hunk. Accept still works. **The whole proposal is never auto-applied.**
- `retry`: ask once more.
- `drop`: that edit is not shown and is listed in the bar.

| # | Guard | Check (Python, existing parser where possible) | Repair | On trip |
|---|---|---|---|---|
| G1 | No added or removed headings | `parser.headings()` on old and new. A non-heading change → 0 headings. An add without new section → 0. A new section → exactly 1 at the first line, at the snapped level (deeper sub-headings only if `asks_structure`). A target with headings → same count and same levels (the text may change if asked). | A leading heading the target did not have is removed (**title injection**). A wrong level on the new section heading is set to the snapped level. | A heading in the middle of new text, or a missing or extra heading → retry ("Do not add headings." / "Keep the heading `### Sub` at level 3."), then `warn` |
| G2 | No front matter or wrappers | New text starts with `---`/YAML, an outer fence, `<<<`/`>>>`, or a label like `[B8]:` / `Block B8:` | Strip | — |
| G3 | Protected inline tokens | Multiset from old: `[[…]]`, `![[…]]`, `![](…)`, link URLs, bare URLs, `` `code` ``, `$…$`, `#tags` (`inline_tags`), `[^n]`, `^block-id`, HTML tags and comments. Each must be in new, except tokens the instruction names (remove / unlink + the token's text). | — | Retry listing the missing ones ("You dropped [[Hosting plan]] and `npm i`. Keep them exactly."), then `warn` "Lost: …" |
| G4 | Fixed blocks byte-identical | Every `⟦KEEP n⟧` appears exactly once | Restore | A missing placeholder → retry, then `drop` that edit |
| G5 | Change size | `change_share(old, new)` = 1 − difflib ratio on word tokens. Limits: small 0.2, medium 0.6, large none; a small fix may always change up to 3 words (`SMALL_WORDS`, 2026-10-31: three typos in a short sentence are a large share of it). (No separate "much shorter" check: it always trips this one first.) | — | Small intent over the limit → retry ("Change only what is wrong; keep every other word."), then `warn` "Changed 64 % of the words (asked: small fixes)" |
| G6 | Block kind kept | `top_blocks(new)` kinds equal old's (a list stays a list, a table keeps its column count), unless `asks_structure` | Renumber ordered lists | `warn` |
| G7 | No echoed context | ≥ 60 % of a neighbour block's word 3-shingles, or the "do not write" lines, appear in new | Trim an echo at the start or end | `warn` |
| G8 | No commentary | `cleanup.clean_reply` rules (§6.2) | Strip | — |
| G9 | Language kept | Main script of the letters (`unicodedata.name` prefix: LATIN, BENGALI, CJK…) old vs new; skipped for Translate | — | `warn` |
| G10 | Finished and non-empty | `finish == "stop"` and `new.strip()` | — | `drop` ("The AI's answer was cut off; nothing was changed there.") |

- **Retry policy:** at most **one retry per block** per run, only for G1, G3, G4 and G5. The feedback names the exact problem.
- **Allowed by the instruction:** `asked_for(instruction, kind)` uses short word lists per guard (heading / title / section; remove / delete / unlink …). It only *relaxes* a guard.

### 4.7 Stage 4: existing content (`core/ai/existing.py`)

- **Normalise text:** strip Markdown with `plain_line`, lowercase, words of ≥ 3 letters, word 3-shingles. `containment(a, b) = |sh(a) ∩ sh(b)| / |sh(a)|`.
- **In the note**, for every add:
  - containment of the new text, per item or row, in any block ≥ 0.6, **or** an equal item key → `Issue("exists", block, line, path)`.
  - Severity `warn` on that hunk: "May repeat line 42 (## Options)" with [Show].
- **In the vault:**
  - `Index.search(query_words(new)[:8], any_words=True)` → up to 6 readable notes other than this one → `best_section` → containment ≥ 0.5 → a proposal note "Similar text in [[hosting § Options]]" (opens on click).
  - Information only. The AI **never edits the other note** (open question 3).
- **From the plan:**
  - `already_there: all` + no edits → no proposal, notice: "This is already in the note: “…” (## Options, line 42). [Show]".
  - `part` → shown in the bar as "Completes the existing text at line 42".
- **Answer commands:** a heading or bold label matching the command (Summary, TL;DR, Outline, Explanation) in the target's section → notice "This note already has a Summary (line 3)". The answer is still written. Information, not a block.

### 4.8 Stage 5: consistency sweep (`core/ai/consistency.py`)

Runs after the writes, with no model call. Works on any list or table, not on one case.
- **Sibling structures.** For each list or table that got items or rows:
  - Look at every *unedited* list or table that shares ≥ 2 item keys (≥ 50 % of its keys) with it.
  - If it lacks the new key → suggestion "The table under ## Comparison lists the same items but not “Fly.io”".
- **Counts.**
  - If a list or table went from n to m items, look at unedited blocks for `n` or its English number word within 3 words of a term from that structure's heading or lead-in line. Example: "We compare **three** options".
  - → suggestion "The intro says “three options”."
  - Other languages: digits only.
- **Shown as:** "Maybe also update: … [Update]". [Update] runs **one** write call (`why` = the suggestion) and adds a region to the same proposal.

### 4.9 Stage 6: present one proposal

**`core/ai/proposals.py` grows regions.** `propose()` is kept for single-region callers.
```python
@dataclass(frozen=True, slots=True)
class Hunk:   id: int; start: int; end: int; old: str; new: str
              reason: str = ""; issues: tuple[Issue, ...] = (); outside: bool = False
              marks: WordMarks | None = None      # word ranges, old side and new side
@dataclass(frozen=True, slots=True)
class Region: start: int; old: str; hunks: tuple[Hunk, ...]
@dataclass(frozen=True, slots=True)
class Proposal: id: int; path: str; regions: tuple[Region, ...]
                notes: tuple[Issue, ...] = ()      # exists / elsewhere / maybe-update / dropped
def propose_many(path, text, changes: list[PlannedChange]) -> Proposal | None
def word_marks(old: str, new: str) -> WordMarks | None   # None when > 60 % changed (noise)
```
- `locate` and `accept` work **per region**. A region that is gone or found twice is out of date. Its hunks are greyed and Accept is disabled; the others still work.
- **Accept all** applies all live hunks in one transaction (one undo step) and keeps one "before AI" version (as now).

**`proposal.js`** (it only draws):
- A reason label at the top of each green block.
- Chips: `outside selection`, warnings (amber), `fixed` notes (grey).
- Word marks: `Decoration.mark` `pp-aidiff-delword` on deleted lines, and `<span class=pp-aidiff-addword>` in the added lines.
- A bar: "AI suggests 3 changes in 3 places · 14 words changed · ‹ › · Accept all · Reject all", plus a second line for notes.
- ‹ › jumps between hunks (existing `gotoLine` flash).

**Modes:**
- **Ask first:** diff.
- **Apply at once:** applied only when there are no `warn` issues **and** every hunk is inside the target. Otherwise a diff with the notice "Some changes need a look" (open question 1).
- **Read-only:** diff with Copy / Close.

**Progress:** the notice says "Planning…", "Writing 2 of 4…", then "Checking…". Stop keeps the regions already finished as the proposal.

---

## 5. Long text: section by section (concern d)

- **When:** Rewrite or Change tone on the whole note, or on a selection whose target goes over the target share (§4.3).
- **Chunks:** `chunks(blocks, max_tokens)` splits at `#` / `##` section starts, and further at block boundaries. The size is about (window − answer) / 2.5, so ~2k tokens at 8k.
- **Each chunk is one write call.** The shared prefix holds the note's heading outline (for consistent tone). The suffix holds the chunk and the last rewritten paragraph of the previous chunk (for flow). The fast-path rules apply: G1 keeps all headings and levels, G3 the tokens, G5 the size.
- *As built (2026-10-31):* `edit_context.chunks` / `chunk_tokens` in the fast path; each part is a region of one proposal shown at the end (the progressive display below is not built yet). Answer commands: `core/ai/longtext.py` `condensed` (the map step), then the usual streamed answer from the parts' summaries.
- **Progressive proposal:** each finished chunk adds a region at once ("Rewriting 2 of 5 · Stop"), and the user may Accept earlier regions while later ones are written.
- **Summarize / Outline of a note that does not fit:** map–reduce. One call per chunk (≤ 120 words each), then one final call on the chunk results. More than 8 chunks → the first 8, with the context line "first 8 of 12 parts".

---

## 6. Answer commands (Summarize, Explain, Outline)

### 6.1 Where the answer goes

*Built 2026-10-31 (P26.12):* `core/ai/placement.py` (`answer_point`, `already_answered`); the bullet switch is `StreamCleaner(avoid_bullet=)`; the heading floor is `cleanup.heading_floor`. Answer commands and Translate run with `think=False` (their reasoning is never shown and costs minutes on thinking models).

`core/ai/placement.py`, `answer_point(text, target) -> AnswerPoint(offset, lead, heading_floor)`:
- **Selection:** the end of the **top-level block** that holds the selection's end. A paragraph ends at the paragraph, a list after the whole list, a quote or callout after the quote, a table after the table, code after the fence.
  - The answer never lands inside a list item or table.
  - `lead = "\n\n"`.
  - If the previous block is a list and the answer starts with the same bullet character, use the other one (`-` or `*`) so they stay two lists.
- **Whole note:** the end of the note (as specified in PLAN §4.28).
- **`heading_floor`:** the level of the section at the insertion point.
  - Headings in the answer at level ≤ floor are **demoted** to floor + 1 (at most 6), so the answer never splits the user's section.
  - A first heading that only repeats the note or section title is dropped.

### 6.2 Clean output (both kinds)

One module, `core/ai/cleanup.py`. `clean_reply` moves here and `edits.py` re-exports it.

**Rules, in order:**
1. `<think>…</think>` removed. An unclosed `<think>` at the start: everything up to `</think>` is dropped; with no `</think>` the answer is empty (G10).
2. One leading preamble line (`_PREAMBLE`) removed. Also removed: labels like "Translation:", "Rewritten text:", "Summary:" when alone on the first line, `[B8]:`, and echoed `<<<` / `>>>`.
3. One closing commentary paragraph (`_CLOSING`, plus a final "(Note: …)") removed.
4. One outer fence removed, unless the original was fenced.
5. Front matter at the start removed.
6. Trailing spaces trimmed. The region's own trailing newline restored.

**While streaming** (`StreamCleaner`; covers P25.3):
- `feed(piece) -> str` buffers the **head** until the first newline (or 200 characters), then decides: preamble → drop; heading → demote or drop (§6.1); opening fence → drop and remember; `<think>` → suppress until `</think>`. After that, text passes through.
- `finish() -> str` writes the rest. The last paragraph (and the blank line before it) is always held back until the next one starts, so a closing paragraph or the closing fence is dropped before it is ever written — nothing has to be taken out of the note again (built P26.6).

---

## 7. Translate: shown, then pushed by the user

*Built 2026-10-31 (P26.13) in the Ask box (`edit_run.replacement_result` for Replace — its diff has no Try again —, `answer_point` for Insert below). In the chat pane a Translate answer is a chat answer with the chat's own Copy / Insert into note / Apply to note.*

- **Where:** with a selection, the Ask box's mini chat; in the chat box, or with the whole note as target, the chat pane. Streamed and rendered as now.
- **Buttons under Translate answers only** (an exception to the "no buttons under answers" rule, by the user's decision):
  - **Replace**: selection targets only. Goes through the normal proposal path: diff in Ask first, applied in Apply at once, guards G1–G4 and G6. G9 is skipped. The G3 variant for wikilinks: the target must stay, the alias may change.
  - **Insert below**: uses `answer_point` (§6.1), one undo step, "before AI" version kept.
  - **Copy**.
- **Read-only** hides Replace and Insert. If the selected text changed before Replace, `locate` fails → "The text changed; use Insert below or Copy."
- **Prompt:**
  ```
  Translate the text into {language}. Keep the markdown exactly: headings, lists, tables, links, images. Do not translate code, URLs, #tags, math, or the note name inside [[ ]] (translate only the text after |). Reply with only the translation.
  ```
- **No words:** the options box suggests languages, starting with the app language.

---

## 8. Options box (changes P25.2 / P25.5)

Schema (`format`, temperature 0, `think = False`):
```json
{"type":"object","properties":{"options":{"type":"array","minItems":3,"maxItems":5,"items":{
  "type":"object","properties":{
    "label":{"type":"string","maxLength":60},
    "group":{"enum":["fix","length","tone","clarity","structure","content","language","other"]}},
  "required":["label","group"]}}},"required":["options"]}
```
- **Single-choice groups:** `length`, `tone`, `language`. Ticking one unticks the others in its group, with a short hint "Only one length". Other groups combine freely.
- **Intent:** `group` feeds `edit_intent`. `fix` → small. `content` → scope `note` (planned). Others → text.
- **Apply N** builds one instruction: "Do all of these: 1) … 2) …" plus the "Your own" words.
- **Fallback lists** per command carry groups too.

---

## 9. Small-model realism

### Model calls per command

Rough guesses for a 7–9B Q4 model; to be measured in P26.15.

| Case | Calls | Rough time (GPU / CPU only) |
|---|---|---|
| Rewrite / Change tone of a selection (fast path) | 1 (+ ≤ 1 retry) | 2–6 s / 15–40 s |
| Content edit ("add option D") | 1 plan + N writes, N = 1–4 (+ ≤ 1 retry each) | 6–15 s / 40–120 s (less with prefix-cache hits) |
| "Update it too" | +1 | |
| Options box | +1 before the run | |
| Whole-note rewrite | 1 per chunk | |
| Answer command | 1 | |

### Provider changes (P26.1)

- `GenerationOptions.schema` (a JSON schema, sent as Ollama's `format`) and `GenerationOptions.think`, per call through `AiEngine.stream(schema=, think=, temperature=, max_answer=)` — the `Provider.chat` signature stays the same (built P26.1). `ollama 0.6.3` (pinned) has both parameters on `AsyncClient.chat`. `AiEngine.ask_json` + `core/ai/structured.py` `parse_json_object` (lenient: the first `{…}` that parses).
- `Finish` gets `prompt_tokens` and `eval_tokens` (not part of equality); the engine keeps the last pair in `last_usage`.
- `think=False` for every JSON and edit call. If Ollama answers that the model "does not support thinking", resend without `think`.
- `FakeProvider` gets `script: list[str] | Callable[[list[ChatMessage]], str]` for scripted replies.

### Setting `ai.edit_planning`

Settings → AI → Edits, "Plan edits across the note": `auto` (default) / `selection` (never plan; one call; deterministic placement). For slow, CPU-only setups. See open question 2.

### When the model misbehaves

| Failure | Detected by | Done |
|---|---|---|
| JSON invalid, cut, or schema ignored | `json.loads`, validation | Parse the first `{…}`; one retry (temperature 0, outline halved); then the deterministic plan (§4.4) |
| Plan anchors a heading or the middle of a section | `snap` | Snapped |
| Plan returns nothing | Validation | Deterministic plan |
| Too many edits; deletes outside the target | Validation | Cut to 6; deletes get `warn` |
| Preamble, title, fence, wrapper | Cleanup, G1, G2 | Stripped (`fixed`) |
| Dropped tokens, over-edit, added heading | G1, G3, G5 | One retry, then `warn` (no auto-apply) |
| Echoed context | G7 | Trimmed or `warn` |
| A thinking model uses its budget on reasoning | Empty content or `length` | `think=False`; else `drop` with a message |
| Ollama down or busy mid-run | `ProviderError` | Finished regions are kept as the proposal; a notice |

### When the run ends without a change: the user retries (user, 2026-10-31)

A run that ends without a proposal — or with one the user does not like — never just disappears. The AI's message (in the Ask box's mini chat, or in the chat when it ran from the chat box) says **why in one line** and carries buttons:

| Ending | Message | Buttons |
|---|---|---|
| Cut off, stopped by an error, Ollama down mid-run | "The AI's answer was cut off; nothing was changed." / the provider's text | Try again · Change request |
| Nothing left after the guards (every edit `drop`ped) | "Nothing was changed: <the reasons>." | Try again · Change request |
| The model declines ("I can't…", empty plan, plan with no edits, no options, no question) | "The AI made no change: <its reason, cut to one line>." | Try again · Change request |
| `already_there: all` | "Already in this note: “…”" + [Show] | Add it anyway · Change request |
| Proposal shown (diff) | — (the diff bar) | the bar gets **Try again** next to Reject all (rejects, then runs again) |
| A proposal with a G5 "changed too much" warning | the warning on the hunk | + **Smaller change** (runs again with "Change only what is needed; keep every other word.") |

- **Try again** runs the same instruction on the same target as a new run (a fresh plan; the automatic one-retry-per-block policy above applies again). When the target text is gone or changed, the button is disabled with "The text changed — select it again".
- **Change request** puts the user's words back in the box (Ask box, or chat composer) with the command chip, caret at the end.
- **Smaller change** runs again with "Change only what is needed; keep every other word" and the change-size limit one step down (large → medium → small).
- **Add it anyway** runs again with "The user wants it added even though similar text exists." (`already_there` is then ignored; when the plan still names no edits, the text is placed by the deterministic plan).
- A run started from these buttons is a normal run (diff in *Ask first*, the same guards); it never applies more than the first would have.
- A **question** from the planner: shown in the box; the user's next message there answers it (the request runs again with "Answer: …", without options).
- Where it shows: a run from the editor (slash menu, palette, Ask box) reopens the Ask box at the target as the mini chat holding that message; a run from the chat box answers in the chat. *As built (2026-10-31):* the Ask box only; ⋯ Rewrite and the slash menu with the box off still end in toasts until P25.4 sends them through the box, and the chat box gets it with its AI commands (P25.4).

**The safety promise.** Whatever the model outputs, nothing with a guard warning is applied without the user seeing it, and nothing outside the target is applied silently. Guards are deterministic, so this is testable at 100 %.

---

## 10. Evaluation harness

- **Fixtures:** `tests/fixtures/ai_edits/<case>/`
  - `note.md`: the selection is marked `⟦sel⟧…⟦/sel⟧`.
  - `case.json`: `{command, instruction, options?, expect}`.
  - `fake.json`: scripted model replies for unit mode, including bad ones.
- **Checks:** `tools/ai_eval/checks.py`, shared by unit tests and the real run. `headings_unchanged(except_new_section_level)`, `tokens_kept`, `changed_blocks ⊇ / ⊆ {anchor texts}`, `inserted_after(anchor_text)`, `heading_level(n)`, `no_duplicate(key)`, `contains / not_contains`, `change_share ≤ x`, `note_kinds ∋ "exists" / "maybe-update"`, `auto_applied == false when issues`.

| # | Case | Pass when |
|---|---|---|
| 1 | Section body selected without its heading; Rewrite | No heading in the result; the heading count of the note is unchanged |
| 2 | 3 typos; Rewrite "fix grammar" | Typos fixed; change share ≤ 0.15 |
| 3 | A paragraph with `[[a\|b]]`, `![[img.png]]`, `` `code` ``, `$x^2$`, `#tag`, a URL | All kept |
| 4 | "Add a section about backups" (## Setup / ## Usage / ## Maintenance / ## FAQ) | One `##` heading, at a section boundary near Maintenance, not inside a section |
| 5 | Options note: intro "three options", a list of 3, a table of 3 rows, a summary paragraph; "add option D: Fly.io" | List +1, table +1 row (right column count), the intro says four; ≥ 3 regions |
| 6 | Add "Docker", already in the list | No insert; an `exists` notice |
| 7 | An option in the list but missing from the table | Only the table changed |
| 8 | Text that exists in another vault note | `elsewhere` note with a link |
| 9 | A selection that includes `### Sub` | Level 3 kept |
| 10 | A selection with a fenced code block | The code block byte-identical |
| 11 | Whole-note rewrite over the window | Per-section regions; headings unchanged |
| 12 | Translate → Replace | Code, URLs and wikilink targets unchanged |
| 13 | Summarize a selection ending in a list | Inserted after the list, as a separate block |
| 14 | Options: two `length` options ticked | Only the last stays ticked (unit) |
| 15 | Bengali paragraph, Rewrite | Script kept |
| 16 | Model replies with a preamble, a closing line, a fence, `<think>`, invalid JSON, an unknown id | Cleaned / fallback used (unit) |

- **Unit mode:** part of `uv run pytest -q`, with `FakeProvider(script=…)`. Checks exact pipeline results, including every bad-output path.
- **Real mode** (opt-in): `uv run python tools/ai_eval/run.py --model gemma4:12b --runs 3 [--case 05]` (as built 2026-10-31: the harness is the package `tools/ai_eval/` — `cases.py`, `checks.py`, `run.py`; no pytest mark). Each run gets a scratch vault, config and access grant. Prints the pass rate per case and the failing checks, the calls and the time; the JSON report goes to a scratch folder. A case's `expect` holds the checks any model must pass, `expect_unit` the scripted replies' exact wording; `unit_only` cases (16a/b: bad model output) and case 14 (`test_single_choice_groups`) run in unit mode only; `num_ctx` gives the long-text case (11) a small window. Prefix-cache hits are not measured yet.
- **Pass criteria:**
  - Safety checks (nothing that broke a guard is applied silently) at 100 %.
  - Quality on one 7–9B instruct model ≥ 80 % of runs for cases 1–4, 6, 9, 10, 15, and ≥ 60 % for cases 5, 7, 8.
  - Baselines for one 3–4B, one 7–9B and one 12–14B model go in TRACKER. A prompt change that drops a case by more than 10 points must be reverted or explained.

---

## 11. Files

| File | New / changed | Role |
|---|---|---|
| `paper_pile/core/blocks.py` | New (from `tidy._blocks`) | Top-level blocks, list items |
| `paper_pile/core/ai/blocks.py` | New | `Block`, `block_map`, `render_view` |
| `paper_pile/core/ai/intent.py` | New | `edit_intent`, `asked_for` |
| `paper_pile/core/ai/edit_context.py` | New | Related blocks, vault hits, budgets, shared prefix |
| `paper_pile/core/ai/plan.py` | New | Plan prompt and schema, `parse_plan`, `snap`, fallback |
| `paper_pile/core/ai/write.py` | New | Write prompts, masking, `merge_new` |
| `paper_pile/core/ai/cleanup.py` | New (`clean_reply` moves here) | Rules, `StreamCleaner` |
| `paper_pile/core/ai/guards.py` | New | G1–G10 |
| `paper_pile/core/ai/existing.py` | New | Shingles, in-note and vault checks |
| `paper_pile/core/ai/consistency.py` | New | Siblings, counts |
| `paper_pile/core/ai/placement.py` | New | `answer_point` |
| `paper_pile/core/ai/edit_run.py` | New | `EditRun` orchestration, events, retries, modes |
| `paper_pile/core/ai/proposals.py` | Changed | Regions, reasons, issues, word marks |
| `paper_pile/core/ai/provider.py`, `ollama.py`, `fake.py` | Changed | `format`, `think`, token counts, scripts |
| `paper_pile/core/ai/engine.py` | Changed | `ask_json`; `stream(format=, think=)` |
| `paper_pile/gui/components/editor_pane.py` | Changed | `_run_edit` uses `EditRun` events; proposal payload |
| `tools/editor_src/proposal.js` | Changed | Labels, chips, word marks, ‹ ›, out-of-date |
| `tools/ai_eval.py`, `tools/ai_eval/checks.py`, `tests/fixtures/ai_edits/` | New | Harness |

---

## 12. Tasks

### Changes to P25 (specified, not built)

| ID | Change |
|---|---|
| P25.1 | Translate moves to the new kind `shown`. `run_command` sends `change` to `EditRun` (P26.9), `answer` to placement (P26.12), `shown` to the mini chat / chat (P26.13). |
| P25.2 | Options are objects `{label, group}` from a JSON-schema call (needs P26.1); fallback lists with groups. |
| P25.3 | Built as `core/ai/cleanup.py` `StreamCleaner` (shared with P26.6), plus heading demotion. |
| P25.5 | Single-choice groups (length / tone / language). |
| P25.6 | "Change → diff" is the P26 pipeline. Translate's push buttons move to P26.13. |

**Suggested order:** P26.1 → P25.1 → P26.2–P26.9 → P25.2–P25.6 with P26.10 → P26.11–P26.16.

### P26: Reliable AI edits (PLAN §4.29)

| ID | Task | Acceptance |
|---|---|---|
| P26.1 | Provider: per-call `format` + `think`; `Finish` token counts; scripted fake | Ollama gets `format` / `think` (transport test); "does not support thinking" → resent without; `FakeProvider(script=…)` replies in order (tests) |
| P26.2 | Block map (`core/blocks.py`, `core/ai/blocks.py`) | `tidy` uses `core/blocks.py` and its tests stay green; ids, kinds, heading paths, list items, fixed blocks and offsets correct on fixture notes (tests) |
| P26.3 | Edit context and budget | Related blocks found for fixture cases 4–8; the view fits `EditBudget.for_window(4096 / 8192 / 32768)`; target blocks never dropped; vault hits go through the access check (tests) |
| P26.4 | Planner | Schema has the `enum` ids; parse and validate; `snap` rules (new section at a section end, sibling level, never after a bare heading); `already_there` / `question` paths; deterministic fallback when the JSON is bad (tests with scripted replies) |
| P26.5 | Writer and merge | Prompts per kind; order with "Already written"; `⟦KEEP n⟧` masking and restore; item marker and renumbering; table rows with the right column count and re-aligned; compact prompt when the window is short (tests) |
| P26.6 | Cleanup and guards G1–G10 | Each guard has trip / no-trip tests; title injection removed (`fixed`); one retry with the feedback text; `warn` blocks auto-apply; `StreamCleaner` covers preamble, heading, fence and `<think>` while streaming (tests) |
| P26.7 | Existing content and consistency sweep | Cases 6, 7, 8 and the sibling / count suggestions found deterministically; vault check respects access (tests) |
| P26.8 | Multi-region proposals | `propose_many`; per-region `locate` / `accept`; out-of-date per region; Accept all = one change set; `word_marks` (tests); `propose()` callers unchanged |
| P26.9 | `EditRun` orchestration | Fast path = 1 call; content edit = 1 + N calls; progress events; Stop keeps finished regions; modes (Apply at once only clean and inside the target); "before AI" version once (tests with fake) |
| P26.10 | Diff UI | Reason labels, chips, word marks, ‹ › jump, notes line, greyed out-of-date hunks, "Update it too" button; both themes (real app, real mouse events; `qa_editor.py` green) |
| P26.11 | Long text | Whole-note rewrite in chunks fills one proposal progressively; Summarize map–reduce over the window (tests + real app) |
| P26.12 | Answer placement | `answer_point` for paragraph / list / quote / table / code / whole note; heading floor demotion; bullet switch; "already has a Summary" notice (tests) |
| P26.13 | Translate push flow | Mini chat and chat show Replace / Insert below / Copy on Translate answers only; Replace → proposal with guards; read-only hides them (tests + real app) |
| P26.14 | Eval harness, unit | All 16 cases run in `pytest -q` with scripted replies |
| P26.15 | Eval harness, real Ollama | `tools/ai_eval.py` report; baselines for 3 model sizes in TRACKER; prefix-cache hits measured (switch writes to compact prompts if they rarely hit) |
| P26.17 | Edit another note on request | An instruction that names another note (`[[x]]` / `@x`) and asks to change it plans blocks in that note too (access check); its changes are a proposal shown when that note opens in a tab, never applied silently (tests + real app) |
| P26.18 | Options from the planner (user 2026-10-31) | `options` in the schema and prompt; 2–4 → stop with options, 1 → run it, options + edits → edits; the re-run from the options box has options off (tests with scripted replies) |
| P26.19 | User retry (user 2026-10-31) | `EditRun` ends with a typed outcome (`cut` / `dropped` / `declined` / `already_there` / `proposal`) + a one-line reason; Try again / Change request / Add it anyway / Smaller change build the right next run; target gone → disabled (tests); the buttons in the mini chat, the chat and the diff bar (real app, real mouse events) |
| P26.16 | Setting + docs | `ai.edit_planning` (Auto / Selection only) in Settings → AI; PLAN §4.26 edit table, §4.28 and §4.29 match the code; QA checklist |

---

## 13. The user's answers (2026-10-30)

1. **Changes outside the selection:** made when the edit needs them, each place with its own Accept / Reject. They are **never** applied without a diff, also in *Apply at once* (only a clean change inside the target is applied at once).
2. **"Selection only" setting:** yes — `ai.edit_planning`, *Auto* (default) / *Selection only*.
3. **Similar text in another note:** only told, with a link. The other note is changed only when the user asks for it (names it in the instruction, `[[note]]` or `@note`); then it gets its own diff in that note (P26.17).
4. **Properties (front matter):** never changed by AI edits for now.
5. **Continue writing:** removed entirely (command, prompt and tests).

---

## Sources

- Aider: [edit formats](https://aider.chat/docs/more/edit-formats.html), [unified diffs / laziness / flexible patching](https://aider.chat/docs/unified-diffs.html), [architect / editor](https://aider.chat/2024/09/26/architect.html); small-model leaderboard figures (secondary): [llm-stats](https://llm-stats.com/benchmarks/aider), [modelfit](https://modelfit.io/tools/aider/)
- [Cursor instant apply](https://cursor.com/blog/instant-apply)
- Continue: [Instant Apply with Relace](https://blog.continue.dev/instant-apply-with-relace), [apply role](https://docs.continue.dev/customize/model-roles/apply); [Morph Fast Apply](https://docs.morphllm.com)
- [Anthropic text editor tool](https://platform.claude.com/docs/en/agents-and-tools/tool-use/text-editor-tool)
- [OpenAI apply_patch discussion](https://community.openai.com/t/responses-api-patches-function-align-your-prompting-with-the-ais-internal-instructions/1372597)
- [Zed Zeta edit prediction](https://zed.dev/blog/edit-prediction)
- [Ollama structured outputs](https://docs.ollama.com/capabilities/structured-outputs); [structured-output issues report](https://www.glukhov.org/post/2025/10/ollama-gpt-oss-structured-output-issues/)
- [Let Me Speak Freely? (arXiv 2408.02442)](https://arxiv.org/abs/2408.02442)
- [Obsidian Smart Composer](https://github.com/glowingjade/obsidian-smart-composer)
