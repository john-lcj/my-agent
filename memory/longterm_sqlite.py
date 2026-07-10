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
        for column, definition in (
            ("memory_id", "TEXT"), ("confidence", "REAL NOT NULL DEFAULT 0.5"),
            ("evidence_ref", "TEXT NOT NULL DEFAULT ''"), ("provenance", "TEXT NOT NULL DEFAULT 'agent'"),
            ("status", "TEXT NOT NULL DEFAULT 'active'"), ("supersedes_id", "TEXT NOT NULL DEFAULT ''"),
        ):
            if column not in cols:
                self._conn.execute(f"ALTER TABLE memories ADD COLUMN {column} {definition}")
        import uuid
        for row in self._conn.execute("SELECT id FROM memories WHERE memory_id IS NULL OR memory_id='' ").fetchall():
            self._conn.execute("UPDATE memories SET memory_id=? WHERE id=?", (uuid.uuid4().hex, row[0]))
        self._conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_memories_memory_id ON memories(memory_id)")
        self._conn.execute("CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts USING fts5(memory_id UNINDEXED, content, kind, scope)")
        self._conn.execute("DELETE FROM memories_fts")
        self._conn.execute("INSERT INTO memories_fts(memory_id,content,kind,scope) SELECT memory_id,content,kind,scope FROM memories WHERE status='active'")
        self._conn.commit()

    def store(self, item: MemoryItem) -> None:
        exp = getattr(item, "expires_at", None)
        if exp is None and item.kind == "fact":
            from memory.policy import ttl_for_kind
            ttl = ttl_for_kind("fact")
            if ttl:
                exp = item.created_at + ttl
        self._conn.execute(
            "INSERT INTO memories (memory_id, kind, content, importance, source, scope, created_at, last_used, expires_at, confidence, evidence_ref, provenance, status, supersedes_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (item.memory_id, item.kind, item.content, item.importance, item.source or "agent",
             getattr(item, "scope", "") or "", item.created_at, item.last_used, exp,
             item.confidence, item.evidence_ref, item.provenance, item.status, item.supersedes_id),
        )
        self._conn.execute("INSERT INTO memories_fts(memory_id,content,kind,scope) VALUES(?,?,?,?)", (item.memory_id, item.content, item.kind, item.scope or ""))
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
                f"SELECT * FROM memories WHERE status='active' AND ({where}){scope_sql} "
                f"ORDER BY importance DESC, last_used DESC LIMIT ?",
                (*params, *scope_params, k),
            ).fetchall()
        else:
            where_only = scope_sql.replace(" AND ", " WHERE ", 1) if scope_sql else ""
            rows = self._conn.execute(
                f"SELECT * FROM memories WHERE status='active'{where_only} ORDER BY importance DESC, last_used DESC LIMIT ?",
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
                memory_id=r["memory_id"], confidence=r["confidence"],
                evidence_ref=r["evidence_ref"], provenance=r["provenance"],
                status=r["status"], supersedes_id=r["supersedes_id"],
            )
            if expired:
                item.content = f"【需刷新·已过期】{item.content}"
            items.append(item)
        self._conn.commit()
        return items

    def fts_retrieve(self, query: str, k: int = 5, scope: str | None = None) -> list[MemoryItem]:
        """Use SQLite FTS5 for token-aware keyword retrieval."""
        tokens = [t for t in query.replace("，", " ").replace(",", " ").split() if t]
        if not tokens:
            return self.retrieve(query, k=k, scope=scope)
        match = " OR ".join('"' + t.replace('"', ' ') + '"' for t in tokens)
        scope_sql = " AND (m.scope = ? OR m.scope = '')" if scope is not None else ""
        params: list = [match]
        if scope is not None:
            params.append(scope)
        params.append(k)
        rows = self._conn.execute(
            "SELECT m.* FROM memories_fts f JOIN memories m ON m.memory_id=f.memory_id "
            "WHERE memories_fts MATCH ? AND m.status='active'" + scope_sql +
            " ORDER BY bm25(memories_fts), m.importance DESC LIMIT ?", params
        ).fetchall()
        if not rows:
            return self.retrieve(query, k=k, scope=scope)
        now = time.time()
        items = []
        for r in rows:
            exp = r["expires_at"]
            expired = exp is not None and float(exp) < now
            if expired and r["kind"] != "fact":
                continue
            if not expired:
                self._conn.execute("UPDATE memories SET last_used=? WHERE id=?", (now, r["id"]))
            items.append(MemoryItem(
                kind=r["kind"], content=r["content"], importance=r["importance"],
                source=r["source"], scope=r["scope"], created_at=r["created_at"],
                last_used=now, expires_at=exp, stale=bool(expired), memory_id=r["memory_id"],
                confidence=r["confidence"], evidence_ref=r["evidence_ref"],
                provenance=r["provenance"], status=r["status"], supersedes_id=r["supersedes_id"],
            ))
        self._conn.commit()
        return items

    def list_by_kind(self, kind: str, limit: int = 50) -> list[dict]:
        """按 kind 列出记忆(含行 id,供管理界面查看/删除)。"""
        rows = self._conn.execute(
            "SELECT * FROM memories WHERE status='active' AND kind = ? "
            "ORDER BY importance DESC, created_at DESC LIMIT ?",
            (kind, limit),
        ).fetchall()
        return [self._row_dict(r) for r in rows]

    def list_all(self, kind: str | None = None, limit: int = 200) -> list[dict]:
        if kind:
            return self.list_by_kind(kind, limit=limit)
        rows = self._conn.execute(
            "SELECT * FROM memories WHERE status='active' ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [self._row_dict(r) for r in rows]

    def delete_by_id(self, row_id: int) -> bool:
        row = self._conn.execute("SELECT memory_id FROM memories WHERE id = ?", (row_id,)).fetchone()
        return self.delete_memory(row[0]) if row else False

    def update_by_id(self, row_id: int, content: str) -> bool:
        row = self._conn.execute("SELECT memory_id FROM memories WHERE id = ?", (row_id,)).fetchone()
        return self.update_memory(row[0], content=(content or "").strip()) if row else False

    def _row_dict(self, r: sqlite3.Row) -> dict:
        return {
            "id": r["id"], "memory_id": r["memory_id"], "kind": r["kind"], "content": r["content"],
            "importance": r["importance"],
            "source": r["source"] if "source" in r.keys() else "agent",
            "scope": r["scope"] if "scope" in r.keys() else "",
            "created_at": r["created_at"],
            "confidence": r["confidence"], "evidence_ref": r["evidence_ref"],
            "provenance": r["provenance"], "status": r["status"],
            "supersedes_id": r["supersedes_id"],
        }

    def get_by_memory_id(self, memory_id: str) -> dict | None:
        row = self._conn.execute("SELECT * FROM memories WHERE memory_id=?", (memory_id,)).fetchone()
        return self._row_dict(row) if row else None

    def update_memory(self, memory_id: str, **fields) -> bool:
        allowed = {"content", "importance", "confidence", "evidence_ref", "provenance", "status", "supersedes_id", "expires_at", "kind", "scope"}
        updates = {k: v for k, v in fields.items() if k in allowed}
        if not updates:
            return False
        sets = ",".join(f"{k}=?" for k in updates)
        cur = self._conn.execute(f"UPDATE memories SET {sets} WHERE memory_id=?", (*updates.values(), memory_id))
        self._conn.execute("DELETE FROM memories_fts WHERE memory_id=?", (memory_id,))
        row = self.get_by_memory_id(memory_id)
        if row and row["status"] == "active":
            self._conn.execute("INSERT INTO memories_fts(memory_id,content,kind,scope) VALUES(?,?,?,?)", (memory_id, row["content"], row["kind"], row["scope"]))
        self._conn.commit()
        return bool(cur.rowcount)

    def delete_memory(self, memory_id: str) -> bool:
        self._conn.execute("DELETE FROM memories_fts WHERE memory_id=?", (memory_id,))
        cur = self._conn.execute("UPDATE memories SET status='deleted' WHERE memory_id=?", (memory_id,))
        self._conn.commit()
        return bool(cur.rowcount)

    def delete_by_content(self, kind: str, content: str) -> int:
        """按 kind+内容精确删除,返回删除条数。"""
        rows = self._conn.execute("SELECT memory_id FROM memories WHERE kind=? AND content=?", (kind, content)).fetchall()
        for row in rows:
            self.delete_memory(row[0])
        return len(rows)

    def delete_by_content_prefix(self, kind: str, prefix: str) -> int:
        """按 kind+内容前缀删除(个人文档重新索引时清旧块)。"""
        like = prefix.replace("%", r"\%").replace("_", r"\_") + "%"
        rows = self._conn.execute(r"SELECT memory_id FROM memories WHERE kind = ? AND content LIKE ? ESCAPE '\'", (kind, like)).fetchall()
        for row in rows:
            self.delete_memory(row[0])
        return len(rows)

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
