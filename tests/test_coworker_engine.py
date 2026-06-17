"""Coworker 引擎:极致工作模式强制派子代理(DAG),闲聊仍由 Captain 直接答。"""
from __future__ import annotations

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agents.coordinator import Coordinator
from agents.registry import AgentRegistry
from core.context import Context


class _StubMain:
    async def run(self, task, ctx, confirm, **kw):
        return "main:" + task


class _StubWorker:
    name = "executor"; role = "可写执行者"; description = "x"


def _build():
    reg = AgentRegistry(); reg.register(_StubWorker())
    c = Coordinator(main_agent=_StubMain(), worker_registry=reg,
                    dispatcher=object(), graph_dispatcher=object())
    calls = {}

    async def fake_escalate(task, ctx, confirm, summary, direct=False):
        calls["direct"] = direct; calls["task"] = task
        return "escalated"
    c._escalate_to_expert = fake_escalate
    return c, calls


def _ctx(coworker):
    ctx = Context(); ctx.coworker = coworker
    return ctx


def test_coworker_forces_dispatch_for_real_task():
    c, calls = _build()
    r = asyncio.run(c.run("帮我做个介绍产品的网页", _ctx(True), lambda *a, **k: True))
    assert r == "escalated" and calls["direct"] is True   # 强制 direct=True 直接走 DAG


def test_coworker_chat_still_answered_by_captain():
    c, calls = _build()
    r = asyncio.run(c.run("你好", _ctx(True), lambda *a, **k: True))
    assert r.startswith("main:") and "direct" not in calls  # 闲聊不派


def test_non_coworker_short_task_not_forced():
    c, calls = _build()
    r = asyncio.run(c.run("读一下 config.py", _ctx(False), lambda *a, **k: True))
    assert r != "escalated"   # 非 coworker 的短任务不被强制派
