# Eval results

Raw logs of the AI evals (`tools/ai_eval/…`), kept so later versions can be compared with
these. One file per run: `<date>_<eval>_<version>_<model>.txt`. Single runs (`--runs 1`):
a difference of one case on a set is within run-to-run noise.

## 2026-11-11 · intent (`tools/ai_eval/intent.py`, `core/ai/understand.py`)

User report: "describe …" typed in the Ask box on a selection (Antigravity backend) edited the
note instead of answering. Class: a request to be told something, worded as a command.
held-out-4 (16) was written before any change, and held-out-5 (13) after v2, before v3.

| Set | v1 old · gemma4 | v3 · gemma4 | v1 old · Gemini | v3 · Gemini |
|---|---|---|---|---|
| eval (40) | 38 | 38 | 37 | 38 |
| held-out (20) | 18 | 17 | 18 | 18 |
| held-out-2 (15) | 14 | 13 | 15 | 15 |
| held-out-3 (12) | 12 | 12 | 12 | 12 |
| held-out-4 (16) | 16 | 16 | 9 | 11 |
| held-out-5 (13) | 11 ¹ | 10 | 10 ¹ | 11 |
| reported (3) | 3 | 3 | 2 | 3 |
| time / request | ~3.5 s | ~4 s | ~30 s (10–230) | ~40 s (10–190) |

Gemini = `gemini-3.8-flash-medium` through the Antigravity CLI.
¹ old rules run on held-out-5 alone (`*_v1-old_held-out-5_*`), after v3's runs.

- **v1 (old):** the rules said "an instruction … to write more about its subject is a change".
- **v2 (rejected):** a `result` field first, which listed kinds of change and said "when either
  reading fits, it is information". gemma4: eval 35/40, held-out 16, held-out-2 12, and choice-open
  requests were acted on. The Gemini run was stopped after the gemma4 result (partial log).
- **v3 (kept):** a neutral `result` field (the text itself / information about it) decided
  first. The `want` rules are kept, except that the faulty sentence now says "write more *of* it,
  work more *into* it", and the answer rules add "also when worded as a command". In Python, a
  change needs `result` and `want` to agree, so an answer is the default.
  Gemini still edits on 5 of 16 held-out-4 cases: "describe the trade-offs", "outline the
  argument", "break this down", "characterize each option" and "continue this paragraph"
  (asked for a choice). Not fixed yet (TRACKER Open issues).

## 2026-11-12 · intent on ornith-1.5:9b (Ollama, third model)

| Set | v1 old | v3 |
|---|---|---|
| eval (40) | 28 (change 10, open 8, answer 10) | 25 (change 17, open 1, answer 7) |
| held-out (20) | 13 | 10 |
| held-out-2 (15) | 8 | 10 |
| held-out-3 (12) | 9 | 8 |
| held-out-4 (16) | 10 | 4 |
| held-out-5 (13) | 6 | 5 |
| reported (3) | 1 | 2 |
| time / request | ~1.5 s | ~1.5 s |

v3 makes ornith worse, on the class it was meant to fix.
Cause (raw JSON probe): ornith answers `result: "the_text_itself"`, the enum's first value, for
every request, even "is this too long?". v3's rule "want: change exactly when result is the text
itself" then copies that into `want`, so the two fields are not independent votes and the
agreement guard never fires. Next version: the safe value first in the enum, and no rule that ties
`want` to `result` (TRACKER Open issues).
