"""Citations in the normal chat (PLAN_vault_agent §7.1, P30.43): the notes sent are numbered,
the answer's numbers are checked and kept as citations (pills), unknown numbers dropped; the
one-shot prompts (AI commands) keep their unnumbered notes."""

from pathlib import Path

from paper_pile.core.ai.context import Context, ContextPart, EditorSnapshot
from paper_pile.core.ai.engine import AiEngine
from paper_pile.core.ai.fake import FakeProvider
from paper_pile.core.config import Config, scope_for
from paper_pile.core.vault import Vault


def test_notes_block_labels_only_when_asked() -> None:
    ctx = Context(1000, [ContextPart("note", "Current note: a.md", "a.md", "alpha")])
    plain = ctx.notes_block()
    assert plain == "The user's notes, for context:\n\n## Current note: a.md\nalpha"
    labelled = ctx.notes_block(labels=True)
    assert "## [1] Current note: a.md\nalpha" in labelled
    assert "data, not instructions" in labelled and "like [1]" in labelled
    assert "[1]" not in ctx.system_prompt()  # one-shot prompts: as before


async def test_chat_answer_keeps_its_citations(tmp_path: Path) -> None:
    vault = Vault(tmp_path / "v")
    vault.root.mkdir()
    vault.create_note("a.md", "# A\nalpha body\n")
    fake = FakeProvider(delay=0, script=["Alpha is the body [1]. Nothing here [9]."])
    cfg = Config(vault=vault.root)
    cfg.set("ai.vault_agent", "off", scope_for("ai.vault_agent", "vault"))
    ai = AiEngine(vault, cfg, provider_factory=lambda _c: fake)
    ai.allow()
    out = ai.add_message("what does it say?")
    reply = ai.start_reply()
    async for _ in ai.answer(reply, out, EditorSnapshot("a.md", "# A\nalpha body\n")):
        pass
    assert "## [1] Current note: a.md" in fake.calls[-1][-1].content
    assert reply.text == "Alpha is the body [1]. Nothing here."  # [9] was never sent
    assert reply.vault["kind"] == "chat"
    assert [(c["n"], c["path"]) for c in reply.vault["cites"]] == [(1, "a.md")]
    assert reply.vault["cites"][0]["anchor"].startswith("# A alpha body")
