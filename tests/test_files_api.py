"""工作区文件树 API 回归(右侧"项目文件"用)。"""
from __future__ import annotations

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_files_api_lists_and_blocks_escape():
    try:
        from fastapi.testclient import TestClient
    except Exception:
        return  # 无 testclient 跳过
    d = tempfile.mkdtemp()
    os.makedirs(os.path.join(d, "sub"))
    open(os.path.join(d, "a.py"), "w").write("x")
    open(os.path.join(d, "sub", "b.md"), "w").write("# h")
    os.environ["AGENT_WORKSPACE_ROOT"] = d
    os.environ["AGENT_API_TOKEN"] = "t"
    try:
        import server.app as app
        c = TestClient(app.app)
        h = {"X-Agent-Token": "t"}
        j = c.get("/api/files", headers=h).json()
        assert j["ok"] and {i["name"] for i in j["items"]} == {"sub", "a.py"}
        # 目录在前
        assert j["items"][0]["type"] == "dir"
        # 进子目录
        j2 = c.get("/api/files?dir=sub", headers=h).json()
        assert [i["name"] for i in j2["items"]] == ["b.md"]
        # 越界拦截
        assert c.get("/api/files?dir=../etc", headers=h).status_code == 400
    finally:
        os.environ.pop("AGENT_WORKSPACE_ROOT", None)
        os.environ.pop("AGENT_API_TOKEN", None)
