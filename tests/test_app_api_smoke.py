"""控制面接口冒烟 —— 覆盖一批此前没测到的 GET/写接口,为 app.py 拆分搭安全网。

策略:建一个 TestClient,带 token 打各 /api/* 接口,断言可达 + 基本结构。
GET 类只读、零副作用;写类用"建了即删"自清理,不污染状态。
"""
from __future__ import annotations

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("AGENT_WORKSPACE_ROOT", tempfile.mkdtemp())
_H = {"X-Agent-Token": "smoke-tok"}


def _client():
    try:
        from fastapi.testclient import TestClient
    except Exception:
        return None
    # 中间件实时读 env;强制设成本测试的 token(防被 .env 真实 token 或别的测试干扰)。
    os.environ["AGENT_API_TOKEN"] = "smoke-tok"
    import server.app as app
    return TestClient(app.app)


def test_health_and_manifest():
    c = _client()
    if c is None:
        return
    assert c.get("/healthz").status_code == 200
    assert c.get("/manifest.json", headers=_H).status_code == 200


def test_readonly_endpoints_reachable():
    c = _client()
    if c is None:
        return
    # 这些 GET 接口应 200 且返回 JSON(覆盖各自 handler)
    for path in ["/api/config", "/api/models", "/api/skills", "/api/commands",
                 "/api/connectors", "/api/templates", "/api/goals", "/api/secrets",
                 "/api/monitors", "/api/suggestions", "/api/stats", "/api/usage",
                 "/api/governance/stats", "/api/audit", "/api/keys", "/api/channels",
                 "/api/sessions", "/api/projects", "/api/tasks", "/api/memory/preferences"]:
        r = c.get(path, headers=_H)
        assert r.status_code == 200, f"{path} → {r.status_code}"
        r.json()   # 可解析为 JSON


def test_auth_required_for_remote():
    c = _client()
    if c is None:
        return
    # 不带 token + 伪装成远程(X-Forwarded-For)→ 控制面应 401
    r = c.get("/api/config", headers={"X-Forwarded-For": "8.8.8.8"})
    assert r.status_code == 401


def test_templates_crud_cycle():
    c = _client()
    if c is None:
        return
    created = c.post("/api/templates", headers=_H,
                     json={"title": "冒烟模板", "content": "x", "category": "测试"})
    assert created.status_code == 200
    tid = created.json().get("id") or created.json().get("template", {}).get("id")
    assert tid
    assert any(t["id"] == tid for t in c.get("/api/templates", headers=_H).json().get("templates", c.get("/api/templates", headers=_H).json()))
    assert c.delete(f"/api/templates/{tid}", headers=_H).status_code == 200


def test_goals_crud_cycle():
    c = _client()
    if c is None:
        return
    r = c.post("/api/goals", headers=_H, json={"text": "冒烟目标"})
    assert r.status_code == 200
    gid = None
    body = r.json()
    if isinstance(body, dict):
        gid = body.get("id") or (body.get("goal") or {}).get("id")
    if gid:
        assert c.delete(f"/api/goals/{gid}", headers=_H).status_code in (200, 404)
