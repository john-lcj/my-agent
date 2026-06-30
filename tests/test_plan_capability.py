"""待办清单能力:plan.update 规整入参 + loop 翻译成 plan_update 事件。"""
from __future__ import annotations

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from capabilities.tools.plan import PlanUpdate, normalize_steps


def test_normalize_steps_strings_and_dicts():
    assert normalize_steps(["查资料", "写报告"]) == [
        {"text": "查资料", "status": "todo"}, {"text": "写报告", "status": "todo"}]
    s = normalize_steps([{"text": "搜", "status": "done", "check": "有来源"}, {"task": "写", "status": "doing"}])
    assert s[0]["status"] == "done" and s[1]["text"] == "写" and s[1]["status"] == "doing"
    assert s[0]["check"] == "有来源"
    assert normalize_steps([{"text": "x", "status": "乱填"}])[0]["status"] == "todo"


def test_plan_update_invoke():
    r = asyncio.run(PlanUpdate().invoke(
        {"steps": [{"text": "a", "status": "done", "check": "a ok"}, {"text": "b", "status": "doing"}]}, None))
    assert r.ok and "完成 1" in r.output and "进行中 1" in r.output and "含验收 1" in r.output


def test_loop_emits_plan_events():
    """loop._emit_plan 把待办翻译成 {type:'plan'} + {type:'node'} 事件(Progress 面板用)。"""
    from core.loop import Agent
    from core.types import EventType
    events = []
    def emit(etype, payload):
        events.append((etype, payload))
    Agent._emit_plan(object.__new__(Agent), emit,
                     {"steps": [{"text": "查", "status": "done"},
                                {"text": "写", "status": "doing"},
                                {"text": "审", "status": "todo"}]})
    plan_evs = [p for et, p in events if et == EventType.PLAN_UPDATE]
    assert plan_evs[0]["type"] == "plan"
    assert [n["id"] for n in plan_evs[0]["nodes"]] == ["t1", "t2", "t3"]
    # done/doing 各发一个 node 事件,todo 不发
    nodes = [p for p in plan_evs if p["type"] == "node"]
    assert {(n["id"], n["status"]) for n in nodes} == {("t1", "done"), ("t2", "running")}
