"""定时任务能力 —— 让 agent 能给自己排期(到点自动执行一段指令)。

场景:
  - "每天早上 9 点给我汇总昨天的邮件"
  - "每隔 2 小时检查一次网站是否在线"

工具:
  ScheduleCreate  风险 WRITE        —— 新建定时任务(标准配置变更,需确认)
  ScheduleList    风险 READ         —— 列出现有定时任务
  ScheduleDelete  风险 DESTRUCTIVE  —— 删除定时任务

实现:直接读写与 Web/调度器同一个 tasks.db。运行中的调度器每拍都重读该库,
因此通过本工具创建/删除的任务会被立刻接管,无需重启。
"""
from __future__ import annotations

import datetime as _dt
from typing import Any

from core.types import CapabilityResult, Risk

_STORE = None


def _store():
    global _STORE
    if _STORE is None:
        from config import Config
        from scheduler.store import TaskStore
        _STORE = TaskStore(db_path=f"{Config.LOG_DIR}/tasks.db")
    return _STORE


def _fmt_next(ts: float) -> str:
    try:
        return _dt.datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")
    except Exception:
        return str(ts)


class ScheduleCreate:
    name = "schedule.create"
    risk = Risk.WRITE
    description = "新建一个定时任务:到点自动把 prompt 交给 agent 执行。支持每隔N秒(every)或每天定点(daily)。"
    schema = {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "任务名称(简短可读)"},
            "prompt": {"type": "string", "description": "到点要执行的完整指令"},
            "schedule_type": {"type": "string", "enum": ["every", "daily"],
                              "description": "every=每隔固定秒数;daily=每天定点"},
            "interval_sec": {"type": "integer", "description": "schedule_type=every 时的间隔秒数(最少10)"},
            "at_hhmm": {"type": "string", "description": "schedule_type=daily 时的时间,如 09:00"},
            "deliver": {"type": "string", "enum": ["none", "email"],
                        "description": "结果投递渠道,默认 none(只记录,不外发)"},
            "deliver_to": {"type": "string", "description": "投递目标(邮箱),留空用渠道默认"},
        },
        "required": ["name", "prompt", "schedule_type"],
    }

    async def invoke(self, args: dict, ctx: Any) -> CapabilityResult:
        name = str(args.get("name", "")).strip()
        prompt = str(args.get("prompt", "")).strip()
        stype = str(args.get("schedule_type", "")).strip()
        if not name or not prompt:
            return CapabilityResult(ok=False, error="缺少 name 或 prompt")
        if stype not in ("every", "daily"):
            return CapabilityResult(ok=False, error="schedule_type 必须是 every 或 daily")
        kwargs: dict = {"name": name, "prompt": prompt, "schedule_type": stype,
                        "task_type": "agent"}
        if stype == "every":
            try:
                kwargs["interval_sec"] = max(10, int(args.get("interval_sec", 3600)))
            except Exception:
                return CapabilityResult(ok=False, error="interval_sec 必须是整数")
        else:
            kwargs["at_hhmm"] = str(args.get("at_hhmm", "09:00")).strip() or "09:00"
        deliver = str(args.get("deliver", "none")).strip() or "none"
        if deliver not in ("none", "email"):
            return CapabilityResult(ok=False, error="deliver 只支持 none 或 email")
        kwargs["deliver"] = deliver
        kwargs["deliver_to"] = str(args.get("deliver_to", "")).strip()
        try:
            task = _store().create(**kwargs)
        except Exception as e:
            return CapabilityResult(ok=False, error=f"创建失败: {e}")
        when = (f"每 {kwargs['interval_sec']} 秒" if stype == "every"
                else f"每天 {kwargs['at_hhmm']}")
        return CapabilityResult(
            ok=True,
            output=f"已创建定时任务「{name}」(id={task.id},{when}),"
                   f"下次运行 {_fmt_next(task.next_run)}。",
        )


class ScheduleList:
    name = "schedule.list"
    risk = Risk.READ
    description = "列出当前所有定时任务(含 id、名称、节奏、下次运行时间、是否启用)。"
    schema = {"type": "object", "properties": {}}

    async def invoke(self, args: dict, ctx: Any) -> CapabilityResult:
        tasks = _store().list()
        if not tasks:
            return CapabilityResult(ok=True, output="当前没有定时任务。")
        lines = []
        for t in tasks:
            when = (f"每{t.interval_sec}秒" if t.schedule_type == "every"
                    else f"每天{t.at_hhmm}")
            flag = "" if t.enabled else "(已停用)"
            lines.append(f"- {t.id} 「{t.name}」{when} 下次 {_fmt_next(t.next_run)}{flag}")
        return CapabilityResult(ok=True, output="\n".join(lines))


class ScheduleDelete:
    name = "schedule.delete"
    risk = Risk.DESTRUCTIVE
    description = "按 id 删除一个定时任务。"
    schema = {
        "type": "object",
        "properties": {"id": {"type": "string", "description": "要删除的任务 id"}},
        "required": ["id"],
    }

    async def invoke(self, args: dict, ctx: Any) -> CapabilityResult:
        tid = str(args.get("id", "")).strip()
        if not tid:
            return CapabilityResult(ok=False, error="缺少 id")
        if _store().get(tid) is None:
            return CapabilityResult(ok=False, error=f"任务 {tid} 不存在")
        _store().delete(tid)
        return CapabilityResult(ok=True, output=f"已删除定时任务 {tid}。")
