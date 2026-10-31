# ruff: noqa: E402
"""Does the model understand what a typed request means (PLAN §4.31, ``core/ai/understand.py``)?
Dev tool, run against a real model:

    uv run python tools/ai_eval/intent.py --model gemma4:12b [--runs 2] [--provider ollama]

Each case is a request about a selected text with what it means: change or answer, and for a
change whether it says enough to act on. The cases are paraphrases written for this eval — the
requests users reported (2026-10-31) are a separate "reported" group, so the score shows
whether the rules generalize rather than fit those phrasings. Nothing is written anywhere.
"""

import argparse
import asyncio
import os
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from paper_pile.core.ai.engine import AiEngine
from paper_pile.core.ai.understand import understand
from paper_pile.core.config import Config
from paper_pile.core.vault import Vault

PARA = (
    "We compare three options for hosting. Docker runs one container, a VM gives you a whole "
    "machine, and bare metal has no layer at all."
)
LIST = "- **Docker**: one container\n- **VM**: a whole machine\n- **Bare metal**: no layer"
TYPOS = "The backups runs every night and they is stored on the NAS."

C, CO, A = "change", "change-open", "answer"  # change (complete), change with a choice left open
CASES: list[tuple[str, str, str]] = [  # (group, selected text, request)
    (C, PARA, "could you flesh this out a bit"),
    (C, PARA, "go deeper on this point"),
    (C, PARA, "say more here"),
    (C, PARA, "tighten this up"),
    (C, PARA, "this is too wordy"),
    (C, TYPOS, "fix the typos"),
    (C, PARA, "bullet points please"),
    (C, PARA, "put this into Spanish"),
    (C, LIST, "this should be a table"),
    (C, PARA, "add an example after the second sentence"),
    (C, TYPOS, "use active voice"),
    (C, PARA, "remove the last sentence"),
    (C, PARA, "less jargon"),
    (C, PARA, "write it for a ten year old"),
    (C, PARA, "expand on the trade-offs"),
    (C, PARA, "make it punchier"),
    (C, PARA, "add a closing line that sums it up"),
    (C, PARA, "split this into two paragraphs"),
    (C, PARA, "sound more professional"),
    (C, LIST, "add a short reason to each item"),
    (CO, PARA, "adjust the voice"),
    (CO, PARA, "put this in another language"),
    (CO, PARA, "give it a different style"),
    (CO, LIST, "reformat it"),
    (CO, PARA, "make it sound different"),
    (CO, PARA, "change the length"),
    (CO, PARA, "rewrite this for a different audience"),
    (CO, PARA, "alter the mood of this"),
    (A, PARA, "what does this mean?"),
    (A, PARA, "is this accurate?"),
    (A, PARA, "why would someone pick a VM here?"),
    (A, TYPOS, "can you check whether this is correct"),
    (A, PARA, "give me the gist"),
    (A, LIST, "what's missing from this list?"),
    (A, PARA, "any weak points in this argument?"),
    (A, LIST, "how many options are listed?"),
    (A, PARA, "who is this written for?"),
    (A, PARA, "thoughts?"),
    (A, LIST, "define bare metal"),
    (A, PARA, "which one is cheapest?"),
]
# written after the first run, before the prompt was tuned on its failures: the honest test
HELD_OUT: list[tuple[str, str, str]] = [
    (C, PARA, "beef this up"),
    (C, PARA, "can this be more vivid"),
    (C, PARA, "add some numbers to back this up"),
    (C, LIST, "drop the bold"),
    (C, PARA, "merge these into one sentence"),
    (C, PARA, "a heading on top please"),
    (C, PARA, "shorter"),
    (C, PARA, "rephrase without the word 'whole'"),
    (C, LIST, "elaborate on the VM option"),
    (C, PARA, "more examples"),
    (CO, PARA, "translate"),
    (CO, LIST, "change the format"),
    (CO, PARA, "make it fit a different platform"),
    (CO, PARA, "rewrite in a different register"),
    (A, TYPOS, "is the grammar ok?"),
    (A, PARA, "what's the main claim here"),
    (A, PARA, "summarize for me"),
    (A, PARA, "does this contradict itself?"),
    (A, PARA, "what would you change?"),
    (A, LIST, "which of these is fastest to set up?"),
]
# written before the "direction" prompt (the first held-out set had been used by then)
HELD_OUT_2: list[tuple[str, str, str]] = [
    (C, PARA, "make it more upbeat"),
    (C, PARA, "cut it in half"),
    (C, PARA, "give it a stronger opening"),
    (C, PARA, "now in German"),
    (C, LIST, "turn this into a checklist"),
    (C, PARA, "lighter on detail"),
    (C, PARA, "add a caveat about cost"),
    (CO, PARA, "change the wording style"),
    (CO, PARA, "use another tone"),
    (CO, LIST, "convert it"),
    (CO, PARA, "make it suit another reader"),
    (A, PARA, "is this too long?"),
    (A, PARA, "what tone is this?"),
    (A, LIST, "does the list cover everything?"),
    (A, PARA, "rate this paragraph"),
]
# written before the "results + must_choose" prompt (both earlier held-out sets were used)
HELD_OUT_3: list[tuple[str, str, str]] = [
    (C, PARA, "make the last part snappier"),
    (C, LIST, "sort these alphabetically"),
    (C, PARA, "add a sentence on security"),
    (C, PARA, "into plain English"),
    (C, PARA, "simplify"),
    (CO, PARA, "pick a different tone for it"),
    (CO, LIST, "present it another way"),
    (CO, PARA, "rewrite it in some other language"),
    (CO, PARA, "modify the length"),
    (A, PARA, "is this clear enough?"),
    (A, LIST, "which would you choose?"),
    (A, PARA, "what's a better word for 'layer' here?"),
]
REPORTED: list[tuple[str, str, str]] = [  # what users typed (2026-10-31): not in the score
    (C, PARA, "Elaborate this"),
    (CO, PARA, "change the tone"),
]


def verdict(group: str, found: object) -> tuple[bool, str]:
    if found is None:
        return False, "no answer"
    want, complete = found.want, found.complete  # type: ignore[attr-defined]
    got = A if want == "answer" else (C if complete else CO)
    detail = got + (f" {list(found.options)[:3]}" if got == CO else "")  # type: ignore[attr-defined]
    return got == group, detail


async def main(args: argparse.Namespace) -> int:
    os.environ["PAPER_PILE_AI"] = "1"
    work = Path(tempfile.mkdtemp(prefix="pp-intent-"))
    (work / "v").mkdir()
    config = Config(global_path=work / "c.toml", vault=work / "v")
    config.set("ai.provider", args.provider)
    config.set("ai.model", args.model)
    config.set("ai.preload", False)
    if args.host:
        config.set("ai.host", args.host)
    ai = AiEngine(Vault(work / "v"), config, access_dir=work / "a")
    by_group: dict[str, list[bool]] = {}
    started = time.monotonic()
    for label, cases in (
        ("eval", CASES),
        ("held-out", HELD_OUT),
        ("held-out-2", HELD_OUT_2),
        ("held-out-3", HELD_OUT_3),
        ("reported", REPORTED),
    ):
        print(f"--- {label}")
        for group, selected, request in cases:
            for _ in range(args.runs):
                t = time.monotonic()
                ok, detail = verdict(group, await understand(ai, request, selected))
                key = group if label == "eval" else label
                by_group.setdefault(key, []).append(ok)
                mark = "PASS" if ok else "FAIL"
                print(
                    f"{mark}  {group:11} {request!r:48} → {detail}  ({time.monotonic() - t:.1f} s)"
                )
    print("---")
    total = [ok for g, oks in by_group.items() if g in (C, CO, A) for ok in oks]
    for group, oks in by_group.items():
        print(f"{group:11} {sum(oks)}/{len(oks)}")
    print(f"eval total  {sum(total)}/{len(total)}  ({time.monotonic() - started:.0f} s)")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--model", required=True)
    parser.add_argument("--runs", type=int, default=1)
    parser.add_argument("--provider", default="ollama", choices=("ollama", "vllm", "openai"))
    parser.add_argument("--host", default="")
    sys.exit(asyncio.run(main(parser.parse_args())))
