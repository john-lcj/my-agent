"""会话级工作台状态持久化 —— meta 读写 + /api 工作目录/产物按会话固定。"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from memory.session_store import SessionStore


def test_meta_merge_and_persist(tmp_path):
    db = str(tmp_path / "s.db")
    s = SessionStore(db_path=db)
    s.ensure_session("sess1")
    s.merge_meta("sess1", {"workspace_dir": "/Users/me/proj"})
    s.merge_meta("sess1", {"artifacts": ["产物/a.md"]})
    m = s.get_meta("sess1")
    assert m["workspace_dir"] == "/Users/me/proj" and m["artifacts"] == ["产物/a.md"]
    # 跨重开仍在(SQLite 持久化)
    s2 = SessionStore(db_path=db)
    assert s2.get_meta("sess1")["workspace_dir"] == "/Users/me/proj"


def test_sessions_are_isolated(tmp_path):
    s = SessionStore(db_path=str(tmp_path / "s.db"))
    s.merge_meta("a", {"workspace_dir": "/dirA"})
    s.merge_meta("b", {"workspace_dir": "/dirB"})
    assert s.get_meta("a")["workspace_dir"] == "/dirA"
    assert s.get_meta("b")["workspace_dir"] == "/dirB"   # 不串


def _client(tmp_path):
    try:
        from fastapi.testclient import TestClient
    except Exception:
        return None
    os.environ["AGENT_API_TOKEN"] = "wb-tok"
    os.environ.setdefault("AGENT_WORKSPACE_ROOT", str(tmp_path))
    import server.app as app
    return TestClient(app.app)


def test_workbench_api_roundtrip(tmp_path):
    c = _client(tmp_path)
    if c is None:
        return
    import uuid
    h = {"X-Agent-Token": "wb-tok"}
    sid = "wbtest-" + uuid.uuid4().hex[:8]   # 随机 sid,避免复用真实库时跨运行污染
    # 初始为空
    assert c.get(f"/api/sessions/{sid}/workbench", headers=h).json()["workspace_dir"] == ""
    # 存工作目录
    c.post(f"/api/sessions/{sid}/workbench", headers=h, json={"workspace_dir": "/Users/me/proj"})
    # 产物累积去重
    c.post(f"/api/sessions/{sid}/workbench", headers=h, json={"artifacts": ["产物/x.md"]})
    c.post(f"/api/sessions/{sid}/workbench", headers=h, json={"artifacts": ["产物/x.md", "产物/y.html"]})
    # 执行进度快照(全量覆盖)
    c.post(f"/api/sessions/{sid}/workbench", headers=h,
           json={"plan": [{"id": "n1", "text": "调研", "done": True},
                          {"id": "n2", "text": "成文", "done": False}]})
    d = c.get(f"/api/sessions/{sid}/workbench", headers=h).json()
    assert d["workspace_dir"] == "/Users/me/proj"
    assert d["artifacts"] == ["产物/x.md", "产物/y.html"]   # 去重 + 累积
    assert len(d["plan"]) == 2 and d["plan"][0]["done"] is True
