"""本地日历能力(.ics)—— 看日程 / 排会 / 删事件,零外部账号、零依赖。

事件存在工作区的一个 .ics 文件(默认 产物/日历.ics),符合 iCalendar(RFC5545)子集,
可直接被 Apple 日历 / Google 日历 / Outlook「订阅本地文件」导入。
日历同步到云(CalDAV)是后续可选项;本地优先,先把"记日程、排会"闭环跑起来。

时间用本地浮动时间(不带时区),格式接受:
  2026-06-30 14:00 / 2026-06-30T14:00 / 2026-06-30(全天)
"""
from __future__ import annotations

import os
import re
import uuid
import hashlib
from datetime import datetime, timedelta
from typing import Any

from capabilities.tools.base import Tool
from core.types import CapabilityResult, Risk


def _cal_path() -> str:
    p = os.environ.get("CALENDAR_FILE", "").strip()
    if p:
        return os.path.expanduser(p)
    ws = os.environ.get("AGENT_WORKSPACE_ROOT", "").strip() or os.getcwd()
    d = os.path.join(ws, "产物")
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, "日历.ics")


def _parse_dt(s: str) -> tuple[datetime | None, bool]:
    """返回 (datetime, 是否全天)。"""
    s = (s or "").strip().replace("/", "-")
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(s, fmt), False
        except ValueError:
            pass
    try:
        return datetime.strptime(s, "%Y-%m-%d"), True
    except ValueError:
        return None, False


def _ics_dt(dt: datetime, all_day: bool) -> str:
    return dt.strftime("%Y%m%d") if all_day else dt.strftime("%Y%m%dT%H%M%S")


def _esc(s: str) -> str:
    return (s or "").replace("\\", "\\\\").replace(",", "\\,").replace(";", "\\;").replace("\n", "\\n")


def _unesc(s: str) -> str:
    return (s or "").replace("\\n", "\n").replace("\\,", ",").replace("\\;", ";").replace("\\\\", "\\")


_HEADER = "BEGIN:VCALENDAR\nVERSION:2.0\nPRODID:-//Captain//Local Calendar//CN\nCALSCALE:GREGORIAN\n"


def _read_events(path: str) -> list[dict]:
    if not os.path.isfile(path):
        return []
    events, cur = [], None
    for raw in open(path, encoding="utf-8"):
        ln = raw.rstrip("\n")
        if ln == "BEGIN:VEVENT":
            cur = {}
        elif ln == "END:VEVENT":
            if cur is not None:
                events.append(cur)
            cur = None
        elif cur is not None and ":" in ln:
            key, val = ln.split(":", 1)
            key = key.split(";", 1)[0]   # 丢掉 ;VALUE=DATE 等参数
            cur[key] = val
    return events


def _fmt_when(dtstr: str) -> str:
    for fmt in ("%Y%m%dT%H%M%S", "%Y%m%d"):
        try:
            dt = datetime.strptime(dtstr, fmt)
            return dt.strftime("%Y-%m-%d %H:%M" if fmt.endswith("S") else "%Y-%m-%d(全天)")
        except ValueError:
            pass
    return dtstr


def _event_dt(ev: dict) -> datetime | None:
    for fmt in ("%Y%m%dT%H%M%S", "%Y%m%d"):
        try:
            return datetime.strptime(ev.get("DTSTART", ""), fmt)
        except ValueError:
            pass
    return None


class CalendarAdd(Tool):
    name = "calendar.add"
    risk = Risk.WRITE
    description = ("往本地日历加一个事件/会议(写入工作区 .ics,可被 Apple/Google 日历订阅)。"
                  "用于'帮我把周五下午3点的评审排进日历'这类。")
    schema = {
        "type": "object",
        "properties": {
            "title": {"type": "string", "description": "事件标题"},
            "start": {"type": "string", "description": "开始,如 2026-06-30 14:00 或 2026-06-30(全天)"},
            "end": {"type": "string", "description": "结束时间(可选)"},
            "duration_min": {"type": "integer", "description": "时长分钟(可选,默认 60;全天忽略)"},
            "location": {"type": "string", "description": "地点(可选)"},
            "notes": {"type": "string", "description": "备注(可选)"},
            "idempotency_key": {"type": "string", "description": "Stable key preventing duplicate events"},
        },
        "required": ["title", "start"],
    }

    async def invoke(self, args: dict, ctx: Any) -> CapabilityResult:
        title = str(args.get("title", "")).strip()
        if not title:
            return CapabilityResult(ok=False, error="缺少 title")
        start, all_day = _parse_dt(str(args.get("start", "")))
        if start is None:
            return CapabilityResult(ok=False, error="start 解析失败,用 2026-06-30 14:00 这样的格式")
        if all_day:
            end, _ = start, True
            dtend = start + timedelta(days=1)
        else:
            if args.get("end"):
                dtend, _ = _parse_dt(str(args.get("end")))
                if dtend is None:
                    return CapabilityResult(ok=False, error="end 解析失败")
            else:
                dtend = start + timedelta(minutes=int(args.get("duration_min", 60) or 60))
        if dtend <= start:
            return CapabilityResult(ok=False, error="end must be later than start")
        path = _cal_path()
        new = not os.path.isfile(path)
        stable_key = str(args.get("idempotency_key", "")).strip()
        uid = (hashlib.sha256(stable_key.encode()).hexdigest() + "@captain.local"
               if stable_key else uuid.uuid4().hex + "@captain.local")
        if not new and stable_key:
            existing = open(path, encoding="utf-8").read()
            if f"UID:{uid}" in existing:
                return CapabilityResult(ok=True, output=f"日历事件已存在(幂等跳过):{title}")
        lines = [
            "BEGIN:VEVENT",
            f"UID:{uid}",
            f"DTSTAMP:{datetime.now().strftime('%Y%m%dT%H%M%S')}",
            (f"DTSTART;VALUE=DATE:{_ics_dt(start, True)}" if all_day
             else f"DTSTART:{_ics_dt(start, False)}"),
            (f"DTEND;VALUE=DATE:{_ics_dt(dtend, True)}" if all_day
             else f"DTEND:{_ics_dt(dtend, False)}"),
            f"SUMMARY:{_esc(title)}",
        ]
        if args.get("location"):
            lines.append(f"LOCATION:{_esc(str(args['location']))}")
        if args.get("notes"):
            lines.append(f"DESCRIPTION:{_esc(str(args['notes']))}")
        lines.append("END:VEVENT")
        block = "\n".join(lines) + "\n"
        try:
            if new:
                with open(path, "w", encoding="utf-8") as f:
                    f.write(_HEADER + block + "END:VCALENDAR\n")
            else:
                txt = open(path, encoding="utf-8").read()
                if "END:VCALENDAR" in txt:
                    txt = txt.replace("END:VCALENDAR", block + "END:VCALENDAR")
                else:
                    txt = txt.rstrip() + "\n" + block
                with open(path, "w", encoding="utf-8") as f:
                    f.write(txt)
        except OSError as e:
            return CapabilityResult(ok=False, error=str(e))
        when = start.strftime("%Y-%m-%d" if all_day else "%Y-%m-%d %H:%M")
        return CapabilityResult(ok=True, output=f"已加入日历:{title} @ {when}({path})")


class CalendarList(Tool):
    name = "calendar.list"
    risk = Risk.READ
    description = "看本地日历里接下来的日程(默认未来 7 天)。用于'我这周有什么安排'。"
    schema = {
        "type": "object",
        "properties": {
            "days": {"type": "integer", "description": "往后看几天,默认 7"},
        },
    }

    async def invoke(self, args: dict, ctx: Any) -> CapabilityResult:
        path = _cal_path()
        evs = _read_events(path)
        if not evs:
            return CapabilityResult(ok=True, output="日历是空的,还没有安排。")
        days = int(args.get("days", 7) or 7)
        now = datetime.now()
        horizon = now + timedelta(days=days)
        rows = []
        for ev in evs:
            dt = _event_dt(ev)
            if dt is None or dt < now - timedelta(hours=12) or dt > horizon:
                continue
            line = f"{_fmt_when(ev.get('DTSTART',''))}  {_unesc(ev.get('SUMMARY',''))}"
            if ev.get("LOCATION"):
                line += f" @ {_unesc(ev['LOCATION'])}"
            rows.append((dt, line))
        if not rows:
            return CapabilityResult(ok=True, output=f"未来 {days} 天没有安排。")
        rows.sort(key=lambda x: x[0])
        return CapabilityResult(ok=True, output=f"未来 {days} 天的日程:\n" + "\n".join(r[1] for r in rows))


class CalendarRemove(Tool):
    name = "calendar.remove"
    risk = Risk.WRITE
    description = "按标题删除本地日历里的事件(标题匹配多个时全删,谨慎)。"
    schema = {
        "type": "object",
        "properties": {"title": {"type": "string", "description": "要删除的事件标题(精确匹配)"}},
        "required": ["title"],
    }

    async def invoke(self, args: dict, ctx: Any) -> CapabilityResult:
        title = str(args.get("title", "")).strip()
        if not title:
            return CapabilityResult(ok=False, error="缺少 title")
        path = _cal_path()
        if not os.path.isfile(path):
            return CapabilityResult(ok=False, error="日历还不存在")
        txt = open(path, encoding="utf-8").read()
        # 按 VEVENT 块过滤
        head = txt.split("BEGIN:VEVENT", 1)[0] if "BEGIN:VEVENT" in txt else _HEADER
        blocks = re.findall(r"BEGIN:VEVENT.*?END:VEVENT\n?", txt, flags=re.S)
        target = f"SUMMARY:{_esc(title)}"
        kept = [b for b in blocks if target not in b]
        removed = len(blocks) - len(kept)
        if removed == 0:
            return CapabilityResult(ok=False, error=f"没找到标题为「{title}」的事件")
        with open(path, "w", encoding="utf-8") as f:
            f.write(head + "".join(kept) + "END:VCALENDAR\n")
        return CapabilityResult(ok=True, output=f"已删除 {removed} 个「{title}」事件")
