"""历史产物检索 API:递归列产物、按文件名搜索、越界目录跳过。"""
from __future__ import annotations

import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_artifacts_list_and_search():
    try:
        from fastapi.testclient import TestClient
    except Exception:
        return
    d = tempfile.mkdtemp()
    os.makedirs(os.path.join(d, "sub"))
    open(os.path.join(d, "report.md"), "w").write("# r")
    time.sleep(0.01)
    open(os.path.join(d, "sub", "data.xlsx"), "w").write("x")
    open(os.path.join(d, "notes.bin"), "w").write("x")     # 非产物扩展名,应被过滤
    os.environ["AGENT_WORKSPACE_ROOT"] = d
    os.environ["AGENT_API_TOKEN"] = "t"
    try:
        import server.app as app
        c = TestClient(app.app)
        h = {"X-Agent-Token": "t"}
        j = c.get("/api/artifacts", headers=h).json()
        names = {i["name"] for i in j["items"]}
        assert "report.md" in names and "data.xlsx" in names
        assert "notes.bin" not in names                      # 非产物被过滤
        # 子目录里的也要被递归到(返回 rel 含 sub）
        rels = {i["rel"] for i in j["items"]}
        assert any(r.endswith(os.path.join("sub", "data.xlsx")) for r in rels)
        # 搜索
        j2 = c.get("/api/artifacts?q=report", headers=h).json()
        assert {i["name"] for i in j2["items"]} == {"report.md"}
    finally:
        os.environ.pop("AGENT_WORKSPACE_ROOT", None)
        os.environ.pop("AGENT_API_TOKEN", None)
