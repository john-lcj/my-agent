"""会话截断与消息反馈 API。"""
from __future__ import annotations

import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_session_truncate_and_feedback():
    try:
        from fastapi.testclient import TestClient
    except Exception:
        return
    d = tempfile.mkdtemp()
    db = os.path.join(d, "sessions.db")
    fb = os.path.join(d, "feedback.db")
    os.environ["AGENT_WORKSPACE_ROOT"] = d
    os.environ["AGENT_API_TOKEN"] = "t"
    try:
        from memory.session_store import SessionStore
        from memory.feedback_store import FeedbackStore

        store = SessionStore(db_path=db)
        store.ensure_session("s1")
        from core.types import Message, Role
        store.append("s1", Message(role=Role.USER, content="hello"))
        store.append("s1", Message(role=Role.ASSISTANT, content="hi"))
        store.append("s1", Message(role=Role.USER, content="again"))
        meta = store.list_messages_meta("s1")
        assert len(meta) == 3
        uid = meta[0]["id"]
        store.truncate_after("s1", uid)
        assert len(store.list_messages_meta("s1")) == 1
        store.append("s1", Message(role=Role.ASSISTANT, content="x"))
        mid = store.list_messages_meta("s1")[-1]["id"]
        store.truncate_from("s1", mid)
        assert len(store.list_messages_meta("s1")) == 1

        fbstore = FeedbackStore(db_path=fb)
        fbstore.upsert("s1", "id:1", 1)
        assert fbstore.get("s1", "id:1") == 1
        fbstore.upsert("s1", "id:1", 0)
        assert fbstore.get("s1", "id:1") is None

        import server.app as appmod
        appmod._feedback_store = fbstore
        c = TestClient(appmod.app)
        h = {"X-Agent-Token": "t"}
        r = c.post("/api/feedback", headers=h, json={
            "session_id": "s1", "msg_key": "id:9", "rating": -1,
        })
        assert r.json()["ok"] is True
        assert c.get("/api/feedback", headers=h, params={
            "session_id": "s1", "msg_key": "id:9",
        }).json()["rating"] == -1
    finally:
        os.environ.pop("AGENT_WORKSPACE_ROOT", None)
        os.environ.pop("AGENT_API_TOKEN", None)
