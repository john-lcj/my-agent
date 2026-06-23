"""分享/导出回归 —— 快照存储 + 公开只读页 + 导出 md(离线)。"""
from __future__ import annotations

import os
import sys

os.environ.setdefault("AGENT_LLM_PROVIDER", "mock")
os.environ["AGENT_API_TOKEN"] = "t"
os.environ["AGENT_INBOX_WATCH"] = "0"
os.environ["AGENT_MONITOR_WATCH"] = "0"

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from memory.share_store import ShareStore


def test_store_create_get_delete(tmp_path):
    st = ShareStore(path=str(tmp_path / "sh.json"))
    tok = st.create("conversation", "测试对话",
                    {"messages": [{"role": "user", "content": "你好"},
                                  {"role": "assistant", "content": "你好,有什么事"}]})
    assert tok and len(tok) > 8
    rec = st.get(tok)
    assert rec["kind"] == "conversation" and rec["title"] == "测试对话"
    assert st.delete(tok) is True and st.get(tok) is None


def test_public_share_page_renders(tmp_path, monkeypatch):
    from config import Config
    monkeypatch.setattr(Config, "LOG_DIR", str(tmp_path))
    # 直接往 store 写一条,再走公开页(/share 不在 /api 下,无需 token)
    ShareStore(path=str(tmp_path / "shares.json")).create(
        "conversation", "我的对话",
        {"messages": [{"role": "user", "content": "讲个笑话"},
                      {"role": "assistant", "content": "为什么程序员分不清万圣节和圣诞节"}]})
    # 取刚写入的 token
    import json
    data = json.load(open(tmp_path / "shares.json", encoding="utf-8"))
    token = next(iter(data))
    from fastapi.testclient import TestClient
    from server.app import app
    with TestClient(app) as c:
        r = c.get(f"/share/{token}")     # 公开,无 token 头
        assert r.status_code == 200
        assert "我的对话" in r.text and "讲个笑话" in r.text and "只读快照" in r.text
        # 不存在的 token → 404
        assert c.get("/share/nope").status_code == 404


def test_export_md_endpoint(monkeypatch):
    os.environ["AGENT_API_TOKEN"] = "t"
    from fastapi.testclient import TestClient
    from server.app import app
    with TestClient(app) as c:
        r = c.get("/api/sessions/whatever/export.md", headers={"X-Agent-Token": "t"})
        assert r.status_code == 200
        assert "text/markdown" in r.headers.get("content-type", "")
        assert r.text.startswith("#")    # markdown 标题
