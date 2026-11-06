# paper-pile — Tracker: the vault agent (P30)

> Live status for `docs/PLAN_vault_agent.md`. Same update protocol as `docs/TRACKER.md`
> (CLAUDE.md): update after every task, error or requirement change; never delete log
> entries. Main `TRACKER.md` keeps a one-line pointer in Current focus.

Legend: 🧠 = needs Opus · ⬜ todo · 🔄 in progress · ✅ done · ⛔ blocked · ⏭️ skipped/deferred

## Current focus
- **Milestone:** M1 — Vault tools and index: done (P30.8–P30.12, 2026-11-06). M0 (eval) comes
  later: user 2026-11-06, "start implementing … do not run eval or large scale test yet"
- **M2 — Understanding:** built and hand-checked on gemma4 (P30.13–P30.15 🔄: accepted only on
  eval numbers, and the eval is not run yet)
- **M3 — Find and judge:** built (P30.18–P30.19 ✅; P30.16–P30.17 🔄 until the eval)
- **Next task:** M4 — read actions on the found notes (P30.20 locate … P30.24 hints)
- **Waiting on the user:** open questions (PLAN_vault_agent §11) — languages in the test
  vault, background note cards, budgets, model-made hints. Defaults are in §10.

## Open issues
- (none)

## Eval scoreboard
<!-- one row per run that matters: date · version · model · split · key numbers · time/case -->
| Date | Version | Model | Split | Understand | Ask P/R | Find recall (must) | Precision | Facts | Edits | Safety (leaks / injection / invented) | s/case |
|---|---|---|---|---|---|---|---|---|---|---|---|
| — | baseline `@vault` (P30.6) | — | — | — | — | — | — | — | — | — | — |

## Task status

### M0 — Eval foundation
| ID | Task | Status | Notes |
|---|---|---|---|
| P30.1 | Plan + tracker + pointers | ✅ | 2026-11-06 |
| P30.2 🧠 | Test vault fixture + manifest | ⬜ | |
| P30.3 🧠 | Cases v1 (dev split) | ⬜ | |
| P30.4 | Scorer | ⬜ | |
| P30.5 | Runner | ⬜ | |
| P30.6 | Baseline: today's `@vault` | ⬜ | sets the M2–M6 targets |
| P30.7 | Held-out split v1 | ⬜ | before any M2 prompt |

### M1 — Vault tools and index
| ID | Task | Status | Notes |
|---|---|---|---|
| P30.8 | Index schema 5: headings, note dates, words, private | ✅ | 2026-11-06 · `headings`, `note_dates` tables; `words`, `private` columns; `tag_pairs`, `link_stats`; schema 4 DBs rebuilt (8 tests) |
| P30.9 | Scope resolver | ✅ | 2026-11-06 · `vault/scope.py` + `vault/dates.py`: folders / tags / dates / names / links; ambiguity + missing reported; private never named (37 tests) |
| P30.10 | Tools (read side) | ✅ | 2026-11-06 · `vault/tools.py`: list, in_scope, by_date, by_tag, links, search (multi-term), outline, read (section, cap); every tool checked on private notes |
| P30.11 | `meta` queries | ✅ | 2026-11-06 · `vault/meta.py`: count, folders, recent, no_links, largest, untagged, tags; no model call; private not counted |
| P30.12 | Result set + compact results | ✅ | 2026-11-06 · `vault/results.py`: numbered pick (all / yes / maybe / numbers / paths), rename / remove, compact text, JSON (16 tests with P30.10–11) |

### M2 — Understanding
| ID | Task | Status | Notes |
|---|---|---|---|
| P30.13 🧠 | Vault understanding prompt + parser | 🔄 | 2026-11-06 · built (`vault/understand.py`), hand-checked on gemma4:12b (`tools/vault_try.py`, ~5–13 s per request warm); acceptance waits for the eval (M0) |
| P30.14 🧠 | Ambiguity rules | 🔄 | 2026-11-06 · model's open choice + `vault/plan.py` name / folder ambiguity → one question with options, `choose()` re-resolves; missing names → notices; eval pending |
| P30.15 | Multi-part split + dependencies | 🔄 | 2026-11-06 · steps + `depends_on` parsed and planned (`after`); gemma4 splits "list X, then add Y" into extract → edit; eval pending |

### M3 — Find and judge
| ID | Task | Status | Notes |
|---|---|---|---|
| P30.16 | Term widening + multi-source candidates | 🔄 | 2026-11-06 · `candidates.py` (search, tags, cards, link neighbours, scope, cap) + `expand.py` second round from the kept notes; hand-checked; eval pending |
| P30.17 🧠 | Judge | 🔄 | 2026-11-06 · `judge.py`: 10 cards per call, yes / maybe / no + reason, unjudged → maybe; card summary shown; hand-checked (both false friends dropped); eval pending |
| P30.18 | Note cards cache | ✅ | 2026-11-06 · `cards.py`: `cards.db` by content hash, rebuildable, stale / private never used, lazy `CardMaker`, card search + summaries for the gatherer (7 tests) |
| P30.19 | Budgets + big-job confirm | ✅ | 2026-11-06 · `find.py` `Budgets`, `capped`, `big_job()` question; `find_notes` runs one step's find stage with progress (7 tests) |

### M4 — Read actions
| ID | Task | Status | Notes |
|---|---|---|---|
| P30.20 | `locate` | ⬜ | |
| P30.21 | `answer` with citations | ⬜ | |
| P30.22 | `summarise` map-reduce | ⬜ | |
| P30.23 | `extract` tables | ⬜ | |
| P30.24 | Empty results + hints | ⬜ | |

### M5 — Agent loop
| ID | Task | Status | Notes |
|---|---|---|---|
| P30.25 🧠 | JSON-action loop + budgets + Stop | ⬜ | |
| P30.26 | Fast-path / loop routing | ⬜ | |
| P30.27 | Plan card | ⬜ | |
| P30.28 | Vault memory file | ⬜ | |

### M6 — Edits across notes
| ID | Task | Status | Notes |
|---|---|---|---|
| P30.29 🧠 | `propose_edit` over the edit pipeline | ⬜ | |
| P30.30 | Dry run + review list | ⬜ | |
| P30.31 | Checkpoint + Undo (N notes) | ⬜ | |
| P30.32 | `write` a new note | ⬜ | |
| P30.33 | Disk-conflict handling | ⬜ | |

### M7 — UI
| ID | Task | Status | Notes |
|---|---|---|---|
| P30.34 | Step card | ⬜ | |
| P30.35 | Result blocks | ⬜ | |
| P30.36 | Chips | ⬜ | |

### M8 — Safety and release
| ID | Task | Status | Notes |
|---|---|---|---|
| P30.37 | Injection + privacy hardening | ⬜ | |
| P30.38 | Manual QA + user's real-model pass | ⬜ | |

### M9 — Later
| ID | Task | Status | Notes |
|---|---|---|---|
| P30.39 | Ask the vault from the Ask box | ⬜ | |
| P30.40 | Embeddings experiment | ⬜ | only on a measured recall gap |
| P30.41 | Saved searches | ⬜ | |
| P30.42 | Suggested links | ⬜ | |

### MC — Citations (can start after M1)
| ID | Task | Status | Notes |
|---|---|---|---|
| P30.43 | Source labels + label → location map | ⬜ | |
| P30.44 | Citation check | ⬜ | |
| P30.45 | Pills + numbered Sources + preview card | ⬜ | |
| P30.46 | Click → open, flash, band; Ctrl+click → split | ⬜ | |
| P30.47 | Re-find after edits; rename / delete / private | ⬜ | |
| P30.48 | Saved in chats + Insert as section wikilinks | ⬜ | |

## Decision log
| Date | Decision | Reason | By |
|---|---|---|---|
| 2026-11-06 | Vault agent as its own plan + tracker (P30); eval first, each stage accepted on eval numbers | User: text-to-note search ("where are the social business notes, summarise all of them"), many question types, folder scopes, edits across notes, multi-part questions, hints, ambiguity; "we may need a new eval" | user |
| 2026-11-06 | Coding-agent ideas adopted: read-only tool set + JSON-action loop, plan card, diff-only writes with permission, checkpoints via version history, vault memory file, per-note sub-calls, result compaction, `note § heading` citations | User asked for suggestions "related to coding agent as well" | claude |
| 2026-11-06 | Defaults until the user decides: vectorless retrieval; automatic trigger with `@` forcing; multi-note edits always diffs; synthetic fixture + optional private set | Open questions not yet answered; the plan names them (§10, §11) | claude |
| 2026-11-06 | Actions as JSON in plain chat answers, not native tool calling | Rule #7: must work on every backend (the Antigravity CLI and many OpenAI-compatible servers have no tool calling) | claude |
| 2026-11-06 | Planned change to PLAN §8 "No tools or agents": replaced by read-only, scope-checked tools + diff-only writes + injection eval gate, applied when P30.37 lands | Tools are needed for vault-wide work; the defence moves from "no tools" to "no writing tools" | claude |
| 2026-11-06 | Citations added to the plan (§7.1, milestone MC, P30.43–P30.48): model cites short labels that Python maps to note § lines (never paths), every citation checked, pills + hover card, click opens + flash + band, Ctrl+click split, re-found after edits, saved in chats, section wikilinks on insert; one system for chat, `@vault`, agent and v2 PDFs | User asked how note citations open and highlight sections; nothing was planned beyond "cited note § heading" | user |
| 2026-11-06 | M1 (tools, no model) built before M0 (eval); the eval gets built but is not run until the user asks | User: "start implementing on new plan. do not run eval or large scale test yet" | user |
| 2026-11-06 | gemma4 is the development model for the prompt work (M2 on); other models come with the eval | User: "use gemma4 as llm first" | user |
| 2026-11-06 | Daily-note dates computed at query time from path + settings, not stored in the index | The index stays independent of settings; a daily-format change needs no rebuild | claude |
| 2026-11-06 | Index `private` column (front matter `ai: false`) and `words`; `tag_pairs` instead of a tag count so callers count only readable notes | Listings and meta must never read note texts nor count private notes | claude |
| 2026-11-06 | Note names: a full path with extension is exact; a bare name never counts as an exact path ("pricing" with `Pricing.md` and `Clients/Pricing.md` is ambiguous); on equal search hits the more specific section wins | Found by tests: a root note silently won over a same-named note in a folder; the `#` title section always beat the `##` that held the words | claude |
| 2026-11-06 | Understanding schema: every step field required, target fields before topic / terms; meta queries described one by one ("how many" takes the list that matches what is counted); `from_result` dropped when no last result was shown or the step depends on an earlier one; meta kept only on meta steps | gemma4 hand check: optional target fields were never filled (folder, "last week" ignored); "how many notes have no tags" → `count`; `from_result: "-1"` / `"all"` with no earlier answer | claude |
| 2026-11-06 | A folder name written with `/` is matched only against whole paths of the same depth | A missing `Clients/x` was silently read as `Clients` by the close-spelling rule (a wider scope than asked) | claude |
| 2026-11-06 | Not fixed by prompt: gemma4 reads "social business" as social media (its own knowledge) | No word lists (CLAUDE.md); wrong candidates are the judge's to drop (P30.17), and the eval will measure it | claude |
| 2026-11-06 | Understanding rule: a target field only when the message limits the notes that way; a topic alone gives no folder / tag | gemma4 narrowed "where are my social business notes" to the Marketing folder + #marketing on its own, hiding every on-topic note | claude |
| 2026-11-06 | Second search round from the notes judged "yes" (`expand.py`), not a better first prompt | The model's first idea of a topic can be wrong; the user's confirmed notes are better evidence of what their notes call it, and it needs no word lists | claude |
| 2026-11-06 | The judge sees the note card's summary; a note about one case / application of the subject is "yes" | gemma4 rejected the village-solar social enterprise as "a specific product idea rather than general notes" when it saw only the note's first lines | claude |
| 2026-11-06 | Cards made lazily per request for now; background making stays open (§11.2) | ~7.5 s per note on gemma4:12b here: a whole vault is a long job to start without the user's choice | claude |

## Issues log
| Date | Task | Symptom | Root cause | Fix | Gotcha? |
|---|---|---|---|---|---|
| 2026-11-06 | P30.13 | gemma4 never filled a step's folders / dates although the message named them | The fields were optional in the JSON schema; with schema-constrained output the model skips optional properties | Every field required (empty values allowed), target fields ordered before topic / terms | y |

## Session log
- 2026-11-06 · P30.1 plan + tracker written (no code)
- 2026-11-06 · Citations section + MC tasks added to the plan (docs only)
- 2026-11-06 · P30.8–P30.12 vault tools and index (M1) · 1604 tests (+61), ruff + mypy clean
- 2026-11-06 · P30.13–P30.15 understanding + plan built, hand-checked on gemma4:12b (9 requests) · 1625 tests (+21)
- 2026-11-06 · P30.16–P30.19 candidates, judge, second round, note cards, budgets (M3); hand check on a 9-note trap vault: 5/5 on-topic found (4 yes + 1 maybe), 0 false friends · 1647 tests (+22)
