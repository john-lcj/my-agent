"""程序记忆 —— 结构化 key-value,按主体作用域持久化。

与自然语言长期记忆不同:适合存偏好开关、任务状态、项目约定等可精确读写的数据。
"""
from __future__ import annotations

import json
import os
import sqlite3
import time
from typing import Any, Optional


class ProgramMemoryStore:
    def __init__(self, db_path: str = "logs/program_memory.db") -> None:
        parent = os.path.dirname(db_path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS program_kv (
                scope      TEXT NOT NULL,
                key        TEXT NOT NULL,
                value_json TEXT NOT NULL,
                updated_at REAL NOT NULL,
                PRIMARY KEY (scope, key)
            );
            """
        )
        self._conn.commit()

    def set(self, scope: str, key: str, value: Any) -> None:
        scope = scope or "global"
        key = key.strip()
        if not key:
            raise ValueError("key 不能为空")
        self._conn.execute(
            "INSERT INTO program_kv (scope, key, value_json, updated_at) "
            "VALUES (?, ?, ?, ?) "
            "ON CONFLICT(scope, key) DO UPDATE SET value_json=excluded.value_json, "
            "updated_at=excluded.updated_at",
            (scope, key, json.dumps(value, ensure_ascii=False), time.time()),
        )
        self._conn.commit()

    def get(self, scope: str, key: str) -> Optional[Any]:
        row = self._conn.execute(
            "SELECT value_json FROM program_kv WHERE scope=? AND key=?",
            (scope or "global", key.strip()),
        ).fetchone()
        if not row:
            return None
        try:
            return json.loads(row[0])
        except json.JSONDecodeError:
            return row[0]

    def list_keys(self, scope: str, prefix: str = "") -> list[str]:
        scope = scope or "global"
        rows = self._conn.execute(
            "SELECT key FROM program_kv WHERE scope=? ORDER BY key",
            (scope,),
        ).fetchall()
        keys = [r[0] for r in rows]
        if prefix:
            keys = [k for k in keys if k.startswith(prefix)]
        return keys

    def delete(self, scope: str, key: str) -> bool:
        cur = self._conn.execute(
            "DELETE FROM program_kv WHERE scope=? AND key=?",
            (scope or "global", key.strip()),
        )
        self._conn.commit()
        return cur.rowcount > 0

    def close(self) -> None:
        self._conn.close()
