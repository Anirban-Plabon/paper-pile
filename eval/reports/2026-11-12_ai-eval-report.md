# paper-pile AI eval report

**Date:** 2026-11-12 · **Scope:** every AI eval in the repository, with the intent experiment
of P29.16 (2026-11-11 → 2026-11-12) in full detail · **Raw logs:** `eval/results/` ·
**Code state at writing:** `understand.py` = P29.16 v3 (commit `9e5d7a4`)

## Summary

- The project has **two working model evals**: the *intent eval* (does the Ask box understand
  what a typed request means, `tools/ai_eval/intent.py`) and the *edit eval* (does an AI change
  come out right and safe, `tools/ai_eval/run.py`). The *vault-agent eval* is fully specified
  (`docs/PLAN_vault_agent.md` §8) but **not built**, although most vault-agent stages are. The
  plan says "eval first, every stage accepted on eval numbers", so that's the largest gap found.
- The user's bug ("describe …" in the Ask box edited the note on the Antigravity / Gemini
  backend) was reproduced by the intent eval: with the baseline prompt Gemini **edits on 8 of 36
  requests that only ask to be told something** (gemma4: 0 of 36).
- Three prompt versions were tried (P29.16 v2, v3, v4), each judged on held-out cases written
  before it, on up to five models. **None improved every model.** v3 (kept for now) fixes the
  bug class partly for Gemini (wrong edits 8/36 → 4/42), NeoHorse and lfm3, and makes ornith worse.
  v4 showed why: **small models do not decide; they take the first value the schema allows.**
- On the newest balanced held-out set (held-out-6, 16 cases, unseen by every version) the
  **baseline prompt is best or within one case on all four local models.**
- Conclusion: further prompt wording or field order won't make this call reliable on small
  models. The next steps are structural: a smaller understanding call, the harness keeping the
  conversation, buttons that need no model, and an answer as the default when the model is
  unsure (§5.7).

---

## 1. Description of the evals

### 1.1 Inventory

| ID  | Eval                                   | Code                                                                                                                                                   | What it measures                                                                                                                                                                                | Runs a real model?           | Status                                                   |
| --- | -------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------- | -------------------------------------------------------- |
| E1  | **Intent eval**                        | `tools/ai_eval/intent.py`                                                                                                                              | The Ask box's understanding call (`core/ai/understand.py`): for a typed request about selected text, is it a *change*, a *change that leaves a choice open* (the app must ask), or an *answer*? | yes                          | in use since 2026-10-31; 136 cases now                   |
| E2  | **Edit eval**                          | `tools/ai_eval/run.py`, `cases.py`, `checks.py`, `tests/fixtures/ai_edits/`                                                                            | The edit pipeline (`EditRun`): is an AI change correct (right place, nothing else touched, tokens kept, structure kept) and safe (nothing that broke a guard is applied unseen)?                | yes (real mode)              | in use since 2026-10-31; 18 cases (16 real, 2 unit-only) |
| E3  | **Unit-mode evals** (part of `pytest`) | edit cases with scripted replies (`fake.json`); `tests/core/test_vault_safety.py`; `tests/core/test_ai_schemas.py`; `tests/core/test_ai_understand.py` | Pipeline logic with scripted model output, including bad output (preambles, broken JSON, prompt-injection notes); schema rules that backends reject                                             | no (scripted `FakeProvider`) | runs on every commit (1781 tests)                        |
| E4  | **Vault-agent eval**                   | planned at `tools/ai_eval/vault/`                                                                                                                      | Understanding, ambiguity, finding, judging, answering with citations, extract, editing, safety, cost for the chat's vault agent                                                                 | —                            | **specified, not built** (P30.2–P30.7 ⬜)                 |
| E5  | Real-app QA scripts                    | `tools/qa_ai_edit.py`, `qa_vault_chat.py`, `qa_editor.py`, `qa_print.py`; `perf_ui.py`, `mem_soak.py`                                                  | The UI around the AI (proposal display, chips, citations…), editor, printing, speed, memory                                                                                                     | no (scripted fake model)     | in use; not model evals, listed for completeness         |

### 1.2 Why these evals were chosen

**E1, intent.** On 2026-10-31 the user required that the harness *understand* a request
instead of matching first words or phrase lists (CLAUDE.md rule 9: "a misread request is an
example of a class: fix the class"). A rule like that can't be checked by looking at one
screenshot, so it needs:
- many paraphrases per class,
- **held-out sets** written before each prompt version (a set that judged a version is no
  longer unseen; CLAUDE.md gotcha),
- a separate "reported" group for what users actually typed, so a fix can't just fit the
  reported phrasing.

**E2, edits.** P26 ("reliable AI edits", `docs/AI_EDITS.md`) replaced a single rewrite call with
a pipeline: plan, write per block, guards, retries, existing-text checks. Each failure the user
reported then became a fixture case with a property any model must satisfy: headings kept, code
byte-identical, wikilinks kept, insert at the right boundary, an "already there" notice instead of
a duplicate. Properties rather than exact text make the eval model-independent.

**E3, unit mode.** Real-model runs are slow and vary between runs. The unit mode keeps the
scorer, the runner and every *bad-output path* tested on every commit, which a real model rarely
exercises: invented ids, invented JSON, prompt-injection notes.

**E4, vault agent.** The vault agent reads many notes and can propose edits across them. Its
plan makes the eval a precondition ("M0 — Eval foundation (before any agent code)") with hard
safety gates: private leaks 0, injection obeyed 0, invented notes 0.

### 1.3 Impact of each eval

| Eval | What a failure costs the user | Severity | Decisions it has driven |
|---|---|---|---|
| E1 intent | Wrong *change* → the note is edited unasked (an undo, or unnoticed with *Apply at once*). Wrong *answer* → nothing changes, the user retypes. Wrong *ask* → an extra click. Wrong *no-ask* → a guessed tone or language. | **High** (data safety) for wrong changes, low for the rest | P29 prompt v1→v5 (2026-10-31); the multi-model comparison (2026-11-01); P29.16 v2 rejected, v3 kept, v4 rejected (this report) |
| E2 edits | Wrong text, a broken structure, a duplicated item, a lost code block or link; worst case, a broken change applied unseen | **High** | the G1–G10 guards; retries; "already there" notices; the window measured per machine; Antigravity accepted as a backend (14/16, 2026-11-05) |
| E3 unit | A regression reaches the user | High (the earliest catch) | every AI commit |
| E4 vault | Wrong notes found or cited, invented notes, private notes leaked, a note's text obeyed as an instruction | **Highest** (privacy) | none yet: there is no measurement to decide with |

### 1.4 Gaps found while writing this report

1. **E4 is missing although its stages exist.** `vault/understand.py`, `find.py`, `judge.py`,
   `loop.py` and `answer.py` were built without the eval that should accept them. Only scripted
   unit tests (E3) cover them.
2. **E1 covers only the Ask box.** The chat's router (`vault/understand.py`) has no intent eval,
   and the chat's follow-up class (a message that points at the previous answer) isn't measured
   anywhere. Yet that class broke on 2026-11-12: "replace the old selection with it" after an
   answer in the Ask box.
3. **E1 and E2 are single-turn.** Neither has conversation cases, so follow-ups are
   untested.
4. **All real runs are single runs.** No measured variance (§5.6).

---

## 2. Eval datasets

### 2.1 E1: intent dataset

**Shape.** Each case is `(group, selected text, request)`. The model sees the selected text
(up to 1500 characters) and the request, exactly as the Ask box sends them.

**Selected texts (3).** All about one topic (hosting options), all English:

| Name | Text | Kind |
|---|---|---|
| `PARA` | "We compare three options for hosting. Docker runs one container, a VM gives you a whole machine, and bare metal has no layer at all." | prose paragraph |
| `LIST` | "- **Docker**: one container / - **VM**: a whole machine / - **Bare metal**: no layer" | markdown list with bold |
| `TYPOS` | "The backups runs every night and they is stored on the NAS." | sentence with grammar errors |

**Labels (3 groups).**

| Group | Meaning | The right app behaviour |
|---|---|---|
| `change` (C) | the text should end up different, and the request says how (or there is one obvious way) | run the edit at once |
| `change-open` (CO) | a change, but it leaves a choice the user must make (which tone? which language?) | ask, with 3–4 options |
| `answer` (A) | tell or show the user something; the note stays as it is | answer in the box |

**Sets.**

| Set | Cases (C / CO / A) | Written | Purpose | Still unseen? |
|---|---|---|---|---|
| eval (main) | 40 (20 / 8 / 12) | 2026-10-31 | the development set: paraphrases per class | no (tuned on) |
| held-out | 20 (10 / 4 / 6) | 2026-10-31, after the first run | judged P29 v2 | no |
| held-out-2 | 15 (7 / 4 / 4) | 2026-10-31, before P29 v3 "direction" | judged P29 v3 | no |
| held-out-3 | 12 (5 / 4 / 3) | 2026-10-31, before P29 v4 | judged P29 v4–v5 | no |
| held-out-4 | 16 (6 / 0 / 10) | 2026-11-11, **before any P29.16 change** | the reported class: requests to be told something worded as commands ("describe the trade-offs", "outline the argument"), next to commands that write about the same subject into the note ("add a description of each option") | no (judged v2, v3) |
| held-out-5 | 13 (4 / 3 / 6) | 2026-11-11, after v2, before v3 | the same class, new wordings, plus CO | no (judged v3) |
| held-out-6 | 16 (6 / 3 / 7) | 2026-11-12, before v4 | **every group**, so a gain in one class can't hide a loss in another | no (judged v4) |
| reported | 3 (1 / 1 / 1) | user reports | "Elaborate this" (C), "change the tone" (CO), "describe this" (A, 2026-11-11) | not scored in totals |
| **total** | **135 scored + 3 reported** | | | |

**Examples per class** (from held-out sets):
- C: "beef this up", "sort these alphabetically", "now as a haiku", "go into more depth on containers"
- CO: "translate", "use another tone", "lay it out differently", "switch the language"
- A: "is the grammar ok?", "summarise the three options", "describe the audience this targets", "give me the pros and cons of each"

**Labelling policy.**
- A request is an *answer* when its reply would be read next to the text, and a *change* when
  its reply would stand in the text's place.
- A choice is *open* when two or more different results fit and nothing in the request or the
  text settles it.

Labels were written by the same agent that tunes the prompt, and are not reviewed by a second
person (§5.6).

**Labels a reviewer may dispute** (kept as written, flagged here):
- "continue this paragraph" (C): could be CO, since the direction isn't given.
- "rank these by complexity" (A): could be a change (reorder the list).
- "break this down for me" (A): could be a change (make it a list).
- "say more here" / "go deeper on this point" (C): some models reasonably ask which aspect.

### 2.2 E2: edit dataset

One folder per case in `tests/fixtures/ai_edits/`:
- `note.md`, with the selection marked `⟦sel⟧…⟦/sel⟧`;
- `case.json` (command, instruction, `expect` checks, `expect_unit`, `unit_only`, `num_ctx`);
- `fake.json` (scripted replies for unit mode).

| Case | Command / instruction | Checks (all must pass) | Tests |
|---|---|---|---|
| 01 section-body-no-title | rewrite "make it clearer" | headings_unchanged, changed, not_contains | no heading invented for a body-only selection |
| 02 typos | rewrite "fix grammar" | not_contains ×2, change_share_max | typos fixed, ≤ 15 % changed |
| 03 tokens | rewrite "make it more formal" | tokens_kept, changed | `[[a\|b]]`, `![[img]]`, code, math, `#tag`, URL kept |
| 04 new-section | rewrite "add a section about backups" | new_headings, new_heading_next_to | one `##` at a section boundary |
| 05 add-option-everywhere | rewrite "add option D: Fly.io" | count_delta ×2, table_columns_same, contains, regions_min | list +1, table +1 row, intro says "four", ≥ 3 regions |
| 06 already-there | rewrite "add Docker as an option" | unchanged, note_kind | no duplicate; "exists" notice |
| 07 only-the-table | rewrite "add VM where it is missing" | changed_lines_match, count_delta | only the table changes |
| 08 elsewhere | rewrite "add a paragraph about nightly backups" | note_kind | "elsewhere" notice linking the vault note that has it |
| 09 subheading-kept | rewrite "make it clearer" | headings_unchanged, changed | `###` level kept |
| 10 code-identical | rewrite "make it clearer" | fences_identical, changed | code block byte-identical |
| 11 long-rewrite | tone "more formal" (`num_ctx` 2048) | headings_unchanged, regions_min, changed | whole note over the window → per-section regions |
| 12 translate-replace | translate "French" → Replace | contains ×3, changed | code, URLs, link targets unchanged |
| 13 summary-after-list | summarize "one line" | inserted_after, answer_not_contains | inserted after the list as its own block |
| 15 script-kept | rewrite "make it clearer" | script_kept, changed | Bengali stays Bengali |
| 16a messy-reply | rewrite "fix grammar" (unit only) | contains, not_contains ×4 | preamble, fence, `<think>`, closing line removed |
| 16b bad-plan-fallback | rewrite "add a note about costs" (unit only) | contains, changed | invalid plan JSON → fallback |
| 17 add-details | rewrite "Add more details in the description section" | no_error, changed, headings_unchanged, contains | a user-reported failure |
| 18 diagram-to-mermaid | rewrite "turn this diagram into mermaid diagram" | no_error, contains ×3, not_contains, headings_unchanged | a user-reported failure |

Case 14 (single-choice option groups) is a plain unit test (`test_single_choice_groups`).

### 2.3 E4: vault-agent dataset (specified, not built)

From `PLAN_vault_agent.md` §8:
- **Vault:** a synthetic vault of about 250 notes in 10 folders, with a manifest of topics, facts
  and traps. The traps are synonym notes, keyword false friends, near-duplicates, `ai: false` and
  excluded notes holding the best answer, topics with no notes, long notes, prompt-injection
  notes, and mixed languages.
- **Cases:** 10–15 per group, in groups locate, answer, summarise, extract, meta, scoped,
  multi-part, follow-up, compare, edit-one, edit-many, write-new, ambiguous-ask, clear-act, empty,
  injection, no-vault.
- **Splits:** dev, held-out and reported.
- **Private set:** optional, on the user's own vault; never committed.

### 2.4 Dataset limitations

| Limitation | Effect |
|---|---|
| E1 has 3 selected texts on one topic, English only | scores say little about other topics, longer selections or other languages |
| E1 is single-turn | follow-ups ("replace it with that") are not measured, which is the second bug the user found |
| Small sets (12–20 per held-out set) | one case = 5–8 points; differences of 1–2 cases are noise (§5.6) |
| Author = tuner | the labels and the prompt come from the same agent; blind spots are shared |
| E2 has 16 real cases, mostly `ai-rewrite` | answer commands, options and the chat's edits are thinly covered |

---

## 3. Evaluator creation strategies

### 3.1 E1: exact class match, no model judge

The scorer (`intent.verdict`) maps the app's parsed result (`understand.parse`) to a class:
`want == "answer"` gives **A**; a change with `complete` gives **C**; otherwise **CO**. It
compares that class with the label. A missing or unusable reply is **"no answer"** and counts as a fail.

Why this design:
- **The scorer reads what the app acts on.** It scores the parsed `Understood` object, not the
  raw JSON, so the agreement guard of v3/v4 and the "fewer than 2 options → act" rule in `parse`
  are included. The score is the app's behaviour.
- **Deterministic and free.** No model judge: an LLM judge would add its own errors and its own
  model dependence. The labels are categorical, so exact match is enough.
- **Paraphrases, not phrases.** Every case is a new wording of a class, and the rules may not
  contain examples that overlap the eval (CLAUDE.md gotcha). This keeps the eval from rewarding
  phrase lists.
- **Held-out discipline.** A new held-out set is written *before* each version is tried. A set
  that judged a version is marked as used. This produced held-out-4, 5 and 6 in P29.16.
- **The reported group is shown but not scored.** The user's own phrasings show whether the
  report is fixed, but can't inflate the total.

**Derived metrics (new in this report).** The errors have very different costs, so a single
accuracy number hides what matters. From each log:

| Metric | Definition | Cost to the user |
|---|---|---|
| **wrong edit** | A labelled, the model said C | the note changes unasked (**the bug class**) |
| ask on a question | A labelled, the model said CO | a choice is shown for a question; nothing changes |
| missed edit | C or CO labelled, the model said A | the user gets an answer, retypes |
| over-ask | C labelled, the model said CO | an extra click |
| under-ask | CO labelled, the model said C | the model guesses a tone or language |

### 3.2 E2: property checks shared by unit and real mode

`checks.py` defines checks as functions of the outcome (the note after the change is accepted,
the answer text, the notes on the proposal). A run passes when every check of its case passes.
The same checks run in pytest with scripted replies (`expect` + `expect_unit`) and against a real
model (`expect` only). That keeps the scorer itself tested.

Design choices:
- **Properties, not reference text.** "headings unchanged", "code byte-identical", "list +1,
  table +1 row" hold for any good answer from any model, so no golden output is needed.
- **Safety check (`safe`).** A result that broke a guard must never be clean, because it would be
  applied unseen in *Apply at once*.
- **Pass criteria** (AI_EDITS §10): safety 100 %; on one 7–9B model ≥ 80 % of runs for cases
  1–4, 6, 9, 10, 15 and ≥ 60 % for 5, 7, 8. A prompt change that drops a case by more than 10
  points must be reverted or explained.

### 3.3 E4: planned per-stage metrics

Stage-wise scoring with oracle inputs, so that a failure is pinned to one stage:
- understanding: exact or partial steps;
- ambiguity: ask precision and recall;
- finding: recall of `must` notes, precision;
- judging: accuracy;
- answering: fact coverage, citation correctness, invented notes;
- extract: row recall and precision;
- editing: right note and section, nothing else touched;
- safety: hard gates at 0;
- cost: calls, tokens, seconds.

### 3.4 Known weaknesses of the evaluators

- **The CO/C boundary is strict.** A reasonable "which aspect?" on "say more here" is a fail.
- **Single label per case.** No partial credit, no "either is fine" label.
- **No confidence.** The models give none, so calibration can't be studied.
- **No variance.** One run per case (see §4.4).

---

## 4. Experiment settings

### 4.1 Models

| Model | Backend | Size on disk | Role in the evals |
|---|---|---|---|
| `gemma4:12b` | Ollama | 7.6 GB | the reference model; the prompts were first tuned on it |
| `gemini-3.8-flash-medium` | Antigravity CLI (`agy`), cloud | — | **the user's own backend**; the reported bug came from it |
| `NeoHorse-1:9B` | Ollama | 5.6 GB | 9B class |
| `ornith-1.5:9b` | Ollama | 6.6 GB | 9B class |
| `lfm3:latest` | Ollama | 1.1 GB | smallest class; same scores as `lfm3:1.7b` of 2026-11-01, so most likely the same model |
| not used | Ollama | `Nanbeige4.3-33B` (21 GB), `Qwen3.8:27B-Q2` (8.2 GB) | too large for the 8 GB GPU to compare at speed |

### 4.2 Hardware and software

- Intel Core i9-14900HX (32 threads), 30 GB RAM, NVIDIA GeForce RTX 5070 Laptop GPU (8 GB,
  driver 595.99.02). gemma4:12b (7.6 GB) is close to the GPU's memory, so part of it may run on
  the CPU; this shows in its latency.
- Ollama 0.40.13. Antigravity: the app's fenced setup (own `HOME`, an app-written agent with no
  tools except `finish` for JSON, `toolPermission: strict`, warm process pool; PLAN §4.30).
- Python 3.12, the app's own code paths (`AiEngine.ask_json`).

### 4.3 Call settings (as the app sends them)

| Setting | E1 intent | E2 edits |
|---|---|---|
| Call | `ask_json(messages, SCHEMA, max_answer=300)` | `EditRun` pipeline (plan JSON, write calls, retries) |
| Constrained JSON | yes: the schema goes to the backend | plan: yes; writes: text |
| Temperature | 0 | ≤ 0.3 |
| Thinking | off (`think=False`; `reasoning_effort: none` on OpenAI-compatible servers) | off |
| Input | system rules + "Selected text: <<<…>>> Request: …" (selection ≤ 1500 chars) | note, selection, outline, related blocks |
| Context window | the model's measured window (`core/ai/window.py`) | same; case 11 forces 2048 |
| Isolation | fresh temp vault, config and access grant per run; user settings never read | same |

### 4.4 Protocol

1. **One run per case** (`--runs 1`), sequential, one model at a time. Local models never ran
   in parallel with each other. One Ollama run overlapped an Antigravity run (different
   machines do the work).
2. **Baseline first.** The current prompt was measured on gemma4 and Gemini before any change.
3. **Held-out before a version.** held-out-4 before v2, held-out-5 before v3, held-out-6
   before v4.
4. **Cheap model first, then the slow backend.** A version that failed on gemma4 or the local
   models wasn't sent to Antigravity (about 1.5 h per full run): v2's Gemini run was stopped,
   and v4 was never run there.
5. **Baselines for new sets.** The old rules were re-run on held-out-5 and held-out-6 alone,
   from a saved copy of the old `understand.py` loaded by a scratch script. That script isn't
   committed; the logs are.

### 4.5 Prompt versions

The P29 versions of 2026-10-31 and the P29.16 versions of 2026-11-11/12 share numbers. This
report uses the P29.16 names; "v1 (old)" is the P29 v5 prompt.

| Name here | Date | What changed | Outcome |
|---|---|---|---|
| P29 v1–v4 | 2026-10-31 | first understanding prompts (bool complete; reworded; "direction"; list results then "must choose") | replaced; see Decision log 2026-10-31 |
| **v1 (old)** = P29 v5 | 2026-10-31 | yes/no "complete", options only when it asks; `want` enum `[change, answer]` first | the baseline of P29.16 |
| v2 | 2026-11-11 | a `result` field before `want` that listed kinds of change; "when either reading fits, it is information" | **rejected** (gemma4 worse) |
| **v3** | 2026-11-11 | a neutral `result` field (`the_text_itself` first) decided before `want`; the over-broad sentence narrowed; "also when worded as a command"; Python: a change needs `result` and `want` to agree; the rule "want = change exactly when result = the text itself" | **kept for now** (committed) |
| v4 | 2026-11-12 | v3 with the safe value first in both enums and the tie between the fields removed | **rejected** (small models flip) |

### 4.6 Timeline

| When | Experiment | Duration |
|---|---|---|
| 11-11 | v1 baseline: gemma4 (all sets) · Gemini (all sets) | 6.7 min · 57 min |
| 11-11 | v2: gemma4 · Gemini (stopped after 11 cases) | 6.6 min · — |
| 11-11 | v3: gemma4 · v1 on held-out-5 (gemma4) · v3 on Gemini | 8.5 min · 1 min · 83 min |
| 11-12 | v1 on held-out-5 (Gemini) | ~12 min |
| 11-12 | ornith: v3 · v1 | 3.8 · 4.1 min |
| 11-12 | lfm3 (v3, v1) · NeoHorse (v3, v1) | 1.5 + 1.1 · 3.5 + 3.6 min |
| 11-12 | v4 on four local models + v1 and v3 on held-out-6 | ~35 min |

A first lfm3 run used the tag `lfm3:1.7b`, which isn't installed (0/40 in 0 s, "no answer").
It was discarded and re-run as `lfm3:latest`.

---

## 5. Eval report

### 5.1 Baselines before this experiment (from TRACKER)

**E2, edits (16 real cases × 3 runs = 48):**

| Model | Passed | Time | Notes |
|---|---|---|---|
| gemma4:12b | 45/48 | 287 s | 06-already-there 0/3 (re-adds Docker; the warning shows it, never applied unseen) |
| NeoHorse-1:9B | 40/48 | 177 s | asks "which result?" on clear requests |
| ornith-1.5:9b | 36/48 | 136 s | the same, more often |
| lfm3:1.7b | 16/48 | 145 s | too weak for edits with these prompts |
| gemini-3.8-flash-low (agy, 1 run) | 14/16 | 239 s | failed 06 (`note_kind`), 17 (`changed`) |

**E1, intent (P29 v5 = "v1 old"; held-out = the first three held-out sets, 47 cases):**

| Model | eval /40 | held-out /47 | Median s / request |
|---|---|---|---|
| gemma4:12b | 38 | 44 | 2.6 |
| NeoHorse-1:9B | 34 | 39 | 1.2 |
| ornith-1.5:9b | 29 | 29 | 1.9 |
| lfm3:1.7b | 16 | 21 | 0.4 |
| gemini-3.8-flash-low (agy) | 38 | 47 | 8.1 |

### 5.2 The reported bug, reproduced

With v1 (old), on held-out-4, the set written for the reported class before any change:

| Model | held-out-4 | Requests to be told something that edited the note |
|---|---|---|
| gemma4:12b | 16/16 | 0 of 10 |
| Gemini 3.8 flash (agy) | **9/16** | **7 of 10**: "describe the trade-offs", "outline the argument", "compare the first two", "list the claims made here", "describe what a VM is", "characterize each option", and "break this down for me" (asked for a choice) |

The reported "describe this" was also edited by Gemini (reported 2/3). The root cause is in the
v1 rule text: *"an instruction to do something with it or to write more about its subject is a
change, even when it is one word."* Gemini applied it to every command, including commands that
ask to be told something; gemma4 didn't.

### 5.3 Results per set: all models, all versions

Scores are cases passed. "—" = not run. v1 on held-out-5 and held-out-6 was run separately (§4.4).

**gemma4:12b**

| Set | v1 | v2 | v3 | v4 |
|---|---|---|---|---|
| eval /40 | 38 | 35 | 38 | 37 |
| held-out /20 | 18 | 16 | 17 | 18 |
| held-out-2 /15 | 14 | 12 | 13 | 14 |
| held-out-3 /12 | 12 | 11 | 12 | 10 |
| held-out-4 /16 | 16 | 16 | 16 | 16 |
| held-out-5 /13 | 11 | — | 10 | 11 |
| held-out-6 /16 | 14 | — | 13 | 14 |
| reported /3 | 3 | 3 | 3 | 3 |

**Gemini 3.8 flash medium (Antigravity)**

| Set | v1 | v3 |
|---|---|---|
| eval /40 | 37 | 38 |
| held-out /20 | 18 | 18 |
| held-out-2 /15 | 15 | 15 |
| held-out-3 /12 | 12 | 12 |
| held-out-4 /16 | 9 | 11 |
| held-out-5 /13 | 10 | 11 |
| reported /3 | 2 | 3 |

**NeoHorse-1:9B · ornith-1.5:9b · lfm3:latest**

| Set | Neo v1 | Neo v3 | Neo v4 | orn v1 | orn v3 | orn v4 | lfm v1 | lfm v3 | lfm v4 |
|---|---|---|---|---|---|---|---|---|---|
| eval /40 | 32 | 31 | 21 | 28 | 25 | 27 | 16 | 24 | 12 |
| held-out /20 | 16 | 15 | 10 | 13 | 10 | 13 | 8 | 12 | 6 |
| held-out-2 /15 | 13 | 10 | 6 | 8 | 10 | 12 | 6 | 10 | 4 |
| held-out-3 /12 | 11 | 6 | 8 | 9 | 8 | 6 | 7 | 8 | 3 |
| held-out-4 /16 | 7 | 13 | 12 | 10 | 4 | 6 | 5 | 8 | 10 |
| held-out-5 /13 | 9 | 8 | 7 | 6 | 5 | 4 | 6 | 9 | 6 |
| held-out-6 /16 | 14 | 12 | 10 | 11 | 8 | 11 | 8 | 9 | 7 |
| reported /3 | 2 | 1 | 2 | 1 | 2 | 1 | 2 | 3 | 1 |

### 5.4 Error types: what the models get wrong

Pooled over every set in each log. Logs of different versions hold different numbers of cases
(sets were added over time), so compare the rates rather than the counts. For v1 on gemma4 and
Gemini, held-out-5 and held-out-6 aren't included.

| Model · version | Correct | **Wrong edit** (A→C) | Ask on a question (A→CO) | Missed edit (C/CO→A) | Over-ask (C→CO) | Under-ask (CO→C) | Median s | Max s |
|---|---|---|---|---|---|---|---|---|
| gemma4 · v1 | 101/106 | **0/36** | 0/36 | 1/70 | 1/49 | 3/21 | 2.8 | 68 |
| gemma4 · v2 | 93/106 | 1/36 | 0/36 | 2/70 | 0/49 | 10/21 | 3.3 | 22 |
| gemma4 · v3 | 109/119 | 1/42 | 0/42 | 1/77 | 0/53 | 8/24 | 4.3 | 23 |
| gemma4 · v4 | 123/135 | 0/49 | 0/49 | 1/86 | 0/59 | 11/27 | 3.4 | 27 |
| Gemini · v1 | 93/106 | **8/36** | 1/36 | 0/70 | 4/49 | 0/21 | 21.1 | 230 |
| Gemini · v3 | 108/119 | **4/42** | 2/42 | 0/77 | 4/53 | 0/24 | 26.0 | 235 |
| NeoHorse · v1 | 90/119 | 7/42 | 5/42 | 0/77 | 13/53 | 4/24 | 1.2 | 19 |
| NeoHorse · v3 | 84/119 | 6/42 | 3/42 | 3/77 | 5/53 | **18/24** | 1.4 | 20 |
| NeoHorse · v4 | 76/135 | 2/49 | 0/49 | **44/86** | 0/59 | 13/27 | 1.4 | 18 |
| ornith · v1 | 75/119 | 3/42 | 10/42 | 1/77 | **26/53** | 4/24 | 1.9 | 16 |
| ornith · v3 | 64/119 | **14/42** | 10/42 | 0/77 | 14/53 | 17/24 | 1.5 | 32 |
| ornith · v4 | 80/135 | 12/49 | 6/49 | 11/86 | 12/59 | 14/27 | 1.4 | 17 |
| lfm3 · v1 | 50/119 | **26/42** | 13/42 | 0/77 | 17/53 | 13/24 | 0.4 | 11 |
| lfm3 · v3 | 74/119 | 6/42 | 6/42 | 2/77 | 27/53 | 4/24 | 0.6 | 16 |
| lfm3 · v4 | 49/135 | 0/49 | 0/49 | **86/86** | 0/59 | 0/27 | 0.7 | 15 |

Gemini's v3 log also has one "no answer": the CLI returned nothing after 95 s.

### 5.5 Findings

**F1. Small models take the first value the schema allows.** This is the clearest result of the
experiment.
- In v3 the `result` enum began with `the_text_itself`. A raw JSON probe showed ornith answering
  `the_text_itself` for *every* request, even "is this too long?". Its wrong edits rose 3/42 →
  14/42.
- In v4 `answer` came first. lfm3 then answered **every** request (86/86 missed edits, not even
  "fix the typos"), and NeoHorse missed 44/86 edits.

The enum order doesn't help these models decide; it only chooses which way they fail.

**F2. Prompt changes move the errors instead of removing them.** This was seen already on
2026-10-31 (TRACKER Issues log) and again here:
- v2 fixed nothing new for gemma4 and raised under-asking 3 → 10 of 21: listing kinds of change
  told the model they were obvious.
- v3 cut NeoHorse's over-asking (13 → 5 of 53) but raised its under-asking (4 → 18 of 24).

**F3. Gemini over-edits; gemma4 doesn't.** On the same prompt Gemini edited 8 of 36 requests
that only asked to be told something, and gemma4 none. v3 halves Gemini's rate (4/42) without
any loss on Gemini's other sets. The remaining misses are "describe the trade-offs", "outline the
argument", "characterize each option" and "detail the reasoning behind this". Gemini runs inside
a coding-agent CLI; whether that harness's own framing adds to the "act on it" bias is untested
(it could be checked by running Gemini through a plain API).

**F4. The v3 agreement guard was defeated by its own rule.** v3 meant `result` and `want` to be
two independent votes, with a change only when both agree. But the rule "want: change exactly
when result is the text itself" made the model copy one into the other, so for ornith the guard
never fired. v4 removed the tie, and then F1 dominated.

**F5. On fresh, balanced cases the old prompt is best locally.** held-out-6 (all three groups,
unseen by every version):

| Model | v1 | v3 | v4 |
|---|---|---|---|
| gemma4:12b | **14** | 13 | **14** |
| ornith-1.5:9b | **11** | 8 | **11** |
| NeoHorse-1:9B | **14** | 12 | 10 |
| lfm3:latest | 8 | **9** | 7 |

v3's gains are concentrated on the class it targeted (held-out-4). On a balanced set they're
outweighed by losses in the other classes for three of the four local models.

**F6. Model size matters more than wording.** Across versions, gemma4 stays at 88–95 % correct
on every set. The 9B models move between 54 % and 76 % and lfm3 between 36 % and 62 %, depending
on wording. That matches the user's observation: *"for the small models this is a huge task."*
One reply decides nine fields: `result`, `want`, `complete`, `question`, `options`, `reach`,
`size`, `adds`, `new_form`. Only the first five concern what the user meant.

**F7. Antigravity's latency.** Median 21–26 s per understanding call (max 230 s), against
0.4–4.3 s locally; 8.1 s with the `low` effort model on 2026-11-05. A full intent run takes
57–83 minutes on Antigravity. This limits how often the user's own backend can be evaluated,
and every extra model call in the product would cost about the same.

**F8. Stable baselines.** lfm3:latest with v1 scored 16/40 on the main eval, the same as
lfm3:1.7b on 2026-11-01. gemma4 with v1 scored 38/40 again (as on 2026-10-31). So between days
the single-run results are reproducible at the level of the totals.

### 5.6 Threats to validity

| Threat | Effect on the conclusions | Mitigation used / needed |
|---|---|---|
| **Single runs** | at temperature 0 the local models are near-deterministic, but Gemini isn't, and per-case flips happen (e.g. gemma4 "elaborate on the VM option" passed in v1, failed in v3) | ±1 case is treated as noise throughout; **needed: `--runs 3` for decisions** |
| **Small sets** | 1 case = 6–8 points on a held-out set | conclusions rely on patterns across sets and models, not one cell |
| **Held-out sets reused** | held-out-4 judged v2 and v3; held-out-5 judged v3 | each set's use is recorded; held-out-6 was fresh for v4; held-out-7 is needed before the next version |
| **Labels by the tuner** | shared blind spots; some labels disputed (§2.1) | flagged; **needed: a second reviewer (the user)** |
| **One topic, one language, 3 texts** | generalisation to real notes unknown | needed: more texts (long, technical, non-English) |
| **Old rules from a scratch copy** | the baseline for held-out-5 and held-out-6 used a saved copy of `understand.py`, run by an uncommitted script | the copy was the committed v1 text; logs are kept |
| **gemma4 near the GPU memory limit** | its latency includes CPU offload; accuracy unaffected | latency of gemma4 not used for decisions |

### 5.7 Decisions and recommendations

**Decisions taken:**
- v2 rejected; v4 rejected; v3 kept for now (Decision log 2026-11-12). That leaves Gemini better
  on the bug class and ornith/NeoHorse worse on balanced cases, a trade-off still open.
- The single understanding call stays. The old binary edit/answer router won't come back (user,
  2026-11-12).

**Recommended next steps, in order:**
1. **Harness, not prompt.** These steps work the same on every backend and need no model call:
   - Replace / Insert below / Copy under every Ask box answer (today only under Translate).
   - The Ask box keeps its conversation: a change typed after an answer gets that answer as
     material. Today the understanding call and the edit see neither, so "replace the old
     selection with it" fails.
   - When the model is unsure, it answers. An answer can still be pushed into the note.
2. **A smaller understanding call.** Only what the user meant (`want`, `complete`, `question`,
   `options`); move `reach`, `size`, `adds` and `new_form` to the edit's own planning, after
   checking that the plan can derive them. Write held-out-7 first. Accept the version only if it
   doesn't lose on any of the five models beyond ±1 per set, with `--runs 3`.
3. **Extend E1:**
   - follow-up cases, with a previous answer in the conversation;
   - more selected texts (long, technical, non-English);
   - a label review by the user;
   - a wrong-edit rate reported next to accuracy for every model.
4. **Build E4** (P30.2–P30.7) before more vault-agent work, as its plan requires. Include the
   chat router's intent cases there.
5. **Check the agy framing (F3).** Run the same intent cases on Gemini through a plain API to
   see whether the coding-agent harness adds the bias.

---

## Appendix A: files

| File(s) | Contents |
|---|---|
| `eval/results/README.md` | short tables per experiment |
| `eval/results/2026-11-11_intent_v1-old_*` | baseline, all sets but held-out-5 and -6: gemma4, Gemini |
| `eval/results/2026-11-11_intent_v2-rejected_*` | v2: gemma4; Gemini partial (stopped) |
| `eval/results/2026-11-11_intent_v3-kept_*` | v3: gemma4, Gemini |
| `eval/results/2026-11-12_intent_v1-old_held-out-5_*` | baseline on held-out-5: gemma4, Gemini |
| `eval/results/2026-11-12_intent_v1-old_{ornith,NeoHorse,lfm3}*` | baseline, all sets |
| `eval/results/2026-11-12_intent_v3-kept_{ornith,NeoHorse,lfm3}*` | v3, all sets |
| `eval/results/2026-11-12_intent_v{1-old,3-kept}_held-out-6_*` | baselines on held-out-6, four local models |
| `eval/results/2026-11-12_intent_v4-rejected_*` | v4, all sets, four local models |

## Appendix B: how to reproduce

```bash
# intent eval (current understand.py), one model
uv run python tools/ai_eval/intent.py --model gemma4:12b [--runs 3]
uv run python tools/ai_eval/intent.py --model gemini-3.8-flash-medium --provider antigravity

# edit eval
uv run python tools/ai_eval/run.py --model gemma4:12b --runs 3 [--case 05]

# unit mode (no model)
uv run pytest -q
```

An older prompt version is reproduced by checking out its commit: v3 = `b2e7ecc`; v1 = the
parent of `b2e7ecc`. v2 and v4 were never committed; their text is described in §4.5 and in the
TRACKER Decision log.
