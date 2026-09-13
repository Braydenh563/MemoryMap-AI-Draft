"""Crash-safe writes for the small pieces of state that live outside SQLite.

Why this exists: the database gets crash-safety for free from SQLite's own
transactions. Anything written straight to a file, `preferences.json` is the
one case in this app today, does not, unless the write itself is atomic.
`Path.write_text()` truncates the file before writing the new content, so a
crash or power loss mid-write leaves a half-written (often zero-byte) file
behind, not the old one. The fix is the standard shape: write the new content
to a temp file in the same directory, `fsync` it so it is actually on disk,
then `os.replace()` it over the real path, a rename within one filesystem is
atomic, so a reader (or the next process to start) always sees either the
whole old file or the whole new one, never a partial write.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any


def atomic_write_text(path: str | os.PathLike[str], text: str) -> None:
    """Replace `path`'s contents with `text`, atomically."""
    target = Path(path)
    fd, tmp_name = tempfile.mkstemp(
        dir=target.parent, prefix=f".{target.name}.", suffix=".tmp"
    )
    try:
        with os.fdopen(fd, "w") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_name, target)
    except BaseException:
        # A failed write must not leave a stray temp file behind, and must
        # not touch the real file at all.
        try:
            os.unlink(tmp_name)
        except OSError:
            # Best-effort cleanup: do not mask the original write/replace
            # failure if removing the temp file also fails.
            pass
        raise


def atomic_write_json(path: str | os.PathLike[str], data: Any, *, indent: int = 2) -> None:
    """Replace `path`'s contents with `data` as JSON, atomically."""
    atomic_write_text(path, json.dumps(data, indent=indent))
