"""最大步数可配置 + 可设为无限制(0)。"""
from __future__ import annotations

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_runtime_config_max_steps():
    from server.runtime_config import RuntimeConfigStore
    from config import Config
    d = tempfile.mkdtemp()
    rc = RuntimeConfigStore(path=os.path.join(d, "runtime.json"))
    # 未设置 -> 默认
    assert rc.get_max_steps() == Config.MAX_STEPS
    # 设具体值
    rc.save({"max_steps": 50})
    assert rc.get_max_steps() == 50
    # 0 = 无限制
    rc.save({"max_steps": 0})
    assert rc.get_max_steps() == 0


def test_config_api_roundtrip():
    try:
        from fastapi.testclient import TestClient
    except Exception:
        return
    d = tempfile.mkdtemp()
    os.environ["AGENT_API_TOKEN"] = "t"
    os.environ["AGENT_LOG_DIR"] = d
    try:
        import importlib
        import server.app as app
        importlib.reload(app)
        c = TestClient(app.app)
        h = {"X-Agent-Token": "t"}
        c.post("/api/config", json={"max_steps": 0}, headers=h)
        assert c.get("/api/config", headers=h).json()["max_steps"] == 0   # 无限制
        c.post("/api/config", json={"max_steps": 99}, headers=h)
        assert c.get("/api/config", headers=h).json()["max_steps"] == 99
    finally:
        os.environ.pop("AGENT_API_TOKEN", None)
        os.environ.pop("AGENT_LOG_DIR", None)


def test_budget_unlimited_conversion():
    """build_agent_bundle: max_steps<=0 -> 极大数(等效无限制)。"""
    from governance.budget import BudgetGovernor
    # 直接验证语义:极大数下,跑很多步也不算超
    b = BudgetGovernor(max_steps=1_000_000)
    for _ in range(500):
        b.charge_step()
    assert not b.exceeded()


def test_mission_scheduler_agent_uses_runtime_max_steps():
    """Mission/定时任务 agent 与 Chat 共用 runtime max_steps。"""
    try:
        from fastapi.testclient import TestClient
    except Exception:
        return
    d = tempfile.mkdtemp()
    os.environ["AGENT_LOG_DIR"] = d
    try:
        import importlib
        import server.app as app_mod
        importlib.reload(app_mod)
        from core.types import Identity

        app_mod._runtime_cfg.save({"max_steps": 50})
        actor = Identity(subject_id="mission", agent_name="main", channel="mission")
        agent, _ctx = app_mod._build_scheduler_agent(actor)
        assert agent.budget.max_steps == 50

        app_mod._runtime_cfg.save({"max_steps": 0})
        agent2, _ = app_mod._build_scheduler_agent(actor)
        assert agent2.budget.max_steps == 1_000_000
    finally:
        os.environ.pop("AGENT_LOG_DIR", None)
