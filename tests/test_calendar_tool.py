"""本地 .ics 日历能力 —— 加/列/删 + 全天 + 文件可被日历订阅。"""
from __future__ import annotations

import asyncio
import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from capabilities.tools.calendar_tool import CalendarAdd, CalendarList, CalendarRemove
from core.types import Risk


def _soon(days=1, hour=15):
    d = datetime.now() + timedelta(days=days)
    return d.strftime(f"%Y-%m-%d {hour:02d}:00")


def test_risk_levels():
    assert CalendarList.risk == Risk.READ
    assert CalendarAdd.risk == Risk.WRITE and CalendarRemove.risk == Risk.WRITE


def test_add_then_list(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_WORKSPACE_ROOT", str(tmp_path))
    r = asyncio.run(CalendarAdd().invoke(
        {"title": "项目评审", "start": _soon(1), "location": "会议室A", "duration_min": 90}, None))
    assert r.ok and "已加入日历" in r.output
    ics = (tmp_path / "产物" / "日历.ics").read_text(encoding="utf-8")
    assert "BEGIN:VCALENDAR" in ics and "SUMMARY:项目评审" in ics and "END:VCALENDAR" in ics
    lst = asyncio.run(CalendarList().invoke({"days": 7}, None))
    assert "项目评审" in lst.output and "会议室A" in lst.output


def test_all_day_event(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_WORKSPACE_ROOT", str(tmp_path))
    d = (datetime.now() + timedelta(days=2)).strftime("%Y-%m-%d")
    r = asyncio.run(CalendarAdd().invoke({"title": "团建", "start": d}, None))
    assert r.ok
    ics = (tmp_path / "产物" / "日历.ics").read_text(encoding="utf-8")
    assert "VALUE=DATE:" in ics       # 全天事件用 DATE 值类型


def test_multiple_events_and_remove(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_WORKSPACE_ROOT", str(tmp_path))
    asyncio.run(CalendarAdd().invoke({"title": "晨会", "start": _soon(1, 9)}, None))
    asyncio.run(CalendarAdd().invoke({"title": "评审", "start": _soon(2, 14)}, None))
    lst = asyncio.run(CalendarList().invoke({}, None))
    assert "晨会" in lst.output and "评审" in lst.output
    # 删除一个
    rm = asyncio.run(CalendarRemove().invoke({"title": "晨会"}, None))
    assert rm.ok and "已删除 1" in rm.output
    lst2 = asyncio.run(CalendarList().invoke({}, None))
    assert "晨会" not in lst2.output and "评审" in lst2.output
    # 文件结构仍合法
    ics = (tmp_path / "产物" / "日历.ics").read_text(encoding="utf-8")
    assert ics.count("END:VCALENDAR") == 1


def test_list_empty_and_bad_date(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_WORKSPACE_ROOT", str(tmp_path))
    empty = asyncio.run(CalendarList().invoke({}, None))
    assert "空" in empty.output
    bad = asyncio.run(CalendarAdd().invoke({"title": "x", "start": "明天下午"}, None))
    assert not bad.ok and "解析失败" in bad.error
