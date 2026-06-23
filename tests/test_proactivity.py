"""主动反思引擎回归 —— 目标库、能力注册、巡检「无」抑制、上下文拼装。"""
from __future__ import annotations

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from memory.goals_store import GoalsStore


def test_goals_crud(tmp_path):
    g = GoalsStore(path=str(tmp_path / "g.json"))
    r = g.add("我在做 Captain 项目", "goal")
    assert r["id"] and r["kind"] == "goal"
    g.add("我在做 Captain 项目")          # 重复不再加
    assert len(g.list()) == 1
    assert g.active_texts() == ["我在做 Captain 项目"]
    assert g.remove(r["id"]) is True
    assert g.list() == []


def test_goal_caps_registered():
    os.environ.setdefault("AGENT_LLM_PROVIDER", "mock")
    from core.bootstrap import build_registry
    reg = build_registry(profile="interactive")
    for n in ("goal.set", "goal.list", "goal.remove"):
        assert reg.get(n) is not None


def test_patrol_no_news_suppressed(monkeypatch):
    # 巡检返回「无」→ 不应触发邮件投递(_deliver_result 不被调用)
    import server.app as app
    called = {"n": 0}

    async def _fake_deliver(*a, **k):
        called["n"] += 1
    monkeypatch.setattr(app, "_deliver_result", _fake_deliver)
    monkeypatch.setenv("EMAIL_USER", "me@x.com")
    asyncio.run(app._proactive_deliver("proactive", "无"))
    asyncio.run(app._proactive_deliver("proactive", "无。"))
    assert called["n"] == 0
    # 巡检有内容 → 投递
    asyncio.run(app._proactive_deliver("proactive", "发现 X 有更新,已整理到 产物/x.md。"))
    assert called["n"] == 1


def test_digest_always_delivers_when_body(monkeypatch):
    import server.app as app
    called = {"n": 0, "subj": ""}

    async def _fake_deliver(channel, to, subject, body):
        called["n"] += 1
        called["subj"] = subject
    monkeypatch.setattr(app, "_deliver_result", _fake_deliver)
    monkeypatch.setenv("EMAIL_USER", "me@x.com")
    asyncio.run(app._proactive_deliver("digest", "今天没什么大事,但建议你登记长期目标。"))
    assert called["n"] == 1 and "简报" in called["subj"]


def test_context_includes_goals(tmp_path, monkeypatch):
    import server.app as app
    from config import Config
    monkeypatch.setattr(Config, "LOG_DIR", str(tmp_path))
    GoalsStore(path=str(tmp_path / "goals.json")).add("关注 AI agent 进展", "interest")
    ctx = app._proactive_context()
    assert "关注 AI agent 进展" in ctx and "长期目标" in ctx
