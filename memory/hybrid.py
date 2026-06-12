"""混合长期记忆 —— SQLite 关键词 + 向量语义,双写双检索。

store/forget 同步写入两套后端;retrieve 合并两路 Top-K,按内容去重后返回。
"""
from __future__ import annotations

import re
from typing import Any

from memory.base import MemoryItem


def _normalize(text: str) -> str:
    """归一化内容用于近重复判断:去空白、去标点、转小写。"""
    t = re.sub(r"\s+", "", text.strip().lower())
    return re.sub(r"[,。.!!??;;、,:：\"'“”‘’()()【】\[\]]", "", t)


class HybridMemory:
    def __init__(self, keyword: Any, semantic: Any) -> None:
        self._kw = keyword
        self._sem = semantic

    def store(self, item: MemoryItem) -> None:
        self._kw.store(item)
        self._sem.store(item)

    def retrieve(self, query: str, k: int = 5) -> list[MemoryItem]:
        kw_hits = self._kw.retrieve(query, k=k)
        sem_hits = self._sem.retrieve(query, k=k)
        kept_norm: list[str] = []
        merged: list[MemoryItem] = []
        # 向量结果优先(语义相近),再补关键词命中。
        # 近重复去重:归一化后相等、或互为子串,都视为重复,避免"喜欢咖啡 / 喜欢喝咖啡。"挤占名额。
        for item in sem_hits + kw_hits:
            content = item.content.strip()
            if not content:
                continue
            norm = _normalize(content)
            if not norm:
                continue
            if any(norm == kn or norm in kn or kn in norm for kn in kept_norm):
                continue
            kept_norm.append(norm)
            merged.append(item)
            if len(merged) >= k:
                break
        return merged

    def list_by_kind(self, kind: str, limit: int = 50) -> list[dict]:
        """按 kind 列出(以关键词后端为准,双写保证两边一致)。"""
        fn = getattr(self._kw, "list_by_kind", None)
        return fn(kind, limit=limit) if callable(fn) else []

    def delete_by_content(self, kind: str, content: str) -> int:
        """双后端按 kind+内容删除,返回总删除条数。"""
        n = 0
        for backend in (self._kw, self._sem):
            fn = getattr(backend, "delete_by_content", None)
            if callable(fn):
                n += fn(kind, content)
        return n

    def delete_by_content_prefix(self, kind: str, prefix: str) -> int:
        """双后端按 kind+内容前缀删除,返回总删除条数。"""
        n = 0
        for backend in (self._kw, self._sem):
            fn = getattr(backend, "delete_by_content_prefix", None)
            if callable(fn):
                n += fn(kind, prefix)
        return n

    def forget(self, min_importance: float = 0.2, max_age_days: float = 30.0) -> int:
        n1 = self._kw.forget(min_importance=min_importance, max_age_days=max_age_days)
        n2 = self._sem.forget(min_importance=min_importance, max_age_days=max_age_days)
        return n1 + n2

    def close(self) -> None:
        for backend in (self._kw, self._sem):
            close = getattr(backend, "close", None)
            if callable(close):
                close()
