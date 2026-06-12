"""语义记忆(向量检索 / RAG)。

架构:
- 向量存储:SQLite BLOB(numpy float32 序列化),零额外运行时依赖。
- 相似度:numpy 余弦相似度,内存计算(记忆条数在万级以内完全够用)。
- 嵌入:由外部注入的 embed_fn 生成(默认用 OpenAI text-embedding-3-small;
  也可以注入 MockEmbed 做确定性测试)。

学习点:
- embedding:把文本语义映射成高维向量,语义相似 = 向量距离近。
- RAG 完整链路:store(文本→向量入库) → retrieve(query→向量→最近邻) → 注入上下文。
- 余弦相似度:dot(a,b)/(|a||b|),只看方向,不看长度,适合文本语义比较。
"""
from __future__ import annotations

import json
import os
import sqlite3
import time
from typing import Callable, List, Optional

import numpy as np

from memory.base import MemoryItem

# 嵌入向量的维度(text-embedding-3-small 输出 1536 维)。
EMBED_DIM = 1536


class VectorMemory:
    def __init__(
        self,
        embed_fn: Callable[[str], List[float]],
        db_path: str = "logs/vectors.db",
    ) -> None:
        self.embed_fn = embed_fn
        self.db_path = db_path
        parent = os.path.dirname(db_path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        self._conn = sqlite3.connect(db_path)
        self._conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self) -> None:
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS vectors (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                kind TEXT NOT NULL,
                content TEXT NOT NULL,
                importance REAL NOT NULL DEFAULT 0.5,
                created_at REAL NOT NULL,
                last_used REAL NOT NULL,
                vec BLOB NOT NULL
            )
            """
        )
        self._conn.commit()

    def store(self, item: MemoryItem) -> None:
        vec = self._to_vec(item.content)
        self._conn.execute(
            "INSERT INTO vectors (kind, content, importance, created_at, last_used, vec) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (item.kind, item.content, item.importance,
             item.created_at, item.last_used, _pack(vec)),
        )
        self._conn.commit()

    def retrieve(self, query: str, k: int = 5) -> list[MemoryItem]:
        q_vec = np.array(self._to_vec(query), dtype=np.float32)
        rows = self._conn.execute(
            "SELECT id, kind, content, importance, created_at, last_used, vec FROM vectors"
        ).fetchall()
        if not rows:
            return []

        scored: list[tuple[float, sqlite3.Row]] = []
        for row in rows:
            rv = _unpack(row["vec"])
            sim = _cosine(q_vec, rv)
            scored.append((sim, row))

        scored.sort(key=lambda x: x[0], reverse=True)
        top = scored[:k]

        now = time.time()
        items: list[MemoryItem] = []
        for sim, row in top:
            self._conn.execute(
                "UPDATE vectors SET last_used = ? WHERE id = ?", (now, row["id"])
            )
            items.append(MemoryItem(
                kind=row["kind"], content=row["content"],
                importance=row["importance"],
                created_at=row["created_at"], last_used=now,
            ))
        self._conn.commit()
        return items

    def delete_by_content(self, kind: str, content: str) -> int:
        """按 kind+内容精确删除(与关键词后端同步删,保持双后端一致)。"""
        cur = self._conn.execute(
            "DELETE FROM vectors WHERE kind = ? AND content = ?", (kind, content))
        self._conn.commit()
        return cur.rowcount

    def delete_by_content_prefix(self, kind: str, prefix: str) -> int:
        """按 kind+内容前缀删除(个人文档重新索引时清旧块)。"""
        like = prefix.replace("%", r"\%").replace("_", r"\_") + "%"
        cur = self._conn.execute(
            r"DELETE FROM vectors WHERE kind = ? AND content LIKE ? ESCAPE '\'",
            (kind, like))
        self._conn.commit()
        return cur.rowcount

    def forget(self, min_importance: float = 0.2, max_age_days: float = 30.0) -> int:
        cutoff = time.time() - max_age_days * 86400
        cur = self._conn.execute(
            "DELETE FROM vectors WHERE importance < ? AND last_used < ?",
            (min_importance, cutoff),
        )
        self._conn.commit()
        return cur.rowcount

    def close(self) -> None:
        self._conn.close()

    def _to_vec(self, text: str) -> list[float]:
        result = self.embed_fn(text)
        if len(result) != EMBED_DIM:
            # 若 embed_fn 返回不同维度(如 mock),补零或截断以保持一致。
            if len(result) < EMBED_DIM:
                result = result + [0.0] * (EMBED_DIM - len(result))
            else:
                result = result[:EMBED_DIM]
        return result


# ── 辅助 ──────────────────────────────────────────────────────────────────────

def _pack(vec: list[float]) -> bytes:
    return np.array(vec, dtype=np.float32).tobytes()


def _unpack(blob: bytes) -> np.ndarray:
    return np.frombuffer(blob, dtype=np.float32)


def _cosine(a: np.ndarray, b: np.ndarray) -> float:
    na, nb = np.linalg.norm(a), np.linalg.norm(b)
    if na == 0 or nb == 0:
        return 0.0
    return float(np.dot(a, b) / (na * nb))


# ── Embed 实现 ─────────────────────────────────────────────────────────────────

def openai_embed_fn(api_key: Optional[str] = None, model: str = "text-embedding-3-small"):
    """工厂:返回一个调用 OpenAI embedding API 的 embed_fn。"""
    import os as _os
    key = api_key or _os.environ.get("OPENAI_API_KEY") or _os.environ.get("DEEPSEEK_API_KEY")

    async def _embed_async(text: str) -> list[float]:
        from openai import AsyncOpenAI
        client = AsyncOpenAI(api_key=key)
        resp = await client.embeddings.create(model=model, input=text)
        return resp.data[0].embedding

    # 同步包装(store/retrieve 目前是同步调用,异步版本留给进阶)
    import asyncio

    def embed(text: str) -> list[float]:
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # 在异步上下文里用 run_in_executor 避免嵌套 event loop
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor(1) as pool:
                    fut = pool.submit(asyncio.run, _embed_async(text))
                    return fut.result()
            return loop.run_until_complete(_embed_async(text))
        except Exception:
            return [0.0] * EMBED_DIM

    return embed


class MockEmbed:
    """确定性 embed(供回归测试用):把文本哈希散布到向量里。"""

    def __call__(self, text: str) -> list[float]:
        import hashlib
        digest = hashlib.sha256(text.encode()).digest()
        rng = np.random.default_rng(int.from_bytes(digest[:8], "big"))
        vec = rng.standard_normal(EMBED_DIM).astype(np.float32)
        vec /= np.linalg.norm(vec) + 1e-9
        return vec.tolist()
