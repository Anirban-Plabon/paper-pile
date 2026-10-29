"""P23 AI hardening (PLAN §6): compaction, tokens for other scripts, access fixes."""

from pathlib import Path

import pytest

from paper_pile.core.ai.access import (
    MAX_OUTSIDE_SEEN,
    AccessPolicy,
    Grant,
    check_outside_path,
    grant_now,
    load_grant,
    revoke,
    save_grant,
)
from paper_pile.core.ai.context import (
    EditorSnapshot,
    build_context,
    cut_to_tokens,
    estimate_tokens,
)
from paper_pile.core.ai.engine import SUMMARIZING, AiEngine
from paper_pile.core.ai.fake import FakeProvider
from paper_pile.core.ai.provider import ProviderError
from paper_pile.core.config import Config
from paper_pile.core.vault import Vault


@pytest.fixture
def setup(tmp_path: Path) -> tuple[AiEngine, FakeProvider, Path]:
    v = Vault(tmp_path / "v")
    v.root.mkdir()
    v.create_note("a.md", "# A\nalpha body\n")
    fake = FakeProvider(delay=0)
    cfg_dir = tmp_path / "cfg"
    ai = AiEngine(v, Config(vault=v.root), provider_factory=lambda _c: fake, access_dir=cfg_dir)
    ai.allow()
    return ai, fake, cfg_dir


async def _ask(ai: AiEngine, text: str, **kw: object) -> None:
    out = ai.add_message(text)
    reply = ai.start_reply()
    async for _ in ai.answer(reply, out, EditorSnapshot(), **kw):  # type: ignore[arg-type]
        pass


# ---- tokens --------------------------------------------------------------------------------


def test_other_scripts_count_one_token_a_character() -> None:
    assert estimate_tokens("abcd" * 10) == 10
    assert estimate_tokens("বাংলা") == 5  # five characters, five tokens (not two)
    mixed = "x" * 1000 + "ব" * 100
    assert estimate_tokens(cut_to_tokens(mixed, 260)) <= 260
    assert cut_to_tokens("short", 100) == "short"


def test_a_bengali_note_is_cut_to_fit(tmp_path: Path) -> None:
    v = Vault(tmp_path / "v")
    v.root.mkdir()
    text = "আমি বাংলায় লিখি। " * 2000  # ~34k characters, nearly all one token each
    ctx = build_context(v, current_path="b.md", current_text=text, budget=3000, paths=["b.md"])
    assert ctx.parts[0].truncated and ctx.used <= 3000


# ---- compaction ----------------------------------------------------------------------------


async def test_compaction_keeps_the_earlier_summary_and_drops_old_turns(
    setup: tuple[AiEngine, FakeProvider, Path],
) -> None:
    ai, fake, _ = setup
    for n in range(10):
        await _ask(ai, f"message {n} " + "words " * 40)
    ai.summary, ai.summarized = "EARLIER SUMMARY", 2
    fake.reply = "new summary"
    assert await ai.compact(room=300)
    sent = fake.calls[-1][-1].content
    assert sent.startswith("Earlier summary:\nEARLIER SUMMARY")  # kept, though turns did not fit
    assert "message 9" not in sent  # the last KEEP_RECENT stay out of the summary
    assert "message 7" in sent and "message 1 " not in sent  # the oldest went first


async def test_a_failed_summary_waits_before_the_next_try(
    setup: tuple[AiEngine, FakeProvider, Path],
) -> None:
    ai, fake, _ = setup
    seen: list[str] = []
    for n in range(8):
        await _ask(ai, f"m{n} " + "words " * 30)
    fake.fail_calls = 1  # the summary call fails, the answer works
    calls = len(fake.calls)
    assert not await ai.compact_if_needed(200, seen.append)
    assert seen == [SUMMARIZING] and len(fake.calls) == calls + 1
    assert not await ai.compact_if_needed(200)  # no new try right away
    assert len(fake.calls) == calls + 1
    for n in range(2):
        await _ask(ai, f"later {n}")
    fake.reply = "summary"
    assert await ai.compact_if_needed(200)  # four messages later it tries again


async def test_compact_by_hand_reports_a_failure(
    setup: tuple[AiEngine, FakeProvider, Path],
) -> None:
    ai, fake, _ = setup
    for n in range(6):
        await _ask(ai, f"m{n}")
    fake.fail_calls = 1
    with pytest.raises(ProviderError):
        await ai.compact()


# ---- access --------------------------------------------------------------------------------


def test_revoke_then_allow_keeps_never_read(tmp_path: Path) -> None:
    vault, cfg = tmp_path / "v", tmp_path / "cfg"
    vault.mkdir()
    save_grant(vault, Grant("2026-10-29T10:00", [".md", ".txt"], ["/x"], ["private"]), cfg)
    revoke(vault, cfg)
    assert load_grant(vault, cfg) is None  # no access meanwhile
    again = grant_now(vault, cfg)
    assert again.exclude == ["private"] and again.file_types == [".md", ".txt"]
    assert again.allow_paths == []  # outside paths are granted afresh


async def test_compact_needs_access(setup: tuple[AiEngine, FakeProvider, Path]) -> None:
    from paper_pile.core.ai.access import AccessDeniedError

    ai, _fake, _ = setup
    for n in range(6):
        await _ask(ai, f"m{n}")
    ai.revoke_access()
    with pytest.raises(AccessDeniedError):
        await ai.compact()


def test_outside_grants_have_limits(tmp_path: Path) -> None:
    vault = tmp_path / "v"
    vault.mkdir()
    assert "whole disk or home" in check_outside_path("/", vault)
    assert "whole disk or home" in check_outside_path(str(Path.home()), vault)
    outside = tmp_path / "out"
    (outside / ".hidden").mkdir(parents=True)
    (outside / "keep.md").write_text("ok")
    (outside / ".token.md").write_text("secret")
    (outside / ".hidden" / "x.md").write_text("secret")
    assert "Hidden" in check_outside_path(str(outside / ".hidden"), vault)
    policy = AccessPolicy(vault, Grant("now", [".md"], [str(outside)]))
    assert [p.name for p in policy.outside_files()] == ["keep.md"]
    assert policy.read_outside(outside / ".token.md") is None


def test_a_huge_outside_folder_stops_early(tmp_path: Path) -> None:
    vault, outside = tmp_path / "v", tmp_path / "big"
    vault.mkdir()
    for d in range(3):
        folder = outside / f"d{d}"
        folder.mkdir(parents=True)
        for n in range(MAX_OUTSIDE_SEEN // 2):
            (folder / f"{n}.bin").touch()
    (outside / "d2" / "late.md").write_text("x")
    policy = AccessPolicy(vault, Grant("now", [".md"], [str(outside)]))
    assert policy.outside_files() == []  # stopped before the third folder
