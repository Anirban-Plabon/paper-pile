"""P27.1: the automatic context window fits this machine (measured once per model)."""

from pathlib import Path

import pytest

from paper_pile.core.ai.engine import AiEngine
from paper_pile.core.ai.fake import FakeProvider
from paper_pile.core.ai.window import WindowCache, measure_window
from paper_pile.core.config import Config
from paper_pile.core.vault import Vault

# gemma4:12b on an 8 GB laptop GPU (measured 2026-10-31): 79 % in VRAM at 8k, 75 % at 32k
LAPTOP = {8192: 0.79, 16384: 0.79, 32768: 0.75, 65536: 0.70}


def engine(tmp_path: Path, fake: FakeProvider, windows: WindowCache | None = None) -> AiEngine:
    root = tmp_path / "v"
    root.mkdir(exist_ok=True)
    return AiEngine(
        Vault(root), Config(vault=root), provider_factory=lambda _c: fake, windows=windows
    )


@pytest.mark.parametrize(
    ("shares", "limit", "expected"),
    [
        (LAPTOP, 262144, 32768),  # 64k moves 9 % more off the GPU: too much
        (LAPTOP, 16384, 16384),  # never above the model's own limit
        ({8192: 1.0, 16384: 1.0, 32768: 1.0, 65536: 0.97}, 131072, 65536),  # fits fully
        ({8192: 1.0, 16384: 0.6}, 131072, 8192),  # the first step already spills
        ({8192: 0.0, 16384: 0.0}, 131072, 8192),  # CPU only
        ({}, 131072, None),  # nothing known (Ollama down): measured again later
    ],
)
async def test_measure_window(shares: dict[int, float], limit: int, expected: int | None) -> None:
    fake = FakeProvider(delay=0)
    fake.gpu_share = shares
    assert await measure_window(fake.memory_use, "m", limit) == expected


async def test_the_automatic_window_is_measured_once_and_sent(tmp_path: Path) -> None:
    fake = FakeProvider(delay=0)
    fake.max_context, fake.gpu_share = 262144, LAPTOP
    cache = WindowCache(tmp_path / "windows.json")
    ai = engine(tmp_path, fake, cache)
    assert await ai.window() == 32768
    assert fake.measured == [8192, 16384, 32768, 65536]
    assert await ai.window() == 32768 and len(fake.measured) == 4  # cached
    parts = [p async for p in ai.stream([], max_answer=10)]
    assert parts and fake.options is not None and fake.options.num_ctx == 32768
    fresh = FakeProvider(delay=0)  # the next start of the app: read from the file
    fresh.max_context = 262144
    assert await engine(tmp_path, fresh, WindowCache(cache.path)).window() == 32768
    assert fresh.measured == []


async def test_a_failed_measurement_is_not_kept(tmp_path: Path) -> None:
    fake = FakeProvider(delay=0)
    fake.max_context = 262144  # gpu_share empty: Ollama could not load it
    ai = engine(tmp_path, fake)
    assert await ai.window() == 8192
    fake.gpu_share = LAPTOP
    assert await ai.window() == 32768


async def test_a_chosen_window_is_never_measured(tmp_path: Path) -> None:
    fake = FakeProvider(delay=0)
    fake.gpu_share = LAPTOP
    ai = engine(tmp_path, fake)
    ai.config.set("ai.num_ctx", 4096)  # type: ignore[union-attr]
    assert await ai.window() == 4096 and fake.measured == []


def test_a_broken_cache_file_is_ignored(tmp_path: Path) -> None:
    path = tmp_path / "windows.json"
    path.write_text("{not json")
    assert WindowCache(path).get("h", "m") is None
