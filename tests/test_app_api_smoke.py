"""控制面接口冒烟 —— 覆盖一批此前没测到的 GET/写接口,为 app.py 拆分搭安全网。

策略:建一个 TestClient,带 token 打各 /api/* 接口,断言可达 + 基本结构。
GET 类只读、零副作用;写类用"建了即删"自清理,不污染状态。
"""
from __future__ import annotations

import os
import sys
import tempfile
import urllib.error
import zipfile
from io import BytesIO

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


def test_frontend_assets_served():
    # 前端拆分后:index + 三个静态资源都要能服务,且通配没遮蔽 /healthz
    c = _client()
    if c is None:
        return
    index = c.get("/")
    assert index.status_code == 200
    assert "no-store" in index.headers.get("cache-control", "")
    for asset, mime in [("/styles.css", "text/css"),
                        ("/app.js", "javascript"),
                        ("/app.boot.js", "javascript")]:
        r = c.get(asset, headers=_H)
        assert r.status_code == 200, f"{asset} → {r.status_code}"
        assert mime in r.headers.get("content-type", "")
        assert "no-store" in r.headers.get("cache-control", "")
    # 显式路由不应抢掉 /healthz
    assert c.get("/healthz").status_code == 200


def test_readonly_endpoints_reachable():
    c = _client()
    if c is None:
        return
    # 这些 GET 接口应 200 且返回 JSON(覆盖各自 handler)
    for path in ["/api/config", "/api/models", "/api/skills", "/api/commands",
                 "/api/connectors", "/api/templates", "/api/goals", "/api/secrets",
                 "/api/monitors", "/api/suggestions", "/api/stats", "/api/usage",
                 "/api/governance/stats", "/api/audit", "/api/keys", "/api/channels",
                 "/api/briefing/preview",
                 "/api/sessions", "/api/projects", "/api/tasks", "/api/memory/preferences"]:
        r = c.get(path, headers=_H)
        assert r.status_code == 200, f"{path} → {r.status_code}"
        r.json()   # 可解析为 JSON


def test_model_picker_api_exposes_truthful_availability():
    c = _client()
    if c is None:
        return
    models = c.get("/api/models?all=true", headers=_H).json()["models"]
    assert models
    for model in models:
        assert {"configured", "verified", "available"}.issubset(model)
        assert model["available"] is bool(model["configured"] and model["verified"])
    ollama = next((model for model in models if model["id"] == "ollama-local"), None)
    if ollama and not ollama["verified"]:
        assert ollama["available"] is False


def test_system_diagnostics_and_update_check(monkeypatch):
    c = _client()
    if c is None:
        return
    import server.routers.system as system_routes

    monkeypatch.setattr(system_routes, "_latest_update_manifest", lambda: {
        "version": "9.9.9",
        "contract_version": 1,
        "platforms": {
            "darwin-aarch64": {
                "url": "https://github.com/john-lcj/my-agent/releases/download/v9.9.9/Captain_9.9.9_arm64.app.tar.gz",
                "signature": "signed-value",
            }
        },
    })
    r = c.get("/api/system/update/check", headers=_H)
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True and body["latest"] == "9.9.9"
    assert body["download_url"].endswith(".app.tar.gz")
    assert body["signed"] is True

    r = c.get("/api/system/diagnostics", headers=_H)
    assert r.status_code == 200
    diagnostics = r.json()
    assert diagnostics["ok"] is True
    assert diagnostics["version"]
    assert diagnostics["commit"]
    assert diagnostics["frontend_asset_hash"]
    assert "database_schema" in diagnostics
    assert set(diagnostics["leader"]) == {"backend", "workers"}

    r = c.get("/api/system/diagnostics/export", headers=_H)
    assert r.status_code == 200
    assert "zip" in r.headers.get("content-type", "")


def test_system_diagnostics_export_redacts_secrets(monkeypatch, tmp_path):
    c = _client()
    if c is None:
        return
    import server.routers.system as system_routes

    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    monkeypatch.setattr(system_routes.Config, "LOG_DIR", str(log_dir))
    (log_dir / "trace.jsonl").write_text(
        "OPENAI_API_KEY=sk-testsecret123456789\n"
        "token Bearer abcdefghijklmnopqrstuvwxyz\n",
        encoding="utf-8",
    )
    (log_dir / "audit.log").write_text(
        "github token ghp_1234567890abcdefghijklmnopqrstuv CAPT-PRO-ABCD-EFGH-IJKL\n",
        encoding="utf-8",
    )
    (log_dir / "runtime.json").write_text(
        '{"access_token":"remote-token-123456","auth_secret":"secret-value-123456"}',
        encoding="utf-8",
    )

    r = c.get("/api/system/diagnostics/export", headers=_H)
    assert r.status_code == 200
    with zipfile.ZipFile(BytesIO(r.content)) as z:
        names = set(z.namelist())
        assert "logs/trace.tail.jsonl" in names
        assert "logs/audit.tail.log" in names
        assert "config/runtime.json" in names
        combined = "\n".join(z.read(name).decode("utf-8", errors="replace") for name in names)

    assert "sk-testsecret123456789" not in combined
    assert "ghp_1234567890abcdefghijklmnopqrstuv" not in combined
    assert "CAPT-PRO-ABCD-EFGH-IJKL" not in combined
    assert "remote-token-123456" not in combined
    assert "secret-value-123456" not in combined
    assert "OPENAI_API_KEY=<redacted>" in combined
    assert "ghp_<redacted>" in combined
    assert "CAPT-PRO-<redacted>" in combined


def test_system_update_check_release_missing(monkeypatch):
    c = _client()
    if c is None:
        return
    import server.routers.system as system_routes

    def missing_release():
        raise urllib.error.HTTPError("https://example.com/latest.json", 404, "Not Found", None, None)

    monkeypatch.setattr(system_routes, "_latest_update_manifest", missing_release)
    r = c.get("/api/system/update/check", headers=_H)
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["release_missing"] is True
    assert "发布安装包" in body["message"]


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
