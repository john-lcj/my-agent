"""Small cross-process locks used by the desktop runtime.

The lock file is intentionally kept after release. Removing a lock file can
create an inode race where two processes both believe they own the same lock.
"""
from __future__ import annotations

import json
import os
import socket
import time
from typing import Any


class ProcessFileLock:
    def __init__(self, path: str, *, role: str) -> None:
        self.path = os.path.abspath(path)
        self.role = role
        self._file = None

    @property
    def acquired(self) -> bool:
        return self._file is not None

    def acquire(self, metadata: dict[str, Any] | None = None) -> bool:
        if self._file is not None:
            return True
        parent = os.path.dirname(self.path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        handle = open(self.path, "a+", encoding="utf-8")
        try:
            self._lock(handle)
        except (BlockingIOError, OSError):
            handle.close()
            return False

        payload = {
            "pid": os.getpid(),
            "role": self.role,
            "hostname": socket.gethostname(),
            "acquired_at": time.time(),
        }
        payload.update(metadata or {})
        handle.seek(0)
        handle.truncate()
        json.dump(payload, handle, ensure_ascii=True, sort_keys=True)
        handle.write("\n")
        handle.flush()
        try:
            os.fsync(handle.fileno())
        except OSError:
            pass
        self._file = handle
        return True

    def release(self) -> None:
        handle = self._file
        if handle is None:
            return
        self._file = None
        try:
            handle.seek(0)
            handle.truncate()
            handle.flush()
        except OSError:
            pass
        try:
            self._unlock(handle)
        finally:
            handle.close()

    def owner(self) -> dict[str, Any]:
        try:
            with open(self.path, "r", encoding="utf-8") as handle:
                value = json.load(handle)
            return value if isinstance(value, dict) else {}
        except Exception:
            return {}

    @staticmethod
    def _lock(handle) -> None:
        if os.name == "nt":
            import msvcrt

            handle.seek(0)
            if not handle.read(1):
                handle.seek(0)
                handle.write("\0")
                handle.flush()
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            return

        import fcntl

        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)

    @staticmethod
    def _unlock(handle) -> None:
        if os.name == "nt":
            import msvcrt

            handle.seek(0)
            try:
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            except OSError:
                pass
            return

        import fcntl

        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    def __enter__(self):
        if not self.acquire():
            raise RuntimeError(f"{self.role} lock is already held: {self.path}")
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.release()
