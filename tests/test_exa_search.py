"""Exa 搜索回归 —— 注册 + 入参校验 + 未配 key 清晰提示(离线,不发真实网络)。"""
from __future__ import annotations

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from capabilities.tools.exa_search import ExaSearch
from core.types import Risk


def test_registered_when_configured(monkeypatch):
    os.environ.setdefault("AGENT_LLM_PROVIDER", "mock")
    monkeypatch.setenv("EXA_API_KEY", "configured")
    from core.bootstrap import build_registry
    reg = build_registry(profile="interactive")
    assert reg.get("exa.search") is not None
    assert reg.get("exa.search").risk == Risk.READ


def test_hidden_when_unconfigured(monkeypatch):
    monkeypatch.delenv("EXA_API_KEY", raising=False)
    from core.bootstrap import build_registry
    reg = build_registry(profile="interactive")
    assert "exa.search" not in {item["name"] for item in reg.specs()}


def test_no_key_clear_error(monkeypatch):
    monkeypatch.delenv("EXA_API_KEY", raising=False)
    r = asyncio.run(ExaSearch().invoke({"query": "AI agent 最新进展"}, None))
    assert not r.ok and "EXA_API_KEY" in r.error


def test_missing_query(monkeypatch):
    monkeypatch.setenv("EXA_API_KEY", "k")
    r = asyncio.run(ExaSearch().invoke({"query": "  "}, None))
    assert not r.ok and "query" in r.error
