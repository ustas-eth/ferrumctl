from __future__ import annotations

import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Any


def rollout_path(path: Path) -> Path:
    """Choose the live file when both representations of a rollout exist."""
    if path.name.endswith(".jsonl.zst"):
        plain = path.with_suffix("")
        return plain if plain.is_file() else path
    if path.name.endswith(".jsonl") and not path.is_file():
        compressed = path.with_suffix(".jsonl.zst")
        if compressed.is_file():
            return compressed
    return path


@contextmanager
def open_rollout(path: Path, mode: str, **kwargs: Any):
    """Open one exact representation without materializing it on disk."""
    if not path.name.endswith(".zst"):
        with path.open(mode, **kwargs) as stream:
            yield stream
        return
    try:
        if sys.version_info >= (3, 14):
            from compression import zstd
        else:
            from backports import zstd
    except ImportError as exc:
        raise OSError("Zstandard support is unavailable in this Python installation") from exc
    try:
        with zstd.open(path, mode, **kwargs) as stream:
            yield stream
    except (EOFError, zstd.ZstdError) as exc:
        raise OSError(f"invalid Zstandard stream: {exc}") from exc
