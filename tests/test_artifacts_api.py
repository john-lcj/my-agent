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
        # 图片 raw 端点
        png = os.path.join(d, "pic.png")
        with open(png, "wb") as f:
            f.write(b"\x89PNG\r\n\x1a\n")
        rel = "pic.png"
        r = c.get(f"/api/artifact/raw?path={rel}", headers=h)
        assert r.status_code == 200 and r.headers["content-type"].startswith("image/")
        meta = c.get(f"/api/artifact?path={rel}", headers=h).json()
        assert meta.get("kind") == "image"
    finally:
        os.environ.pop("AGENT_WORKSPACE_ROOT", None)
        os.environ.pop("AGENT_API_TOKEN", None)


def test_save_artifact_writes_file_and_appears_in_list():
    """写作助手「保存到产物」按钮对应的后端接口:POST /api/artifacts。"""
    try:
        from fastapi.testclient import TestClient
    except Exception:
        return
    d = tempfile.mkdtemp()
    os.environ["AGENT_WORKSPACE_ROOT"] = d
    os.environ["AGENT_API_TOKEN"] = "t"
    try:
        import server.app as app
        c = TestClient(app.app)
        h = {"X-Agent-Token": "t"}
        r = c.post("/api/artifacts", json={"filename": "写作结果.md", "content": "# hello"}, headers=h)
        assert r.status_code == 200
        body = r.json()
        assert body["ok"] is True
        assert body["rel"] == "产物/写作结果.md"
        saved = os.path.join(d, "产物", "写作结果.md")
        assert os.path.isfile(saved)
        assert open(saved, encoding="utf-8").read() == "# hello"
        # 路径穿越前缀应被 basename() 剥离,只落在产物目录内
        r2 = c.post("/api/artifacts", json={"filename": "../../evil.md", "content": "x"}, headers=h)
        assert r2.json()["ok"] is True
        assert not os.path.isfile(os.path.join(os.path.dirname(d), "evil.md"))
        assert os.path.isfile(os.path.join(d, "产物", "evil.md"))
        # 缺文件名应报错
        r3 = c.post("/api/artifacts", json={"content": "x"}, headers=h)
        assert r3.status_code == 400

        office = os.path.join(d, "产物", "客户报告 2026.docx")
        with open(office, "wb") as f:
            f.write(b"PK\x03\x04office")
        rel = "产物/客户报告 2026.docx"
        meta = c.get("/api/artifact", params={"path": rel}, headers=h).json()
        assert meta["ok"] is True and meta["kind"] == "office"
        file_response = c.get("/api/artifact/file", params={"path": rel}, headers=h)
        assert file_response.status_code == 200
        assert file_response.content.startswith(b"PK")
        listed = c.get("/api/artifacts", headers=h).json()["items"]
        assert any(item["rel"] == rel for item in listed)
    finally:
        os.environ.pop("AGENT_WORKSPACE_ROOT", None)
        os.environ.pop("AGENT_API_TOKEN", None)
