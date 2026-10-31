"""The automatic context window (``ai.num_ctx`` = 0, PLAN §4.26): the largest step at which the
model still sits on the GPU as much as it does at 8k, measured once per model on this machine.

A bigger window costs memory for its KV cache; when that pushes more of the model off the GPU,
every answer gets slower. Ollama tells how much of a loaded model is in VRAM, so each step is
loaded once and compared with the 8k load. The result is cached (per host and model, for
``MAX_AGE_S``), so the measuring loads happen once, not per message.
"""

import json
import logging
import time
from collections.abc import Awaitable, Callable
from pathlib import Path

log = logging.getLogger("paper_pile.ai.window")

BASE_WINDOW = 8192  # always affordable; the step the others are compared with
WINDOW_STEPS = (16384, 32768, 65536)  # tried in turn, after the base
GPU_SLACK = 0.05  # a step may move at most this share of the model off the GPU
MAX_AGE_S = 30 * 24 * 3600.0  # measured again after this long (drivers, other GPU users)

# (model, num_ctx) -> (size, size in VRAM) in bytes once loaded; None when unknown
MemoryProbe = Callable[[str, int], Awaitable[tuple[int, int] | None]]


def gpu_share(use: tuple[int, int] | None) -> float | None:
    if use is None or use[0] <= 0:
        return None
    return use[1] / use[0]


async def measure_window(probe: MemoryProbe, model: str, limit: int) -> int | None:
    """The largest step up to ``limit`` that keeps the model on the GPU as much as the base
    does (within ``GPU_SLACK``); the base when the model runs on the CPU only; None when the
    base load could not be measured (Ollama down: try again later)."""
    base = gpu_share(await probe(model, BASE_WINDOW))
    if base is None:
        return None
    if base == 0:  # CPU only: a bigger window just takes RAM, and attention gets slower
        return BASE_WINDOW
    chosen = BASE_WINDOW
    for step in WINDOW_STEPS:
        if step > limit:
            break
        share = gpu_share(await probe(model, step))
        log.info("%s at %d: %.2f of it on the GPU (8k: %.2f)", model, step, share or 0, base)
        if share is None or share < base - GPU_SLACK:
            break
        chosen = step
    return chosen


class WindowCache:
    """Measured windows by ``host|model``, kept in a JSON file (in memory only without one)."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path
        self._data: dict[str, dict[str, float]] = self._load()

    def get(self, host: str, model: str) -> int | None:
        entry = self._data.get(f"{host}|{model}")
        if entry is None or time.time() - entry.get("at", 0) > MAX_AGE_S:
            return None
        return int(entry["window"])

    def put(self, host: str, model: str, window: int) -> None:
        self._data[f"{host}|{model}"] = {"window": window, "at": time.time()}
        if self.path is None:
            return
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(self._data, indent=1), encoding="utf-8")
        except OSError as exc:
            log.info("could not save measured windows: %s", exc)

    def _load(self) -> dict[str, dict[str, float]]:
        if self.path is None:
            return {}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        if not isinstance(data, dict):
            return {}
        return {
            k: v
            for k, v in data.items()
            if isinstance(v, dict) and isinstance(v.get("window"), int)
        }
