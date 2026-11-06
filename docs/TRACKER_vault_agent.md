# paper-pile — Tracker: the vault agent (P30)

> Live status for `docs/PLAN_vault_agent.md`. Same update protocol as `docs/TRACKER.md`
> (CLAUDE.md): update after every task, error or requirement change; never delete log
> entries. Main `TRACKER.md` keeps a one-line pointer in Current focus.

Legend: 🧠 = needs Opus · ⬜ todo · 🔄 in progress · ✅ done · ⛔ blocked · ⏭️ skipped/deferred

## Current focus
- **Milestone:** M0 — Eval foundation
- **Next task:** P30.2 — test vault fixture + manifest
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
| P30.8 | Index schema 5: headings, note dates | ⬜ | |
| P30.9 | Scope resolver | ⬜ | |
| P30.10 | Tools (read side) | ⬜ | |
| P30.11 | `meta` queries | ⬜ | |
| P30.12 | Result set + compact results | ⬜ | |

### M2 — Understanding
| ID | Task | Status | Notes |
|---|---|---|---|
| P30.13 🧠 | Vault understanding prompt + parser | ⬜ | |
| P30.14 🧠 | Ambiguity rules | ⬜ | |
| P30.15 | Multi-part split + dependencies | ⬜ | |

### M3 — Find and judge
| ID | Task | Status | Notes |
|---|---|---|---|
| P30.16 | Term widening + multi-source candidates | ⬜ | |
| P30.17 🧠 | Judge | ⬜ | |
| P30.18 | Note cards cache | ⬜ | |
| P30.19 | Budgets + big-job confirm | ⬜ | |

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

## Decision log
| Date | Decision | Reason | By |
|---|---|---|---|
| 2026-11-06 | Vault agent as its own plan + tracker (P30); eval first, each stage accepted on eval numbers | User: text-to-note search ("where are the social business notes, summarise all of them"), many question types, folder scopes, edits across notes, multi-part questions, hints, ambiguity; "we may need a new eval" | user |
| 2026-11-06 | Coding-agent ideas adopted: read-only tool set + JSON-action loop, plan card, diff-only writes with permission, checkpoints via version history, vault memory file, per-note sub-calls, result compaction, `note § heading` citations | User asked for suggestions "related to coding agent as well" | claude |
| 2026-11-06 | Defaults until the user decides: vectorless retrieval; automatic trigger with `@` forcing; multi-note edits always diffs; synthetic fixture + optional private set | Open questions not yet answered; the plan names them (§10, §11) | claude |
| 2026-11-06 | Actions as JSON in plain chat answers, not native tool calling | Rule #7: must work on every backend (the Antigravity CLI and many OpenAI-compatible servers have no tool calling) | claude |
| 2026-11-06 | Planned change to PLAN §8 "No tools or agents": replaced by read-only, scope-checked tools + diff-only writes + injection eval gate, applied when P30.37 lands | Tools are needed for vault-wide work; the defence moves from "no tools" to "no writing tools" | claude |

## Issues log
| Date | Task | Symptom | Root cause | Fix | Gotcha? |
|---|---|---|---|---|---|

## Session log
- 2026-11-06 · P30.1 plan + tracker written (no code)
