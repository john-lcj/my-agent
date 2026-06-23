"""主动监控回归 —— store 增删、due 调度、能力注册。"""
from __future__ import annotations

import asyncio
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from memory.monitor_store import MonitorStore


def test_create_list_delete(tmp_path):
    st = MonitorStore(path=str(tmp_path / "m.json"))
    rec = st.create(name="盯首页", source_type="url", source="https://x/feed",
                    action="提醒我", interval_sec=60)
    assert rec["id"] and rec["interval_sec"] == 60
    assert len(st.list()) == 1
    assert st.delete(rec["id"]) is True
    assert st.list() == []


def test_interval_floor_60(tmp_path):
    st = MonitorStore(path=str(tmp_path / "m.json"))
    rec = st.create(name="x", source_type="url", source="s", action="a", interval_sec=5)
    assert rec["interval_sec"] == 60   # 下限 60s


def test_due_respects_interval(tmp_path):
    st = MonitorStore(path=str(tmp_path / "m.json"))
    rec = st.create(name="x", source_type="file", source="f", action="a", interval_sec=100)
    now = time.time()
    assert len(st.due(now)) == 1            # 从没查过 → 到点
    st.update_state(rec["id"], "h1", now)
    assert st.due(now) == []                # 刚查过 → 没到点
    assert len(st.due(now + 200)) == 1      # 过了间隔 → 又到点


def test_caps_registered():
    os.environ.setdefault("AGENT_LLM_PROVIDER", "mock")
    from core.bootstrap import build_registry
    reg = build_registry(profile="interactive")
    for n in ("monitor.create", "monitor.list", "monitor.delete"):
        assert reg.get(n) is not None
