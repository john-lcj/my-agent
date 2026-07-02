"""Small size-based rotation helpers for local text logs."""
from __future__ import annotations

import os


DEFAULT_MAX_BYTES = 20 * 1024 * 1024
DEFAULT_BACKUPS = 3


def _positive_int(raw: str | None, default: int) -> int:
    try:
        value = int(str(raw or "").strip())
    except Exception:
        return default
    return value if value > 0 else default


def max_bytes() -> int:
    return _positive_int(os.environ.get("AGENT_LOG_MAX_BYTES"), DEFAULT_MAX_BYTES)


def backup_count() -> int:
    return _positive_int(os.environ.get("AGENT_LOG_BACKUPS"), DEFAULT_BACKUPS)


def rotate_if_needed(path: str, *, limit: int | None = None, backups: int | None = None) -> bool:
    """Rotate path when it is at or above limit. Returns True if rotation happened."""
    limit = limit or max_bytes()
    backups = backups if backups is not None else backup_count()
    if backups <= 0 or limit <= 0 or not os.path.isfile(path):
        return False
    try:
        if os.path.getsize(path) < limit:
            return False
        parent = os.path.dirname(path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        oldest = f"{path}.{backups}"
        if os.path.exists(oldest):
            os.remove(oldest)
        for idx in range(backups - 1, 0, -1):
            src = f"{path}.{idx}"
            if os.path.exists(src):
                os.replace(src, f"{path}.{idx + 1}")
        os.replace(path, f"{path}.1")
        return True
    except Exception:
        return False


def append_text(path: str, text: str, *, limit: int | None = None, backups: int | None = None) -> None:
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    rotate_if_needed(path, limit=limit, backups=backups)
    with open(path, "a", encoding="utf-8") as f:
        f.write(text)
