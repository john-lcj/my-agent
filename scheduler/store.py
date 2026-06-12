"""定时任务的定义与持久化。

任务 = "一段时间到了,就让 agent 跑一句话(prompt),并可选地把结果送到某个渠道"。
持久化用 SQLite(与 session_store 同风格),重启后任务不丢。

调度表达支持两种,够用且直观:
  every:   每隔 N 秒/分/时跑一次(interval_sec 秒)
  daily:   每天某个 HH:MM 跑一次(at_hhmm)
"""
from __future__ import annotations

import json
import os
import sqlite3
import time
import uuid
from dataclasses import dataclass, field, asdict


@dataclass
class ScheduledTask:
    id: str
    name: str
    prompt: str                       # 到点交给 agent 执行的指令
    schedule_type: str = "every"      # 'every' | 'daily'
    interval_sec: int = 3600          # schedule_type=every 时生效
    at_hhmm: str = "09:00"            # schedule_type=daily 时生效
    deliver: str = "none"             # 结果投递渠道: none / email / wechat / qq
    deliver_to: str = ""              # 投递目标(邮箱/用户ID),为空用渠道默认
    task_type: str = "agent"          # agent | memory_forget
    enabled: bool = True
    created_at: float = field(default_factory=time.time)
    last_run: float = 0.0
    next_run: float = 0.0
    last_result: str = ""
    last_status: str = ""             # ok / error / blocked

    def to_dict(self) -> dict:
        return asdict(self)

    def compute_next_run(self, now: float | None = None) -> float:
        now = now if now is not None else time.time()
        if self.schedule_type == "daily":
            import datetime as _dt
            try:
                hh, mm = (int(x) for x in self.at_hhmm.split(":"))
            except Exception:
                hh, mm = 9, 0
            local = _dt.datetime.fromtimestamp(now)
            target = local.replace(hour=hh, minute=mm, second=0, microsecond=0)
            if target.timestamp() <= now:
                target = target + _dt.timedelta(days=1)
            return target.timestamp()
        # every
        return now + max(10, int(self.interval_sec))


class TaskStore:
    def __init__(self, db_path: str = "logs/tasks.db") -> None:
        self.db_path = db_path
        parent = os.path.dirname(db_path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS tasks (id TEXT PRIMARY KEY, data TEXT NOT NULL)")
        self._conn.commit()

    def _row_to_task(self, row) -> ScheduledTask:
        d = json.loads(row["data"])
        return ScheduledTask(**d)

    def list(self) -> list[ScheduledTask]:
        rows = self._conn.execute("SELECT id, data FROM tasks").fetchall()
        return [self._row_to_task(r) for r in rows]

    def get(self, task_id: str) -> ScheduledTask | None:
        row = self._conn.execute(
            "SELECT id, data FROM tasks WHERE id = ?", (task_id,)).fetchone()
        return self._row_to_task(row) if row else None

    def save(self, task: ScheduledTask) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO tasks (id, data) VALUES (?, ?)",
            (task.id, json.dumps(task.to_dict(), ensure_ascii=False)))
        self._conn.commit()

    def delete(self, task_id: str) -> None:
        self._conn.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
        self._conn.commit()

    def create(self, **kwargs) -> ScheduledTask:
        task = ScheduledTask(id=uuid.uuid4().hex[:12], **kwargs)
        task.next_run = task.compute_next_run()
        self.save(task)
        return task
