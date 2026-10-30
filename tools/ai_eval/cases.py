"""Loading the fixture cases (``tests/fixtures/ai_edits/<case>/``) and running one through the
app's own AI code: a change through :class:`EditRun` (the whole proposal accepted), an answer
command placed by ``answer_point`` and cleaned while it streams, Translate → Replace through
``replacement_result``.

A case folder holds ``note.md`` (the selection marked ``⟦sel⟧…⟦/sel⟧``), ``case.json``
(``command``, ``instruction``, ``groups``, ``notes`` — other notes of the vault —, ``expect``:
checks any model must pass, ``expect_unit``: checks of the scripted replies' exact wording) and
``fake.json`` (the scripted replies for unit mode).
"""

import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from paper_pile.core.ai.cleanup import StreamCleaner
from paper_pile.core.ai.commands import ai_command
from paper_pile.core.ai.edit_run import EditResult, EditRun, replacement_result
from paper_pile.core.ai.engine import AiEngine
from paper_pile.core.ai.placement import answer_point
from paper_pile.core.ai.proposals import accept, apply_changes

FIXTURES = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "ai_edits"
NOTE = "note.md"
_SEL = re.compile(r"⟦sel⟧(.*?)⟦/sel⟧", re.DOTALL)


@dataclass
class Case:
    name: str
    note: str  # without the selection marks
    selection: tuple[int, int] | None
    command: str  # an AI command id, or "translate-replace"
    instruction: str
    groups: tuple[str, ...]
    notes: dict[str, str]  # other notes in the vault
    expect: list[list[Any]]
    script: list[str]
    expect_unit: list[list[Any]] = field(default_factory=list)
    unit_only: bool = False  # it tests bad model output: only with the scripted replies
    num_ctx: int = 0  # a smaller context window for this case (a long-text case), 0: the model's


@dataclass
class Outcome:
    case: Case
    after: str  # the note once the AI's change is accepted (or its answer written)
    result: EditResult | None = None
    answer: str = ""  # an answer command's text, as written
    calls: int = 0
    seconds: float = 0.0
    error: str = ""
    extra: dict[str, Any] = field(default_factory=dict)


def load_case(folder: Path) -> Case:
    raw = (folder / NOTE).read_text(encoding="utf-8")
    m = _SEL.search(raw)
    note = _SEL.sub(lambda x: x.group(1), raw)
    selection = (m.start(), m.start() + len(m.group(1))) if m else None
    spec = json.loads((folder / "case.json").read_text(encoding="utf-8"))
    fake = folder / "fake.json"
    script = json.loads(fake.read_text(encoding="utf-8")) if fake.exists() else []
    return Case(
        folder.name,
        note,
        selection,
        spec["command"],
        spec.get("instruction", ""),
        tuple(spec.get("groups", ())),
        dict(spec.get("notes", {})),
        list(spec["expect"]),
        list(script),
        list(spec.get("expect_unit", [])),
        bool(spec.get("unit_only")),
        int(spec.get("num_ctx", 0)),
    )


def load_cases(root: Path = FIXTURES) -> list[Case]:
    return [load_case(d) for d in sorted(root.iterdir()) if (d / "case.json").exists()]


def write_vault(case: Case, root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / NOTE).write_text(case.note, encoding="utf-8")
    for name, text in case.notes.items():
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).write_text(text, encoding="utf-8")


async def run_case(case: Case, engine: AiEngine) -> Outcome:
    """``case`` through the app's own code with ``engine`` (its vault holds the case's notes)."""
    began = time.monotonic()
    try:
        if case.command == "translate-replace":
            out = await _translate(case, engine)
        elif (cmd := ai_command(case.command)) is not None and cmd.kind == "change":
            out = await _change(case, engine)
        else:
            out = await _answer(case, engine)
    except Exception as exc:  # noqa: BLE001  (a failing case is a result, not a crash)
        out = Outcome(case, case.note, error=f"{type(exc).__name__}: {exc}")
    out.seconds = time.monotonic() - began
    return out


async def _change(case: Case, engine: AiEngine) -> Outcome:
    cmd = ai_command(case.command)
    assert cmd is not None
    run = EditRun(
        engine,
        path=NOTE,
        note=case.note,
        selection=case.selection,
        instruction=cmd.request(case.instruction),
        words=case.instruction,
        command_id=cmd.id,
        groups=case.groups,
    )
    result = await run.run()
    after = case.note
    if result.proposal is not None:
        done = accept(result.proposal, case.note)
        if done is not None:
            after = apply_changes(case.note, done[0])
    return Outcome(case, after, result, calls=run.calls)


async def _answer(case: Case, engine: AiEngine) -> Outcome:
    cmd = ai_command(case.command)
    assert cmd is not None
    start, end = case.selection or (0, len(case.note))
    point = answer_point(case.note, start, end, whole=case.selection is None)
    messages = await engine.command_messages(
        cmd.spec(case.instruction),
        path=NOTE,
        text=case.note,
        caret=point.offset,
        selected=case.note[start:end] if case.selection else "",
    )
    cleaner = StreamCleaner(point.heading_floor, avoid_bullet=point.avoid_bullet)
    stream = engine.stream(messages, think=False)  # as the app writes answers
    text = "".join([cleaner.feed(p) async for p in stream]) + cleaner.finish()
    after = case.note[: point.offset] + point.lead + text + case.note[point.offset :]
    return Outcome(case, after, answer=text, calls=1)


async def _translate(case: Case, engine: AiEngine) -> Outcome:
    cmd = ai_command("ai-translate")
    assert cmd is not None and case.selection is not None
    start, end = case.selection
    spec = cmd.spec(case.instruction)
    selected = case.note[start:end]
    messages = await engine.command_messages(
        spec, path=NOTE, text=case.note, caret=end, selected=selected
    )
    answer = "".join([p async for p in engine.stream(messages, think=False)])
    result = replacement_result(NOTE, case.note, start, end, answer, "translation")
    after = case.note
    if result.proposal is not None:
        done = accept(result.proposal, case.note)
        if done is not None:
            after = apply_changes(case.note, done[0])
    return Outcome(case, after, result, answer=answer, calls=1)
