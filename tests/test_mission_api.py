"""Mission 接口 —— 用独立 FastAPI app + 假 start_mission,纯测路由(不打真 LLM)。"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _app(tmp_path):
    from fastapi import FastAPI
    from server.routers.mission import register_missions
    from memory.mission_store import MissionStore
    store = MissionStore(db_path=str(tmp_path / "m.db"))
    started = []
    app = FastAPI()
    register_missions(app, store, lambda mid: started.append(mid))
    return app, store, started


def test_create_list_get(tmp_path):
    try:
        from fastapi.testclient import TestClient
    except Exception:
        return
    app, store, started = _app(tmp_path)
    c = TestClient(app)
    r = c.post("/api/mission", json={"goal": "写德国市场分析", "attention_level": 2})
    assert r.status_code == 200 and r.json()["ok"]
    mid = r.json()["mission"]["id"]
    assert started == [mid]                       # 创建后后台启动被触发
    assert any(m["id"] == mid for m in c.get("/api/missions").json()["missions"])
    assert c.get(f"/api/mission/{mid}").json()["goal"] == "写德国市场分析"
    assert c.get("/api/mission/nope").status_code == 404


def test_create_with_preset_tasks(tmp_path):
    try:
        from fastapi.testclient import TestClient
    except Exception:
        return
    app, store, started = _app(tmp_path)
    c = TestClient(app)
    mid = c.post("/api/mission", json={"goal": "g", "tasks": ["a", "b", "c"]}).json()["mission"]["id"]
    assert [t["text"] for t in store.get(mid)["tasks"]] == ["a", "b", "c"]


def test_missing_goal_and_cancel(tmp_path):
    try:
        from fastapi.testclient import TestClient
    except Exception:
        return
    app, store, started = _app(tmp_path)
    c = TestClient(app)
    assert c.post("/api/mission", json={}).status_code == 400
    mid = c.post("/api/mission", json={"goal": "可取消"}).json()["mission"]["id"]
    assert c.post(f"/api/mission/{mid}/cancel").json()["ok"]
    assert store.get(mid)["status"] == "cancelled"
    # 已取消(终态)再取消 → 400
    assert c.post(f"/api/mission/{mid}/cancel").status_code == 400
