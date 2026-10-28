"""The AI engine (PLAN §4.26): the chat's turns, saving, messages and the AI commands' prompts."""

from pathlib import Path

import pytest

from paper_pile.core.ai.attachments import FileRef
from paper_pile.core.ai.chats import load_chat
from paper_pile.core.ai.context import EditorSnapshot
from paper_pile.core.ai.engine import (
    DIVIDER,
    NOTE_ONLY,
    AiEngine,
    message_tokens,
    short_count,
)
from paper_pile.core.ai.fake import FakeProvider
from paper_pile.core.commands import StreamInsert
from paper_pile.core.config import Config
from paper_pile.core.vault import Vault


@pytest.fixture
def vault(tmp_path: Path) -> Vault:
    v = Vault(tmp_path / "v")
    v.root.mkdir()
    v.create_note("a.md", "# A\nalpha body\n")
    v.create_note("b.md", "beta body")
    return v


@pytest.fixture
def fake() -> FakeProvider:
    return FakeProvider(delay=0)


def engine(vault: Vault, fake: FakeProvider, **config: object) -> AiEngine:
    cfg = Config(vault=vault.root)
    for key, value in config.items():
        cfg.set(key.replace("__", "."), value, "vault")
    return AiEngine(vault, cfg, user_name=lambda: "Ana", provider_factory=lambda _c: fake)


async def ask(ai: AiEngine, text: str, snap: EditorSnapshot | None = None, **kw: object) -> str:
    out = ai.add_message(text, **kw)  # type: ignore[arg-type]
    reply = ai.start_reply()
    pieces = [p async for p in ai.answer(reply, out, snap or EditorSnapshot())]
    assert "".join(pieces) == reply.text
    return reply.text


async def test_chat_turns_messages_and_save(vault: Vault, fake: FakeProvider) -> None:
    ai = engine(vault, fake)
    assert await ask(ai, "first") == "You said: first "
    await ask(ai, "second", EditorSnapshot("a.md", "# A\nalpha body\n"))
    sent = fake.calls[-1]
    assert sent[0].role == "system" and "Ana" in sent[0].content
    assert "alpha body" not in sent[0].content  # notes go with the message
    assert [(m.role, m.content.strip()) for m in sent[1:3]] == [
        ("user", "first"),
        ("assistant", "You said: first"),
    ]
    assert sent[3].content.startswith("The user's notes") and "alpha body" in sent[3].content
    assert sent[3].content.endswith(DIVIDER + "second")
    assert ai.title == "first"
    ai.save()
    saved = load_chat(ai.chats_dir(), ai.chat_id)
    assert saved is not None and [t.role for t in saved.turns] == ["user", "assistant"] * 2


async def test_history_turns_cap_and_failed_turns_left_out(
    vault: Vault, fake: FakeProvider
) -> None:
    ai = engine(vault, fake, ai__history_turns=2)
    await ask(ai, "one")
    ai.add_message("two")
    ai.failed(ai.start_reply(), "Ollama isn't running")
    await ask(ai, "three")
    past = [m.content.strip() for m in fake.calls[-1][1:-1]]
    assert past == ["You said: one", "two"]  # the failed reply is not sent, the cap keeps 2


async def test_attachments_go_to_context_and_quotes(vault: Vault, fake: FakeProvider) -> None:
    ai = engine(vault, fake)
    picked = ai.selection("chosen words", "a.md")
    files = [FileRef("x.txt", "file text")]
    await ask(ai, "what?", selections=[picked], notes=["b.md", "missing.md"], files=files)
    message = fake.calls[-1][-1].content
    assert "chosen words" in message and "file text" in message and "beta body" in message
    user = ai.turns[0]
    assert user.attachment.splitlines() == ["From [[a]]: [Selected text]", "[[b]]", "x.txt: [File]"]
    assert user.quotes[0].text == "chosen words" and user.quotes[0].note == "a"
    assert ai.turns[1].summary.startswith("Context:")


def test_block_attachment(vault: Vault, fake: FakeProvider) -> None:
    ai = engine(vault, fake)
    code = ai.block("code", "py", "x = 1\ny = 2\n", "a.md")
    assert code.text == "```py\nx = 1\ny = 2\n```" and code.kind == "Code block"
    assert code.size() == "2 lines" and code.label == "From [[a]]"
    assert ai.block("math", "", "e=mc^2", "").text == "$$\ne=mc^2\n$$"


async def test_open_new_forget_and_delete(vault: Vault, fake: FakeProvider) -> None:
    ai = engine(vault, fake)
    await ask(ai, "keep me")
    ai.save()
    first = ai.chat_id
    ai.new_chat()
    assert ai.turns == [] and ai.chat_id != first
    assert ai.open_chat(first) and ai.title == "keep me"
    assert not ai.open_chat("20990101-000000-nothere")
    assert not ai.forget("other") and ai.chat_id == first
    assert ai.delete_chat(first) and ai.turns == []
    assert load_chat(ai.chats_dir(), first) is None


def test_save_off_and_empty_chat(vault: Vault, fake: FakeProvider) -> None:
    ai = engine(vault, fake, ai__save_chats=False)
    ai.add_message("hello")
    ai.save()
    engine(vault, fake).save()  # nothing said yet
    assert list(ai.chats_dir().glob("*.json")) == []


async def test_command_messages(vault: Vault, fake: FakeProvider) -> None:
    ai = engine(vault, fake)
    text = "intro\n" + "x" * 5000 + "\nEND"
    fix = StreamInsert("Fix it.", source="selection", replace_selection=True)
    msgs = await ai.command_messages(fix, path="a.md", text=text, caret=0, selected="teh cat")
    assert msgs[0].content.endswith(NOTE_ONLY) and "teh cat" not in msgs[0].content
    assert msgs[1].content.endswith(DIVIDER + "Fix it.\n\nText:\nteh cat")
    assert msgs[1].content.count("teh cat") == 1  # the selection is sent once
    cont = StreamInsert("Continue.", source="before")
    msgs = await ai.command_messages(cont, path="a.md", text=text, caret=len(text))
    task = msgs[1].content.split(DIVIDER)[-1]
    assert task.endswith("END") and len(task) < 4100
    ask_it = StreamInsert("", source="auto", ask=True)
    msgs = await ai.command_messages(ask_it, path="a.md", text="note", caret=0, question="Why?")
    assert msgs[1].content.endswith(DIVIDER + "Why?") and not msgs[0].content.endswith(NOTE_ONLY)


async def test_stream_passes_model_and_options(vault: Vault, fake: FakeProvider) -> None:
    ai = engine(vault, fake, ai__temperature=0.3)
    assert "".join([p async for p in ai.stream([])]) == "You said:  "
    assert fake.options is not None and fake.options.temperature == 0.3


@pytest.mark.parametrize(
    ("model_max", "num_ctx", "expected"),
    [(131072, 0, 8192), (4096, 0, 4096), (None, 0, 8192), (4096, 16384, 16384)],
)
async def test_window_from_the_model_and_sent_to_it(
    vault: Vault, fake: FakeProvider, model_max: int | None, num_ctx: int, expected: int
) -> None:
    fake.max_context = model_max
    ai = engine(vault, fake, ai__num_ctx=num_ctx)
    assert await ai.window() == expected
    await ask(ai, "hi")
    assert fake.options is not None and fake.options.num_ctx == expected


async def test_long_chat_never_overflows_the_window(vault: Vault, fake: FakeProvider) -> None:
    fake.max_context = 2048
    ai = engine(vault, fake, ai__history_turns=50)
    for i in range(30):
        ai.add_message(f"question {i} " + "q" * 300)
        ai.start_reply().text = f"answer {i} " + "a" * 300
    big = "note line\n" * 2000  # far more than the window
    await ask(ai, "last one", EditorSnapshot("a.md", big))
    sent = fake.calls[-1]
    assert message_tokens(sent) <= 2048 - AiEngine.answer_room(2048)
    assert sent[-1].content.endswith(DIVIDER + "last one")
    assert sent[-2].content.startswith("answer 29")  # the newest turns are the ones kept
    assert len(sent) < 30
    assert ai.turns[-1].summary.endswith("/ 2k tokens") and "(some cut)" in ai.turns[-1].summary


def test_short_count() -> None:
    assert [short_count(n) for n in (850, 1536, 2048, 2150, 8192, 131072)] == [
        "850",
        "1.5k",
        "2k",
        "2.1k",
        "8k",
        "128k",
    ]


async def test_prompt_start_stays_the_same_from_message_to_message(
    vault: Vault, fake: FakeProvider
) -> None:
    ai = engine(vault, fake)
    note = "# A\nalpha body\n"
    for i in range(4):
        note += f"edit {i}\n"  # the open note changes between messages
        await ask(ai, f"question {i}", EditorSnapshot("a.md", note))
    systems = {call[0].content for call in fake.calls}
    assert len(systems) == 1 and "edit" not in systems.pop()
    for before, after in zip(fake.calls, fake.calls[1:], strict=False):
        assert after[: len(before) - 1] == before[:-1]  # only the last message differs


async def test_attached_note_and_quote_stay_for_later_messages(
    vault: Vault, fake: FakeProvider
) -> None:
    ai = engine(vault, fake)
    await ask(ai, "about b", selections=[ai.selection("chosen words", "a.md")], notes=["b.md"])
    assert ai.turns[0].notes == ["b"]
    await ask(ai, "and now?")
    sent = fake.calls[-1]
    assert "beta body" in sent[-1].content  # the note attached earlier is still sent
    assert "chosen words" in sent[1].content and sent[1].content.endswith("about b")


async def test_no_vault_walk_or_reread_per_message(
    vault: Vault, fake: FakeProvider, monkeypatch: pytest.MonkeyPatch
) -> None:
    walks: list[int] = []
    reads: list[str] = []
    walk, read = vault.walk_notes, vault.read_text
    monkeypatch.setattr(vault, "walk_notes", lambda: (walks.append(1), walk())[1])
    monkeypatch.setattr(vault, "read_text", lambda rel: (reads.append(str(rel)), read(rel))[1])
    ai = engine(vault, fake)
    for i in range(3):
        await ask(ai, f"see @b {i}")
    assert len(walks) == 1 and reads.count("b.md") == 1
    ai.notes_changed()
    await ask(ai, "@b again")
    assert len(walks) == 2


def test_old_chat_files_load(vault: Vault, tmp_path: Path) -> None:
    import json

    folder = tmp_path / "chats"
    folder.mkdir()
    turns = [{"role": "user", "text": "hi"}, {"role": "user", "text": "x", "notes": "bad"}]
    (folder / "20260101-000000-aaaaaa.json").write_text(json.dumps({"turns": turns}))
    chat = load_chat(folder, "20260101-000000-aaaaaa")
    assert chat is not None and [t.notes for t in chat.turns] == [[], []]
