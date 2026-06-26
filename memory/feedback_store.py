"""消息反馈 —— 点赞/点踩落库,供后续 eval 与质量分析。"""
from __future__ import annotations

import os
import sqlite3
import time


class FeedbackStore:
    def __init__(self, db_path: str = "logs/feedback.db") -> None:
        parent = os.path.dirname(db_path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS message_feedback (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                msg_key TEXT NOT NULL,
                rating INTEGER NOT NULL,
                created_at REAL NOT NULL,
                UNIQUE(session_id, msg_key)
            )
            """
        )
        self._conn.commit()

    def upsert(self, session_id: str, msg_key: str, rating: int) -> None:
        sid = (session_id or "").strip()
        key = (msg_key or "").strip()
        if not sid or not key:
            return
        if rating == 0:
            self._conn.execute(
                "DELETE FROM message_feedback WHERE session_id = ? AND msg_key = ?",
                (sid, key),
            )
            self._conn.commit()
            return
        if rating not in (1, -1):
            return
        self._conn.execute(
            "INSERT INTO message_feedback (session_id, msg_key, rating, created_at) "
            "VALUES (?, ?, ?, ?) "
            "ON CONFLICT(session_id, msg_key) DO UPDATE SET "
            "rating = excluded.rating, created_at = excluded.created_at",
            (sid, key, rating, time.time()),
        )
        self._conn.commit()

    def get(self, session_id: str, msg_key: str) -> int | None:
        row = self._conn.execute(
            "SELECT rating FROM message_feedback WHERE session_id = ? AND msg_key = ?",
            (session_id, msg_key),
        ).fetchone()
        return int(row["rating"]) if row else None

    def close(self) -> None:
        self._conn.close()
