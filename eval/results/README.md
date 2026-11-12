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

## 2026-11-12 · intent on lfm3:latest (1.1 GB) and NeoHorse-1:9B (Ollama)

| Set | lfm3 old | lfm3 v3 | NeoHorse old | NeoHorse v3 |
|---|---|---|---|---|
| eval (40) | 16 (change 11, open 3, answer 2) | 24 (9, 5, 10) | 32 (15, 7, 10) | 31 (18, 3, 10) |
| held-out (20) | 8 | 12 | 16 | 15 |
| held-out-2 (15) | 6 | 10 | 13 | 10 |
| held-out-3 (12) | 7 | 8 | 11 | 6 |
| held-out-4 (16) | 5 | 8 | 7 | 13 |
| held-out-5 (13) | 6 | 9 | 9 | 8 |
| reported (3) | 2 | 3 | 2 | 1 |
| time / request | ~1.1 s | ~1.5 s | ~3.6 s | ~3.5 s |

- **lfm3:** v3 is better on every set (eval 16 → 24, held-out-4 5 → 8/16). With the old rules it
  answers only 2 of 12 questions; the `result` field fixes that.
- **NeoHorse:** held-out-4, the class of this fix, rises 7 → 13/16, but it loses ground on
  requests that leave a choice open (open 7 → 3/8; held-out-3 11 → 6/12; held-out-2 13 → 10/15):
  it acts on "change the tone" instead of asking which. Eval total 32 → 31.
- A first run used the name `lfm3:1.7b`, which is not installed (0/40 in 0 s, "no answer");
  it is not kept. The model is `lfm3:latest`.

## All models, v1 old → v3 (eval 40 / held-out-4 16)

| Model | eval | held-out-4 |
|---|---|---|
| gemma4:12b | 38 → 38 | 16 → 16 |
| Gemini 3.8 flash (Antigravity) | 37 → 38 | 9 → 11 |
| NeoHorse-1:9B | 32 → 31 | 7 → 13 |
| lfm3 | 16 → 24 | 5 → 8 |
| ornith-1.5:9b | 28 → 25 | 10 → 4 |

v3 helps four of five models on the "describe…" class and hurts ornith. NeoHorse also loses on
choice-open requests, and ornith on those and on questions.

## 2026-11-12 · v4 (rejected): safe value first in every enum, `result` and `want` independent

held-out-6 (16, every group) written before v4. v1 / v3 were run on held-out-6 alone.

| Model | v4 eval (40) | v4 change / open / answer | held-out-6 v1 | v3 | v4 |
|---|---|---|---|---|---|
| gemma4:12b | 37 | 20 / 5 / 12 | 14 | 13 | 14 |
| ornith-1.5:9b | 27 | 14 / 3 / 10 | 11 | 8 | 11 |
| NeoHorse-1:9B | 21 | 8 / 1 / 12 | 14 | 12 | 10 |
| lfm3:latest | 12 | 0 / 0 / 12 | 8 | 9 | 7 |

- Putting "answer" first flips which way small models fail: lfm3 never edits (0/20 changes,
  not even "fix the typos"), NeoHorse edits on 8/20. Small models do not decide here; they take
  the first value. Antigravity not run (rejected on the local models first).
- On the fresh, balanced held-out-6 the **old rules (v1) are best or within one case on all
  four local models**; v3's gain is the "describe…" class (held-out-4), mostly on Gemini.
- Conclusion: changing the order or tying of fields does not make the one call easier for small
  models. The next step is to make the call itself smaller (fewer fields, shorter rules), with a
  fresh held-out-7.
