from __future__ import annotations

import importlib
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_license_admin_page_does_not_expose_admin_token(tmp_path, monkeypatch):
    try:
        from fastapi.testclient import TestClient
    except Exception:
        return

    monkeypatch.setenv("ADMIN_TOKEN", "super-secret-admin-token")
    monkeypatch.setenv("DB_PATH", str(tmp_path / "license.db"))
    import license_server.main as lm
    lm = importlib.reload(lm)

    with TestClient(lm.app) as client:
        r = client.get("/admin")
        assert r.status_code == 200
        assert "super-secret-admin-token" not in r.text
        assert "X-Admin-Token" in r.text


def test_license_admin_generate_and_list(tmp_path, monkeypatch):
    try:
        from fastapi.testclient import TestClient
    except Exception:
        return

    monkeypatch.setenv("ADMIN_TOKEN", "admin-token")
    monkeypatch.setenv("DB_PATH", str(tmp_path / "license.db"))
    import license_server.main as lm
    lm = importlib.reload(lm)

    with TestClient(lm.app) as client:
        h = {"X-Admin-Token": "admin-token"}
        r = client.post("/api/license/generate", headers=h, json={
            "plan": "pro", "months": 12, "n": 2, "note": "pytest", "max_devices": 3,
        })
        assert r.status_code == 200
        assert len(r.json()["keys"]) == 2
        listed = client.get("/api/license/list", headers=h).json()
        assert listed["stats"]["total"] == 2
        assert all(k["note"] == "pytest" for k in listed["keys"])
