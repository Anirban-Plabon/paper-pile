"""P29: a typed request is understood by the model — change or answer, complete or with a choice
left open, how far a change reaches (PLAN §4.31). The model's quality is measured on paraphrases
by ``tools/ai_eval/intent.py``; these tests cover reading its answer and using it."""

import json
from pathlib import Path

from paper_pile.core.ai.edit_run import EditRun
from paper_pile.core.ai.engine import AiEngine
from paper_pile.core.ai.fake import FakeProvider
from paper_pile.core.ai.understand import SCHEMA, Understood, parse, understand
from paper_pile.core.config import Config
from paper_pile.core.vault import Vault

TEXT = "We compare three options for hosting."


def answer(**kw: object) -> dict[str, object]:
    base: dict[str, object] = {
        "want": "change", "complete": True, "question": "", "options": [],
        "reach": "selection", "size": "medium", "adds": False, "new_form": False,
    }  # fmt: skip
    return {**base, **kw}


def test_a_complete_change() -> None:
    found = parse(answer(size="large", adds=True))
    assert found == Understood("change", True, "", (), "selection", "large", True)
    assert found is not None and found.intent().scope == "text"


def test_a_choice_left_open_comes_with_its_question_and_options() -> None:
    found = parse(
        answer(complete=False, question="Which tone?", options=["Formal", "Friendly", "Formal "])
    )
    assert found is not None and not found.complete
    assert found.question == "Which tone?" and found.options == ("Formal", "Friendly")


def test_open_without_choices_to_offer_is_acted_on() -> None:
    found = parse(answer(complete=False, question="Which?", options=["Only one"]))
    assert found is not None and found.complete and found.options == () and found.question == ""


def test_an_answer_is_always_complete_and_nonsense_is_none() -> None:
    found = parse(answer(want="answer", complete=False, options=["a", "b"]))
    assert found is not None and found.complete and found.options == ()
    assert parse(None) is None and parse({"want": "maybe"}) is None
    odd = parse(answer(reach="everywhere", size="huge"))
    assert odd is not None and (odd.reach, odd.size) == ("selection", "medium")


def test_reach_and_new_form_become_the_pipeline_intent() -> None:
    found = parse(answer(reach="note", new_form=True, size="small"))
    assert found is not None
    assert found.intent() == found.intent() and found.intent().scope == "note"
    assert found.intent().asks_structure and found.intent().size == "small"
    assert set(SCHEMA["required"]) == set(SCHEMA["properties"])


def engine(tmp_path: Path, replies: list[str]) -> tuple[AiEngine, FakeProvider]:
    root = tmp_path / "v"
    root.mkdir()
    (root / "h.md").write_text(f"# H\n\n{TEXT}\n")
    fake = FakeProvider(delay=0, script=replies)
    ai = AiEngine(Vault(root), Config(vault=root), provider_factory=lambda _c: fake)
    ai.allow()
    return ai, fake


async def test_understand_asks_with_the_text_and_no_reasoning(tmp_path: Path) -> None:
    ai, fake = engine(tmp_path, [json.dumps(answer(want="answer"))])
    found = await understand(ai, "is this accurate?", TEXT)
    assert found is not None and found.want == "answer"
    sent = fake.calls[0][-1].content
    assert TEXT in sent and "is this accurate?" in sent
    assert fake.options is not None and fake.options.schema is not None
    assert fake.options.think is False


async def test_a_failing_model_gives_none(tmp_path: Path) -> None:
    ai, fake = engine(tmp_path, [])
    fake.up = False
    fake.fail_calls = 1
    assert await understand(ai, "whatever", TEXT) is None


async def test_the_understood_scope_wins_over_word_lists(tmp_path: Path) -> None:
    ai, _fake = engine(tmp_path, [])
    note = f"# H\n\n{TEXT}\n"
    at = note.index(TEXT)
    common = {"path": "h.md", "note": note, "selection": (at, at + len(TEXT))}
    words_only = EditRun(ai, instruction="add Fly.io", **common)  # type: ignore[arg-type]
    assert words_only.intent.scope == "note"  # "add": the word list says plan the note
    told = parse(answer(adds=True))
    assert told is not None
    run = EditRun(ai, instruction="add Fly.io", intent=told.intent(), **common)  # type: ignore[arg-type]
    assert run.intent.scope == "text" and run.intent.adds
