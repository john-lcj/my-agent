"""主动性第一波回归 —— 简报上下文、监控分级、monitor→mission。"""
from __future__ import annotations

import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.briefing import (
    build_daily_briefing_context,
    drain_monitor_digest_queue,
    enqueue_monitor_digest,
    resolve_briefing_prompt,
)
from memory.monitor_store import MonitorStore
from memory.mission_store import MissionStore


def test_monitor_store_attention(tmp_path):
    st = MonitorStore(path=str(tmp_path / "monitors.json"))
    rec = st.create("t", "file", "a.txt", "check", attention="urgent")
    assert rec["attention"] == "urgent"
    rec2 = st.create("t2", "file", "b.txt", "check", attention="invalid")
    assert rec2["attention"] == "normal"


def test_monitor_digest_queue(tmp_path):
    log_dir = str(tmp_path)
    enqueue_monitor_digest(log_dir, "价格", "https://x.com", "变了")
    rows = drain_monitor_digest_queue(log_dir)
    assert len(rows) == 1
    assert rows[0]["name"] == "价格"
    assert drain_monitor_digest_queue(log_dir) == []


def test_briefing_context_includes_mission(tmp_path):
    log_dir = str(tmp_path)
    os.makedirs(log_dir, exist_ok=True)
    ms = MissionStore(db_path=str(tmp_path / "missions.db"))
    m = ms.create("调研竞品")
    ms.set_tasks(m["id"], ["收集资料", "写报告"])
    ms.set_status(m["id"], "planning")
    ms.set_status(m["id"], "executing")
    ctx = build_daily_briefing_context(log_dir=log_dir, mission_store=ms)
    assert "调研竞品" in ctx
    assert "今日待办" in ctx


def test_resolve_briefing_prompt(tmp_path):
    log_dir = str(tmp_path)
    p = resolve_briefing_prompt("{context}", log_dir=log_dir, mission_store=None)
    assert "昨日完成" in p or "协作" in p


def test_format_daily_briefing_email_plain(tmp_path):
    log_dir = str(tmp_path)
    os.makedirs(log_dir, exist_ok=True)
    journal = os.path.join(log_dir, "journal.md")
    with open(journal, "w", encoding="utf-8") as f:
        f.write("# 协作日志\n\n## 2026-07-02 10:00\n\n**做了**:修了简报\n")
    ms = MissionStore(db_path=str(tmp_path / "m.db"))
    m = ms.create("写报告")
    ms.set_tasks(m["id"], ["大纲"])
    ms.set_status(m["id"], "planning")
    ms.set_status(m["id"], "executing")
    body = __import__("core.briefing", fromlist=["format_daily_briefing_email"]).format_daily_briefing_email(
        log_dir=log_dir, mission_store=ms,
    )
    assert "Captain 每日简报" in body
    assert "一、昨日完成" in body
    assert "修了简报" in body
    assert "写报告" in body
    assert "**" not in body
    assert "##" not in body


def test_handle_monitor_urgent_creates_mission(tmp_path, monkeypatch):
    import server.async_tasks as at

    ms = MissionStore(db_path=str(tmp_path / "missions.db"))
    created = []

    class _FakeApp:
        _mission_store = ms

        @staticmethod
        async def _run_mission_and_deliver(mid):
            created.append(mid)
            return ms.get(mid)

    import server.app as sa
    monkeypatch.setattr(sa, "_mission_store", ms)
    monkeypatch.setattr(sa, "_run_mission_and_deliver", _FakeApp._run_mission_and_deliver)

    m = {"name": "文件", "source": "x.txt", "action": "分析", "attention": "urgent"}
    asyncio.run(at._handle_monitor_change(m, "aaa", "bbb"))
    assert len(created) == 1
    mission = ms.get(created[0])
    assert mission is not None
    assert "监控" in mission["goal"]


def test_handle_monitor_low_no_mission(tmp_path, monkeypatch):
    import server.async_tasks as at
    import server.app as sa

    ms = MissionStore(db_path=str(tmp_path / "missions.db"))
    monkeypatch.setattr(sa, "_mission_store", ms)
    called = []
    monkeypatch.setattr(sa, "_run_mission_and_deliver", lambda mid: called.append(mid))

    m = {"name": "静默", "source": "y.txt", "action": "x", "attention": "low"}
    asyncio.run(at._handle_monitor_change(m, "a", "b"))
    assert called == []
    assert ms.list() == []


def test_handle_monitor_normal_enqueues_digest(tmp_path, monkeypatch):
    import server.async_tasks as at
    from core.briefing import load_monitor_digest_queue
    from config import Config

    monkeypatch.setattr(Config, "LOG_DIR", str(tmp_path))
    m = {"name": "价格", "source": "p.txt", "action": "分析", "attention": "normal"}
    asyncio.run(at._handle_monitor_change(m, "old", "newhash"))
    rows = load_monitor_digest_queue(str(tmp_path))
    assert len(rows) == 1
    assert rows[0]["name"] == "价格"


def test_briefing_context_varies_by_state(tmp_path):
    """模拟不同日 journal/mission 状态,简报 context 应变化(三段式结构不变)。"""
    log_dir = str(tmp_path)
    os.makedirs(log_dir, exist_ok=True)
    journal = os.path.join(log_dir, "journal.md")
    with open(journal, "w", encoding="utf-8") as f:
        f.write("## 2026-07-01\n- 完成 A\n")
    ctx_a = build_daily_briefing_context(log_dir=log_dir, mission_store=None)

    with open(journal, "w", encoding="utf-8") as f:
        f.write("## 2026-07-02\n- 完成 B\n")
    ms = MissionStore(db_path=str(tmp_path / "m2.db"))
    m = ms.create("新任务")
    ms.set_tasks(m["id"], ["步骤1"])
    ms.set_status(m["id"], "planning")
    ms.set_status(m["id"], "executing")
    ctx_b = build_daily_briefing_context(log_dir=log_dir, mission_store=ms)

    for ctx in (ctx_a, ctx_b):
        assert "今日待办" in ctx
        assert "需决策" in ctx or "需关注" in ctx
    assert ctx_a != ctx_b
    assert "新任务" in ctx_b
    assert "完成 A" in ctx_a or "协作" in ctx_a


def test_plan_prompt_includes_goals():
    from core.mission_runner import _plan_prompt
    p = _plan_prompt("做报告", ["增长", "自动化"])
    assert "增长" in p
    assert "做报告" in p
