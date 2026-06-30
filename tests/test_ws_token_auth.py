from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_frontend_websocket_does_not_put_token_in_url():
    js = open("frontend/app.js", encoding="utf-8").read()
    assert "new WebSocket(`${proto}//${location.host}/ws`)" in js
    assert "/ws${_q}" not in js
    assert "?token=" not in js


def test_remote_websocket_accepts_first_frame_auth(monkeypatch):
    try:
        from fastapi.testclient import TestClient
    except Exception:
        return

    monkeypatch.setenv("AGENT_API_TOKEN", "ws-test-token")
    monkeypatch.setenv("AUTH_SECRET", "ws-test-secret")

    import server.app as appmod

    client = TestClient(appmod.app)
    with client.websocket_connect("/ws", headers={"X-Forwarded-For": "8.8.8.8"}) as ws:
        ws.send_json({"type": "auth", "token": "ws-test-token"})
        ws.send_json({"type": "init", "session_id": "s-ws-auth-test", "model": "mock", "mode": "chat"})
        msg = ws.receive_json()
        assert msg["type"] == "history"
