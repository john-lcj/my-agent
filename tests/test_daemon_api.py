"""后台任务投递入口回归 —— HTTP /api/task 入队 + 状态查询。

只验证 API 契约(入队成功、能查到记录、未知任务 404),不等待 LLM 执行完成。
"""
from __future__ import annotations

import os
import sys

os.environ.setdefault("AGENT_LLM_PROVIDER", "mock")
os.environ["AGENT_INBOX_WATCH"] = "0"  # 测试里关掉收件箱轮询,避免动文件系统
os.environ["AGENT_API_TOKEN"] = "t"    # /api/* 非 loopback 鉴权:带 token 头

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient

from server.app import app

H = {"X-Agent-Token": "t"}


def _tok():
    # 其它测试可能改动该 env(顺序无关性):每个请求前强制设回。
    os.environ["AGENT_API_TOKEN"] = "t"


def test_submit_and_query_task():
    _tok()
    with TestClient(app) as c:
        r = c.post("/api/task", json={"text": "（测试）整理一下今天的待办", "mode": "coworker"}, headers=H)
        assert r.status_code == 200, r.text
        tid = r.json()["task_id"]
        assert tid
        # 立即查:应能查到记录,并使用结构化执行状态。
        g = c.get(f"/api/task/{tid}", headers=H)
        assert g.status_code == 200
        rec = g.json()["task"]
        assert rec["id"] == tid
        assert rec["status"] in (
            "queued", "running", "succeeded", "partial", "blocked",
            "failed", "delivery_failed",
        )
        assert rec["source"] == "api"


def test_missing_text_rejected():
    _tok()
    with TestClient(app) as c:
        r = c.post("/api/task", json={"text": "  "}, headers=H)
        assert r.status_code == 400


def test_unknown_task_404():
    _tok()
    with TestClient(app) as c:
        r = c.get("/api/task/deadbeefdead", headers=H)
        assert r.status_code == 404
