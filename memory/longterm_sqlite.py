"""长期记忆(SQLite 后端)。

务实原则:SQLite 能解决的,先别上向量库。关键词 + 重要性 + 时间近度
就能取回大部分有用记忆,也让你先理解"记忆的生命周期":
存入 -> 被检索(刷新使用时间)-> 低价值且久未使用时被遗忘清理。

接口与 memory.base.Memory 一致,将来换成向量后端对上层透明。
"""
from __future__ import annotations

import os
import sqlite3
import time

from memory.base import MemoryItem


class SQLiteMemory:
    def __init__(self, db_path: str = "logs/memory.db") -> None:
        self.db_path = db_path
        parent = os.path.dirname(db_path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self) -> None:
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS memories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                kind TEXT NOT NULL,
                content TEXT NOT NULL,
                importance REAL NOT NULL DEFAULT 0.5,
                source TEXT NOT NULL DEFAULT 'agent',
                created_at REAL NOT NULL,
                last_used REAL NOT NULL
            )
            """
        )
        # 兼容旧库:补 source / scope 列
        cols = {r[1] for r in self._conn.execute("PRAGMA table_info(memories)").fetchall()}
        if "source" not in cols:
            self._conn.execute("ALTER TABLE memories ADD COLUMN source TEXT NOT NULL DEFAULT 'agent'")
        if "scope" not in cols:
            self._conn.execute("ALTER TABLE memories ADD COLUMN scope TEXT NOT NULL DEFAULT ''")
        if "expires_at" not in cols:
            self._conn.execute("ALTER TABLE memories ADD COLUMN expires_at REAL")
        self._conn.commit()

    def store(self, item: MemoryItem) -> None:
        exp = getattr(item, "expires_at", None)
        if exp is None and item.kind == "fact":
            from memory.policy import ttl_for_kind
            ttl = ttl_for_kind("fact")
            if ttl:
                exp = item.created_at + ttl
        self._conn.execute(
            "INSERT INTO memories (kind, content, importance, source, scope, created_at, last_used, expires_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (item.kind, item.content, item.importance, item.source or "agent",
             getattr(item, "scope", "") or "", item.created_at, item.last_used, exp),
        )
        self._conn.commit()

    def retrieve(self, query: str, k: int = 5, scope: str | None = None) -> list[MemoryItem]:
        tokens = [t for t in query.replace("，", " ").replace(",", " ").split() if t]
        # 隔离:scope 非 None 时只取 当前 scope 或 全局('') 的记忆;None=不过滤(取全部)。
        scope_sql = ""
        scope_params: list = []
        if scope is not None:
            scope_sql = " AND (scope = ? OR scope = '')"
            scope_params = [scope]
        rows: list[sqlite3.Row]
        if tokens:
            where = " OR ".join(["content LIKE ?"] * len(tokens))
            params = [f"%{t}%" for t in tokens]
            rows = self._conn.execute(
                f"SELECT * FROM memories WHERE ({where}){scope_sql} "
                f"ORDER BY importance DESC, last_used DESC LIMIT ?",
                (*params, *scope_params, k),
            ).fetchall()
        else:
            where_only = scope_sql.replace(" AND ", " WHERE ", 1) if scope_sql else ""
            rows = self._conn.execute(
                f"SELECT * FROM memories{where_only} ORDER BY importance DESC, last_used DESC LIMIT ?",
                (*scope_params, k),
            ).fetchall()

        now = time.time()
        items: list[MemoryItem] = []
        for r in rows:
            exp = r["expires_at"] if "expires_at" in r.keys() else None
            expired = exp is not None and float(exp) < now
            if expired and r["kind"] != "fact":
                continue
            if not expired:
                self._conn.execute("UPDATE memories SET last_used = ? WHERE id = ?", (now, r["id"]))
            item = MemoryItem(
                kind=r["kind"], content=r["content"],
                importance=r["importance"],
                source=r["source"] if "source" in r.keys() else "agent",
                scope=r["scope"] if "scope" in r.keys() else "",
                created_at=r["created_at"], last_used=now,
                expires_at=float(exp) if exp is not None else None,
                stale=bool(expired),
            )
            if expired:
                item.content = f"【需刷新·已过期】{item.content}"
            items.append(item)
        self._conn.commit()
        return items

    def list_by_kind(self, kind: str, limit: int = 50) -> list[dict]:
        """按 kind 列出记忆(含行 id,供管理界面查看/删除)。"""
        rows = self._conn.execute(
            "SELECT * FROM memories WHERE kind = ? "
            "ORDER BY importance DESC, created_at DESC LIMIT ?",
            (kind, limit),
        ).fetchall()
        return [self._row_dict(r) for r in rows]

    def list_all(self, kind: str | None = None, limit: int = 200) -> list[dict]:
        if kind:
            return self.list_by_kind(kind, limit=limit)
        rows = self._conn.execute(
            "SELECT * FROM memories ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [self._row_dict(r) for r in rows]

    def delete_by_id(self, row_id: int) -> bool:
        cur = self._conn.execute("DELETE FROM memories WHERE id = ?", (row_id,))
        self._conn.commit()
        return cur.rowcount > 0

    def update_by_id(self, row_id: int, content: str) -> bool:
        cur = self._conn.execute(
            "UPDATE memories SET content = ? WHERE id = ?",
            ((content or "").strip(), int(row_id)),
        )
        self._conn.commit()
        return cur.rowcount > 0

    def _row_dict(self, r: sqlite3.Row) -> dict:
        return {
            "id": r["id"], "kind": r["kind"], "content": r["content"],
            "importance": r["importance"],
            "source": r["source"] if "source" in r.keys() else "agent",
            "scope": r["scope"] if "scope" in r.keys() else "",
            "created_at": r["created_at"],
        }

    def delete_by_content(self, kind: str, content: str) -> int:
        """按 kind+内容精确删除,返回删除条数。"""
        cur = self._conn.execute(
            "DELETE FROM memories WHERE kind = ? AND content = ?", (kind, content))
        self._conn.commit()
        return cur.rowcount

    def delete_by_content_prefix(self, kind: str, prefix: str) -> int:
        """按 kind+内容前缀删除(个人文档重新索引时清旧块)。"""
        like = prefix.replace("%", r"\%").replace("_", r"\_") + "%"
        cur = self._conn.execute(
            r"DELETE FROM memories WHERE kind = ? AND content LIKE ? ESCAPE '\'",
            (kind, like))
        self._conn.commit()
        return cur.rowcount

    def forget(self, min_importance: float = 0.2, max_age_days: float = 30.0) -> int:
        """清理低价值且久未使用的记忆,返回删除条数。"""
        cutoff = time.time() - max_age_days * 86400
        cur = self._conn.execute(
            "DELETE FROM memories WHERE importance < ? AND last_used < ?",
            (min_importance, cutoff),
        )
        self._conn.commit()
        return cur.rowcount

    def close(self) -> None:
        self._conn.close()
