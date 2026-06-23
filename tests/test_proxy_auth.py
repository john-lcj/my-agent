"""隧道/代理鉴权回归 —— 带 Cloudflare 头的请求强制要 token(堵 localhost 免密绕过)。"""
from __future__ import annotations

import os
import sys

os.environ.setdefault("AGENT_LLM_PROVIDER", "mock")
os.environ["AGENT_INBOX_WATCH"] = "0"
os.environ["AGENT_MONITOR_WATCH"] = "0"

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient
from server.app import app


def test_proxied_request_without_token_rejected():
    os.environ["AGENT_API_TOKEN"] = "t"
    with TestClient(app) as c:
        # 模拟 Cloudflare 隧道:带 cf-ray 头、无 token → 必须 401
        r = c.get("/api/models", headers={"cf-ray": "deadbeef-LHR"})
        assert r.status_code == 401


def test_proxied_request_with_token_ok():
    os.environ["AGENT_API_TOKEN"] = "t"
    with TestClient(app) as c:
        r = c.get("/api/models", headers={"cf-ray": "deadbeef-LHR", "X-Agent-Token": "t"})
        assert r.status_code == 200


def test_x_forwarded_for_also_triggers():
    os.environ["AGENT_API_TOKEN"] = "t"
    with TestClient(app) as c:
        r = c.get("/api/models", headers={"x-forwarded-for": "1.2.3.4"})
        assert r.status_code == 401
