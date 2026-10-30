"""P26.11: answer commands on a note too long for the window — read part by part (AI_EDITS §5)."""

from pathlib import Path

from paper_pile.core.ai.commands import ai_command
from paper_pile.core.ai.engine import AiEngine
from paper_pile.core.ai.fake import FakeProvider
from paper_pile.core.ai.longtext import MAX_PARTS, condensed
from paper_pile.core.config import Config
from paper_pile.core.vault import Vault

SUMMARIZE = ai_command("ai-summarize")
assert SUMMARIZE is not None


def engine(tmp_path: Path, fake: FakeProvider) -> AiEngine:
    root = tmp_path / "v"
    root.mkdir()
    config = Config(vault=root)
    config.set("ai.num_ctx", 2048)
    ai = AiEngine(Vault(root), config, provider_factory=lambda _c: fake)
    ai.allow()
    return ai


def note(sections: int) -> str:
    body = " ".join(f"word{i}" for i in range(260))
    return "".join(f"## Part {n}\n\n{body}.\n\n" for n in range(1, sections + 1))


async def test_a_text_that_fits_is_not_condensed(tmp_path: Path) -> None:
    fake = FakeProvider(delay=0, script=[])
    assert await condensed(engine(tmp_path, fake), SUMMARIZE, "Short text.") is None
    assert fake.calls == []


async def test_a_long_text_is_read_part_by_part(tmp_path: Path) -> None:
    fake = FakeProvider(delay=0, script=[f"summary {n}" for n in range(1, 4)])
    seen: list[tuple[int, int]] = []
    ai = engine(tmp_path, fake)
    out = await condensed(ai, SUMMARIZE, note(3), lambda n, t: seen.append((n, t)))
    assert out is not None and "Part 1:\nsummary 1" in out and "Part 3:\nsummary 3" in out
    assert seen == [(1, 3), (2, 3), (3, 3)] and len(fake.calls) == 3
    assert fake.options_seen[0] is not None and fake.options_seen[0].think is False


async def test_more_than_eight_parts_reads_the_first_eight(tmp_path: Path) -> None:
    fake = FakeProvider(delay=0, script=[f"s{n}" for n in range(1, MAX_PARTS + 1)])
    out = await condensed(engine(tmp_path, fake), SUMMARIZE, note(12))
    assert out is not None and f"the first {MAX_PARTS} of 12 parts" in out
    assert len(fake.calls) == MAX_PARTS
