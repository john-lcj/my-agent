from __future__ import annotations

import json
import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_backup_export_filters_sensitive_files(tmp_path, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from config import Config
    from server.routers.backup import register_backup

    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    monkeypatch.setattr(Config, "LOG_DIR", str(log_dir))

    (log_dir / "runtime.json").write_text(json.dumps({"model": "mock"}), encoding="utf-8")
    (log_dir / "model_keys.json").write_text(json.dumps({"deepseek": "secret"}), encoding="utf-8")
    (tmp_path / ".env").write_text("AGENT_API_TOKEN=secret\nAUTH_SECRET=secret\n", encoding="utf-8")

    conn = sqlite3.connect(log_dir / "sessions.db")
    conn.executescript(
        """
        CREATE TABLE sessions (id TEXT PRIMARY KEY,title TEXT,created_at REAL,updated_at REAL,kind TEXT,meta TEXT,project_id TEXT);
        CREATE TABLE messages (id INTEGER PRIMARY KEY AUTOINCREMENT,session_id TEXT,role TEXT,content TEXT,name TEXT,tool_calls TEXT,tool_call_id TEXT,reasoning_content TEXT,ts REAL);
        INSERT INTO sessions VALUES ('s1','hello',1,1,'chat',NULL,NULL);
        INSERT INTO messages(session_id,role,content,ts) VALUES ('s1','user','hi',1);
        """
    )
    conn.commit()
    conn.close()

    app = FastAPI()
    register_backup(app)
    data = TestClient(app).get("/api/backup/export").json()

    assert data["ok"] if "ok" in data else data["app"] == "captain"
    raw = json.dumps(data, ensure_ascii=False)
    assert "AGENT_API_TOKEN" not in raw
    assert "AUTH_SECRET" not in raw
    assert "model_keys" not in raw
    assert data["data"]["sqlite"]["sessions.db"]["sessions"][0]["id"] == "s1"
    assert data["data"]["json"]["runtime"]["model"] == "mock"


def test_backup_import_rejects_invalid_payload(tmp_path, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from config import Config
    from server.routers.backup import register_backup

    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    monkeypatch.setattr(Config, "LOG_DIR", str(log_dir))

    app = FastAPI()
    register_backup(app)
    r = TestClient(app).post("/api/backup/import", json={"app": "other"})
    assert r.status_code == 400
    assert r.json()["ok"] is False
