"""资源互斥锁 —— 防止多个 agent 同时写同一资源(文件/数据库/外部服务)。

设计原则:
  - 锁的粒度是"资源路径"(字符串 key),而不是全局大锁。
  - 读操作不加锁(只有写/破坏操作需要)。
  - 加锁失败时默认拒绝(fail-safe),而不是等待(防止长时间阻塞整个 agent)。
  - 锁释放后等待者自动获得锁,FIFO 顺序。

用法(在 WorkerAgent / loop 中集成):
    async with resource_lock.acquire("path/to/file.txt"):
        # 安全地写文件

也可以用 try_acquire 做非阻塞尝试:
    if not await resource_lock.try_acquire("file.txt", timeout=5.0):
        return CapabilityResult(ok=False, error="资源被占用,稍后重试")
"""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import AsyncIterator


class ResourceLock:
    def __init__(self) -> None:
        self._locks: dict[str, asyncio.Lock] = {}

    def _get(self, key: str) -> asyncio.Lock:
        if key not in self._locks:
            self._locks[key] = asyncio.Lock()
        return self._locks[key]

    def _maybe_prune(self, key: str) -> None:
        """锁既不被持有、也无等待者时,从字典移除,避免长跑无界增长。

        在 asyncio 单线程下安全:_get 与 acquire() 之间无 await,acquire 的快速路径
        不会让出事件循环;真正在等待的任务会先进入 _waiters,因而不会被误删。
        """
        lock = self._locks.get(key)
        if lock is None:
            return
        waiters = getattr(lock, "_waiters", None)
        if not lock.locked() and not waiters:
            self._locks.pop(key, None)

    @asynccontextmanager
    async def acquire(self, key: str) -> AsyncIterator[None]:
        """阻塞直到获得锁(FIFO)。推荐用于已知会等待的场景。"""
        lock = self._get(key)
        async with lock:
            yield
        self._maybe_prune(key)

    async def try_acquire(self, key: str, timeout: float = 3.0) -> "ResourceGuard | None":
        """尝试在 timeout 秒内获取锁。获取成功返回 Guard(需手动 release),否则返回 None。"""
        lock = self._get(key)
        try:
            await asyncio.wait_for(lock.acquire(), timeout=timeout)
            return ResourceGuard(self, key, lock)
        except asyncio.TimeoutError:
            self._maybe_prune(key)
            return None

    def is_locked(self, key: str) -> bool:
        lock = self._locks.get(key)
        return lock is not None and lock.locked()

    def locked_keys(self) -> list[str]:
        return [k for k, v in self._locks.items() if v.locked()]


class ResourceGuard:
    """try_acquire 的返回值,用 async with 或手动 release 释放。"""
    def __init__(self, owner: "ResourceLock", key: str, lock: asyncio.Lock) -> None:
        self._owner = owner
        self._key = key
        self._lock = lock

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        self.release()

    def release(self) -> None:
        if self._lock.locked():
            self._lock.release()
        self._owner._maybe_prune(self._key)


# 全局默认实例(可在组合根替换)
default_lock = ResourceLock()
