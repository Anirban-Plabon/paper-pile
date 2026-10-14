"""Small filesystem helpers shared by core modules."""

import contextlib
import os
import tempfile
from pathlib import Path

DEFAULT_FILE_MODE = 0o644


def atomic_write_bytes(path: Path, data: bytes) -> None:
    """Write ``data`` to ``path`` so readers see either the old or the new content, never a mix.

    Temp file in the same directory (hidden name), fsync, then ``os.replace``. The mode of an
    existing file is kept. On any failure the temp file is removed and ``path`` is untouched.
    """
    try:
        mode = path.stat().st_mode & 0o7777
    except FileNotFoundError:
        mode = DEFAULT_FILE_MODE
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
    _fsync_dir(path.parent)


def _fsync_dir(directory: Path) -> None:
    """Best effort: persist the rename itself."""
    with contextlib.suppress(OSError):
        fd = os.open(directory, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
