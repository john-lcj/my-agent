"""简报预览 API。"""
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
    os.environ["AGENT_API_TOKEN"] = "smoke-tok"
    import server.app as app
    return TestClient(app.app)


def test_briefing_preview_endpoint():
    c = _client()
    if c is None:
        return
    r = c.get("/api/briefing/preview", headers=_H)
    assert r.status_code == 200
    body = r.json()
    assert "context" in body
    assert "body" in body
    assert isinstance(body["context"], str)
    assert "Captain 每日简报" in body["body"]
