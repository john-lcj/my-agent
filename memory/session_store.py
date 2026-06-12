"""会话持久化 —— 让多轮对话活过刷新与重连。

地基级组件:对话历史不再只活在内存里的 list,而是落到 SQLite。
刷新页面、断线重连、甚至重启服务后,凭 session_id 就能把整段对话读回来。

两张表:
  sessions(id, title, created_at, updated_at)
  messages(id, session_id, role, content, name, tool_calls, tool_call_id, ts)

只持久化 USER/ASSISTANT/TOOL 三类消息;SYSTEM(人设/能力清单/记忆注入)
每次装载时由组合根重新生成,不入库 —— 这样人设升级能立即对历史会话生效。
"""
from __future__ import annotations

import json
import os
import sqlite3
import time
from typing import Optional

from core.types import Message, Role, ToolCallRef


class SessionStore:
    def __init__(self, db_path: str = "logs/sessions.db") -> None:
        self.db_path = db_path
        parent = os.path.dirname(db_path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self) -> None:
        self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS sessions (
                id          TEXT PRIMARY KEY,
                title       TEXT NOT NULL DEFAULT '',
                created_at  REAL NOT NULL,
                updated_at  REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS messages (
                id                INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id        TEXT NOT NULL,
                role              TEXT NOT NULL,
                content           TEXT NOT NULL,
                name              TEXT,
                tool_calls        TEXT,
                tool_call_id      TEXT,
                reasoning_content TEXT,
                ts                REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_messages_session
                ON messages(session_id, id);
            """
        )
        self._conn.commit()
        try:
            self._conn.execute(
                "ALTER TABLE messages ADD COLUMN reasoning_content TEXT"
            )
            self._conn.commit()
        except sqlite3.OperationalError:
            pass
        cols = {r[1] for r in self._conn.execute("PRAGMA table_info(sessions)").fetchall()}
        if "kind" not in cols:
            self._conn.execute(
                "ALTER TABLE sessions ADD COLUMN kind TEXT NOT NULL DEFAULT 'chat'"
            )
        if "meta" not in cols:
            self._conn.execute("ALTER TABLE sessions ADD COLUMN meta TEXT")
        self._conn.commit()

    # ── 会话级 ────────────────────────────────────────────────────────────────
    def ensure_session(self, session_id: str, title: str = "", kind: str = "chat") -> None:
        now = time.time()
        self._conn.execute(
            "INSERT OR IGNORE INTO sessions (id, title, created_at, updated_at, kind) "
            "VALUES (?, ?, ?, ?, ?)",
            (session_id, title, now, now, kind),
        )
        self._conn.commit()

    def list_sessions(self, limit: int = 50) -> list[dict]:
        rows = self._conn.execute(
            "SELECT id, title, created_at, updated_at, kind FROM sessions "
            "ORDER BY updated_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]

    def update_title(self, session_id: str, title: str) -> bool:
        title = (title or "").strip()
        cur = self._conn.execute(
            "UPDATE sessions SET title = ?, updated_at = ? WHERE id = ?",
            (title, time.time(), session_id),
        )
        self._conn.commit()
        return cur.rowcount > 0

    def session_exists(self, session_id: str) -> bool:
        row = self._conn.execute(
            "SELECT 1 FROM sessions WHERE id = ?", (session_id,)
        ).fetchone()
        return row is not None

    def delete_session(self, session_id: str) -> None:
        self._conn.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))
        self._conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
        self._conn.commit()

    def save_roundtable(self, session_id: str, title: str, meta: dict) -> None:
        """持久化圆桌记录(meta 含 topic/messages/summary 等)。"""
        now = time.time()
        meta_json = json.dumps(meta, ensure_ascii=False)
        title = (title or "圆桌会议").strip()[:80]
        self._conn.execute(
            "INSERT INTO sessions (id, title, created_at, updated_at, kind, meta) "
            "VALUES (?, ?, ?, ?, 'roundtable', ?) "
            "ON CONFLICT(id) DO UPDATE SET "
            "title = excluded.title, updated_at = excluded.updated_at, "
            "kind = 'roundtable', meta = excluded.meta",
            (session_id, title, now, now, meta_json),
        )
        self._conn.commit()

    def load_roundtable(self, session_id: str) -> Optional[dict]:
        row = self._conn.execute(
            "SELECT meta, title FROM sessions WHERE id = ? AND kind = 'roundtable'",
            (session_id,),
        ).fetchone()
        if row is None or not row["meta"]:
            return None
        try:
            data = json.loads(row["meta"])
        except Exception:
            return None
        if isinstance(data, dict):
            data.setdefault("title", row["title"])
        return data

    # ── 消息级 ────────────────────────────────────────────────────────────────
    def append(self, session_id: str, message: Message) -> None:
        """追加一条消息;首条用户消息顺便给会话起个标题。"""
        if not self.session_exists(session_id):
            return
        tool_calls_json = (
            json.dumps([{"id": tc.id, "name": tc.name, "args": tc.args}
                        for tc in message.tool_calls], ensure_ascii=False)
            if message.tool_calls else None
        )
        self._conn.execute(
            "INSERT INTO messages (session_id, role, content, name, tool_calls, "
            "tool_call_id, reasoning_content, ts) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (session_id, message.role.value, message.content, message.name,
             tool_calls_json, message.tool_call_id, message.reasoning_content, message.ts),
        )
        # 用首条用户消息当标题(若还没有标题)
        if message.role == Role.USER:
            row = self._conn.execute(
                "SELECT title FROM sessions WHERE id = ?", (session_id,)
            ).fetchone()
            if row is not None and not row["title"]:
                title = message.content.strip().replace("\n", " ")[:40]
                self._conn.execute(
                    "UPDATE sessions SET title = ? WHERE id = ?", (title, session_id))
        self._conn.execute(
            "UPDATE sessions SET updated_at = ? WHERE id = ?", (time.time(), session_id))
        self._conn.commit()

    def load(self, session_id: str) -> list[Message]:
        """读回某会话的全部已持久化消息(不含 SYSTEM)。"""
        rows = self._conn.execute(
            "SELECT role, content, name, tool_calls, tool_call_id, reasoning_content, ts "
            "FROM messages WHERE session_id = ? ORDER BY id",
            (session_id,),
        ).fetchall()
        out: list[Message] = []
        for r in rows:
            tool_calls = []
            if r["tool_calls"]:
                try:
                    tool_calls = [ToolCallRef(id=t["id"], name=t["name"],
                                              args=t.get("args", {}))
                                  for t in json.loads(r["tool_calls"])]
                except Exception:
                    tool_calls = []
            out.append(Message(
                role=Role(r["role"]),
                content=r["content"],
                name=r["name"],
                tool_calls=tool_calls,
                tool_call_id=r["tool_call_id"],
                reasoning_content=r["reasoning_content"],
                ts=r["ts"],
            ))
        return out

    def close(self) -> None:
        self._conn.close()
