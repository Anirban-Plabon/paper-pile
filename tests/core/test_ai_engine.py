"""The AI engine (PLAN §4.26): the chat's turns, saving, messages and the AI commands' prompts."""

from pathlib import Path

import pytest

from paper_pile.core.ai.attachments import FileRef
from paper_pile.core.ai.chats import load_chat
from paper_pile.core.ai.context import EditorSnapshot
from paper_pile.core.ai.engine import NOTE_ONLY, AiEngine
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
    assert sent[0].role == "system" and "alpha body" in sent[0].content and "Ana" in sent[0].content
    assert [(m.role, m.content.strip()) for m in sent[1:]] == [
        ("user", "first"),
        ("assistant", "You said: first"),
        ("user", "second"),
    ]
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
    system = fake.calls[-1][0].content
    assert "chosen words" in system and "file text" in system and "beta body" in system
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


def test_command_messages(vault: Vault, fake: FakeProvider) -> None:
    ai = engine(vault, fake)
    text = "intro\n" + "x" * 5000 + "\nEND"
    fix = StreamInsert("Fix it.", source="selection", replace_selection=True)
    msgs = ai.command_messages(fix, path="a.md", text=text, caret=0, selected="teh cat")
    assert msgs[0].content.endswith(NOTE_ONLY) and "teh cat" in msgs[0].content
    assert msgs[1].content == "Fix it.\n\nText:\nteh cat"
    cont = StreamInsert("Continue.", source="before")
    msgs = ai.command_messages(cont, path="a.md", text=text, caret=len(text))
    assert msgs[1].content.endswith("END") and len(msgs[1].content) < 4100
    ask_it = StreamInsert("", source="auto", ask=True)
    msgs = ai.command_messages(ask_it, path="a.md", text="note", caret=0, question="Why?")
    assert msgs[1].content == "Why?" and not msgs[0].content.endswith(NOTE_ONLY)


async def test_stream_passes_model_and_options(vault: Vault, fake: FakeProvider) -> None:
    ai = engine(vault, fake, ai__temperature=0.3)
    assert "".join([p async for p in ai.stream([])]) == "You said:  "
    assert fake.options is not None and fake.options.temperature == 0.3
