"""Mission 持久化(SQLite)—— 让"数字员工"的任务跨进程重启依然活着。

一个 mission 一行;子任务/产物/通知作为 JSON 列随行存(MVP 够用,日后量大再拆表)。
状态变更走 core.mission 的状态机校验,非法转移直接拒绝(防把状态写花)。
"""
from __future__ import annotations

import json
import os
import sqlite3
import time
import uuid

from core.mission import MissionStatus, AttentionLevel, can_transition


class MissionStore:
    def __init__(self, db_path: str = "logs/missions.db") -> None:
        parent = os.path.dirname(db_path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS missions (
                id TEXT PRIMARY KEY,
                goal TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'created',
                attention_level INTEGER NOT NULL DEFAULT 2,
                deadline TEXT NOT NULL DEFAULT '',
                blocked_reason TEXT NOT NULL DEFAULT '',
                tasks TEXT NOT NULL DEFAULT '[]',        -- [{id,text,status,result}]
                artifacts TEXT NOT NULL DEFAULT '[]',    -- [路径]
                notifications TEXT NOT NULL DEFAULT '[]', -- [{ts,level,message}]
                context TEXT NOT NULL DEFAULT '[]',       -- [用户补充的资料/决策,供卡住后恢复]
                created_at REAL NOT NULL DEFAULT 0,
                updated_at REAL NOT NULL DEFAULT 0
            )
            """
        )
        # 旧库迁移:补 context 列(忽略已存在)
        try:
            self._conn.execute("ALTER TABLE missions ADD COLUMN context TEXT NOT NULL DEFAULT '[]'")
        except sqlite3.OperationalError:
            pass
        self._conn.commit()

    # ── 基础 CRUD ──────────────────────────────────────────────
    def create(self, goal: str, attention_level: int = AttentionLevel.EMAIL,
               deadline: str = "") -> dict:
        mid = uuid.uuid4().hex[:12]
        now = time.time()
        self._conn.execute(
            "INSERT INTO missions (id, goal, status, attention_level, deadline, "
            "created_at, updated_at) VALUES (?,?,?,?,?,?,?)",
            (mid, goal.strip(), MissionStatus.CREATED.value,
             int(attention_level), deadline, now, now))
        self._conn.commit()
        return self.get(mid)

    def get(self, mid: str) -> dict | None:
        row = self._conn.execute("SELECT * FROM missions WHERE id=?", (mid,)).fetchone()
        return self._hydrate(row) if row else None

    def list(self, status: str | None = None) -> list[dict]:
        if status:
            rows = self._conn.execute(
                "SELECT * FROM missions WHERE status=? ORDER BY updated_at DESC",
                (status,)).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM missions ORDER BY updated_at DESC").fetchall()
        return [self._hydrate(r) for r in rows]

    # ── 状态机(校验合法转移)────────────────────────────────────
    def set_status(self, mid: str, status: str, reason: str = "") -> dict:
        m = self.get(mid)
        if m is None:
            raise KeyError(f"mission 不存在:{mid}")
        cur = m["status"]
        if cur == status:
            pass  # 幂等:同态(如 executing→executing 推进)允许
        elif not can_transition(cur, status):
            raise ValueError(f"非法状态转移:{cur} → {status}")
        self._conn.execute(
            "UPDATE missions SET status=?, blocked_reason=?, updated_at=? WHERE id=?",
            (MissionStatus(status).value, reason, time.time(), mid))
        self._conn.commit()
        return self.get(mid)

    # ── 子任务 / 产物 / 通知 ─────────────────────────────────────
    def set_tasks(self, mid: str, tasks: list[dict]) -> dict:
        norm = []
        for i, t in enumerate(tasks):
            if isinstance(t, str):
                t = {"text": t}
            norm.append({"id": t.get("id") or f"t{i+1}",
                         "text": str(t.get("text", "")),
                         "status": t.get("status", "pending"),
                         "result": t.get("result", "")})
        self._save_field(mid, "tasks", norm)
        return self.get(mid)

    def update_task(self, mid: str, task_id: str, status: str | None = None,
                    result: str | None = None) -> dict:
        m = self.get(mid)
        if m is None:
            raise KeyError(mid)
        tasks = m["tasks"]
        for t in tasks:
            if t["id"] == task_id:
                if status is not None:
                    t["status"] = status
                if result is not None:
                    t["result"] = result
        self._save_field(mid, "tasks", tasks)
        return self.get(mid)

    def next_task(self, mid: str) -> dict | None:
        """下一个待办子任务(顺序执行,取第一个 pending)。"""
        m = self.get(mid)
        if m is None:
            return None
        for t in m["tasks"]:
            if t.get("status") == "pending":
                return t
        return None

    def add_artifact(self, mid: str, path: str) -> dict:
        m = self.get(mid)
        if m is None:
            raise KeyError(mid)
        arts = m["artifacts"]
        if path not in arts:
            arts.append(path)
        self._save_field(mid, "artifacts", arts)
        return self.get(mid)

    def add_context(self, mid: str, note: str) -> dict:
        """记录用户为解卡补充的资料/决策(恢复执行时拼进任务上下文)。"""
        m = self.get(mid)
        if m is None:
            raise KeyError(mid)
        ctx = m.get("context") or []
        note = (note or "").strip()
        if note:
            ctx.append({"ts": time.time(), "note": note})
        self._save_field(mid, "context", ctx)
        return self.get(mid)

    def add_notification(self, mid: str, level: int, message: str) -> dict:
        m = self.get(mid)
        if m is None:
            raise KeyError(mid)
        notes = m["notifications"]
        notes.append({"ts": time.time(), "level": int(level), "message": message})
        self._save_field(mid, "notifications", notes)
        return self.get(mid)

    # ── 内部 ──────────────────────────────────────────────────
    def _save_field(self, mid: str, field: str, value) -> None:
        self._conn.execute(
            f"UPDATE missions SET {field}=?, updated_at=? WHERE id=?",
            (json.dumps(value, ensure_ascii=False), time.time(), mid))
        self._conn.commit()

    @staticmethod
    def _hydrate(row: sqlite3.Row) -> dict:
        d = dict(row)
        for f in ("tasks", "artifacts", "notifications", "context"):
            try:
                d[f] = json.loads(d.get(f) or "[]")
            except Exception:
                d[f] = []
        return d

    def close(self) -> None:
        self._conn.close()
