"""Canonical long-term memory facade.

Both indexes share ``MemoryItem.memory_id`` and every lifecycle operation is
mirrored.  Semantic retrieval is optional at runtime, but a mock embedding is
never selected implicitly by the factory.
"""
from __future__ import annotations

import re
import time
from typing import Any

from memory.base import MemoryItem


def _normalize(text: str) -> str:
    t = re.sub(r"\s+", "", text.strip().lower())
    return re.sub(r"[,。.!!??;;、,:：\"'“”‘’()()【】\[\]]", "", t)


def _canonicalize(item: MemoryItem) -> MemoryItem:
    """Normalize trust metadata at the write boundary."""
    if item.source == "user" and item.provenance in {"", "agent"}:
        item.provenance = "owner_confirmed"
    elif item.source in {"email", "web", "document", "connector", "external"}:
        item.provenance = "external_observation"
        if item.status == "active":
            item.status = "quarantined"
    elif item.provenance in {"", "agent"}:
        item.provenance = "agent_inference"
    item.confidence = max(0.0, min(1.0, float(item.confidence)))
    return item


class HybridMemory:
    def __init__(self, keyword: Any, semantic: Any | None = None,
                 min_similarity: float = 0.35) -> None:
        self._kw = keyword
        self._sem = semantic
        self.min_similarity = min_similarity

    def store(self, item: MemoryItem) -> None:
        item = _canonicalize(item)
        if item.kind == "preference":
            try:
                from memory.conflict import resolve_preference_conflict
                resolve_preference_conflict(self, item.content, item.scope or "")
            except Exception:
                pass
        self._kw.store(item)
        try:
            if self._sem is not None:
                self._sem.store(item)
        except Exception:
            # Do not leave a keyword row claiming semantic durability.
            self._kw.delete_memory(item.memory_id)
            raise

    def retrieve(self, query: str, k: int = 5, scope: str | None = None) -> list[MemoryItem]:
        kw_fn = getattr(self._kw, "fts_retrieve", self._kw.retrieve)
        kw_hits = kw_fn(query, k=k, scope=scope)
        sem_hits: list[MemoryItem] = []
        if self._sem is not None:
            try:
                sem_hits = self._sem.retrieve(query, k=k, scope=scope,
                                              min_similarity=self.min_similarity)
            except TypeError:
                sem_hits = self._sem.retrieve(query, k=k, scope=scope)
        candidates = sem_hits + kw_hits
        kept: list[str] = []
        scored: list[tuple[float, MemoryItem]] = []
        for item in candidates:
            if item.status != "active" or not item.content.strip():
                continue
            norm = _normalize(item.content)
            if not norm or any(norm == old or norm in old or old in norm for old in kept):
                continue
            kept.append(norm)
            provenance_weight = {
                "owner_confirmed": 1.0, "system": 0.95,
                "agent_inference": 0.82, "external_observation": 0.35,
            }.get(item.provenance, 0.6)
            score = (getattr(item, "similarity", 0.0) * 0.62
                     + item.confidence * 0.20 + item.importance * 0.12
                     + provenance_weight * 0.06)
            scored.append((score, item))
        scored.sort(key=lambda pair: pair[0], reverse=True)
        return [item for _, item in scored[:k]]

    def list_by_kind(self, kind: str, limit: int = 50) -> list[dict]:
        fn = getattr(self._kw, "list_by_kind", None)
        return fn(kind, limit=limit) if callable(fn) else []

    def list_all(self, kind: str | None = None, limit: int = 200) -> list[dict]:
        fn = getattr(self._kw, "list_all", None)
        return fn(kind, limit) if callable(fn) else []

    def _resolve_id(self, row_id: int) -> str | None:
        getter = getattr(self._kw, "get_by_row_id", None)
        if callable(getter):
            row = getter(row_id)
            return row.get("memory_id") if row else None
        conn = getattr(self._kw, "_conn", None)
        if conn is not None:
            row = conn.execute("SELECT memory_id FROM memories WHERE id=?", (int(row_id),)).fetchone()
            return row[0] if row else None
        return None

    def delete_by_id(self, row_id: int) -> bool:
        memory_id = self._resolve_id(row_id)
        return self.delete_by_memory_id(memory_id) if memory_id else False

    def delete_by_memory_id(self, memory_id: str | None) -> bool:
        if not memory_id:
            return False
        results = []
        for backend in (self._kw, self._sem):
            fn = getattr(backend, "delete_memory", None)
            if callable(fn):
                results.append(bool(fn(memory_id)))
        return any(results)

    def update_by_id(self, row_id: int, content: str) -> bool:
        memory_id = self._resolve_id(row_id)
        if not memory_id:
            return False
        return self.update_memory(memory_id, content=(content or "").strip())

    def update_memory(self, memory_id: str, **fields) -> bool:
        changed = []
        for backend in (self._kw, self._sem):
            fn = getattr(backend, "update_memory", None)
            if callable(fn):
                changed.append(bool(fn(memory_id, **fields)))
        return any(changed)

    def supersede(self, memory_id: str, replacement: MemoryItem) -> None:
        replacement.supersedes_id = memory_id
        self.update_memory(memory_id, status="superseded")
        self.store(replacement)

    def delete_by_content(self, kind: str, content: str) -> int:
        rows = self.list_by_kind(kind, limit=10000)
        ids = [r.get("memory_id") for r in rows if r.get("content") == content]
        for memory_id in ids:
            self.delete_by_memory_id(memory_id)
        return len(ids)

    def delete_by_content_prefix(self, kind: str, prefix: str) -> int:
        rows = self.list_by_kind(kind, limit=10000)
        ids = [r.get("memory_id") for r in rows if (r.get("content") or "").startswith(prefix)]
        for memory_id in ids:
            self.delete_by_memory_id(memory_id)
        return len(ids)

    def export(self, scope: str | None = None, include_deleted: bool = False) -> list[dict]:
        if include_deleted and getattr(self._kw, "_conn", None) is not None:
            rows = [dict(r) for r in self._kw._conn.execute(
                "SELECT * FROM memories ORDER BY created_at DESC LIMIT 10000").fetchall()]
        else:
            rows = self.list_all(limit=10000)
        return [r for r in rows if (scope is None or r.get("scope") in {"", scope})
                and (include_deleted or r.get("status") == "active")]

    def forget(self, min_importance: float = 0.2, max_age_days: float = 30.0) -> int:
        ids = [r.get("memory_id") for r in self.list_all(limit=10000)
               if r.get("importance", 1.0) < min_importance
               and r.get("created_at", time.time()) < time.time() - max_age_days * 86400]
        for memory_id in ids:
            self.delete_by_memory_id(memory_id)
        return len(ids)

    def close(self) -> None:
        for backend in (self._kw, self._sem):
            close = getattr(backend, "close", None)
            if callable(close):
                close()
