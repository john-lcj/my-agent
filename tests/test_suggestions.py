"""主动建议回归 —— store 增改、能力注册、API 接受(→入队)/忽略。"""
from __future__ import annotations

import os
import sys

os.environ.setdefault("AGENT_LLM_PROVIDER", "mock")
os.environ["AGENT_API_TOKEN"] = "t"
os.environ["AGENT_INBOX_WATCH"] = "0"
os.environ["AGENT_MONITOR_WATCH"] = "0"

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from memory.suggestions_store import SuggestionsStore


def _tok():
    os.environ["AGENT_API_TOKEN"] = "t"


def test_store_add_dedup_status(tmp_path):
    st = SuggestionsStore(path=str(tmp_path / "s.json"))
    r = st.add("今天先把报告写完", kind="plan", action="续写报告")
    assert r["status"] == "pending" and r["kind"] == "plan"
    st.add("今天先把报告写完", kind="plan")        # 同文本 pending → 不重复
    assert len(st.pending()) == 1
    st.set_status(r["id"], "accepted")
    assert st.pending() == []


def test_caps_registered():
    from core.bootstrap import build_registry
    reg = build_registry(profile="interactive")
    assert reg.get("suggest.add") is not None
    assert reg.get("suggest.list") is not None


def test_api_list_accept_dismiss(tmp_path, monkeypatch):
    _tok()
    from config import Config
    monkeypatch.setattr(Config, "LOG_DIR", str(tmp_path))
    SuggestionsStore(path=str(tmp_path / "suggestions.json")).add(
        "昨天的爬虫没跑完,我想到用 API 直接拉,要试试吗?", kind="resume", action="用 API 重做爬虫")
    from fastapi.testclient import TestClient
    from server.app import app
    H = {"X-Agent-Token": "t"}
    with TestClient(app) as c:
        rows = c.get("/api/suggestions", headers=H).json()["suggestions"]
        assert rows and rows[0]["kind"] == "resume"
        sid = rows[0]["id"]
        acc = c.post(f"/api/suggestions/{sid}/accept", headers=H).json()
        assert acc["ok"] and acc["task_id"]          # 有 action → 入队执行
        assert c.get("/api/suggestions", headers=H).json()["suggestions"] == []  # 不再 pending
        # 忽略不存在的 → ok False
        assert c.post("/api/suggestions/nope/dismiss", headers=H).json()["ok"] is False
