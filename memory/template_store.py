"""提示词/指令模板库 —— 把常用话术、固定任务存成模板,一键插入对话框。

简单 SQLite 存储,供「自定义 · 提示词模板」标签页增删改查。
"""
from __future__ import annotations

import os
import sqlite3
import time
import uuid


class TemplateStore:
    def __init__(self, db_path: str = "logs/templates.db") -> None:
        parent = os.path.dirname(db_path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS templates (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL DEFAULT '',
                content TEXT NOT NULL DEFAULT '',
                category TEXT NOT NULL DEFAULT '',
                updated_at REAL NOT NULL DEFAULT 0
            )
            """
        )
        self._conn.commit()

    def list(self) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM templates ORDER BY updated_at DESC"
        ).fetchall()
        return [dict(r) for r in rows]

    def save(self, title: str, content: str, category: str = "",
             tid: str | None = None) -> dict:
        tid = (tid or "").strip() or uuid.uuid4().hex[:12]
        self._conn.execute(
            "INSERT INTO templates (id, title, content, category, updated_at) "
            "VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(id) DO UPDATE SET title=excluded.title, content=excluded.content, "
            "category=excluded.category, updated_at=excluded.updated_at",
            (tid, title or "", content or "", category or "", time.time()),
        )
        self._conn.commit()
        row = self._conn.execute("SELECT * FROM templates WHERE id = ?", (tid,)).fetchone()
        return dict(row)

    def delete(self, tid: str) -> bool:
        cur = self._conn.execute("DELETE FROM templates WHERE id = ?", ((tid or "").strip(),))
        self._conn.commit()
        return cur.rowcount > 0

    def close(self) -> None:
        self._conn.close()
