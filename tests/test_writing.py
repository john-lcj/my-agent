"""专注写作回归 —— 助手改写端点 + 保存到产物(mock 模型,不发真实网络)。"""
from __future__ import annotations

import os
import sys

os.environ.setdefault("AGENT_LLM_PROVIDER", "mock")
os.environ["AGENT_API_TOKEN"] = "t"
os.environ["AGENT_INBOX_WATCH"] = "0"
os.environ["AGENT_MONITOR_WATCH"] = "0"

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient
from server.app import app

H = {"X-Agent-Token": "t"}


def _tok():
    os.environ["AGENT_API_TOKEN"] = "t"


def test_assist_needs_instruction():
    _tok()
    with TestClient(app) as c:
        r = c.post("/api/writing/assist", json={"text": "abc", "instruction": " "}, headers=H)
        assert r.status_code == 400


def test_assist_returns_text(monkeypatch):
    _tok()
    from core.types import Step

    class _FakeLLM:
        name = "fake"
        async def next_step(self, messages, capabilities, emit_token=None):
            return Step(text="今天天气晴朗,正适合出门走走。")
    import llm.factory as _f
    monkeypatch.setattr(_f, "build_llm", lambda *a, **k: _FakeLLM())
    with TestClient(app) as c:
        r = c.post("/api/writing/assist",
                   json={"text": "今天天气不错", "instruction": "润色这段"}, headers=H)
        assert r.status_code == 200
        d = r.json()
        assert d["ok"] is True and "晴朗" in d["text"]


def test_save_to_artifacts(tmp_path, monkeypatch):
    _tok()
    monkeypatch.setenv("AGENT_WORKSPACE_ROOT", str(tmp_path))
    with TestClient(app) as c:
        r = c.post("/api/writing/save",
                   json={"title": "我的稿子", "content": "正文内容"}, headers=H)
        assert r.status_code == 200
        d = r.json()
        assert d["ok"] is True and d["path"].endswith(".md")
        # 真落盘到 产物/
        assert (tmp_path / "产物" / "我的稿子.md").read_text(encoding="utf-8") == "正文内容"
