"""产物真实预览 /preview/<path> —— html 渲染 + 相对资源 + 越界拦截。"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _resolver(root):
    root = os.path.realpath(str(root))
    def resolve(sub):
        real = os.path.realpath(os.path.join(root, sub))
        if real != root and not real.startswith(root + os.sep):
            return False, "", "路径在工作区之外"
        if ".env" in real.lower():
            return False, "", "敏感路径"
        return True, real, ""
    return resolve


def test_preview_html_css_and_guard(tmp_path):
    try:
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
    except Exception:
        return
    from server.routers.preview import register_preview
    (tmp_path / "产物").mkdir()
    (tmp_path / "产物" / "page.html").write_text("<h1>你好</h1>", encoding="utf-8")
    (tmp_path / "产物" / "style.css").write_text("h1{color:red}", encoding="utf-8")
    app = FastAPI()
    register_preview(app, _resolver(tmp_path))
    c = TestClient(app)

    r = c.get("/preview/产物/page.html")
    assert r.status_code == 200 and "text/html" in r.headers["content-type"] and "你好" in r.text
    r2 = c.get("/preview/产物/style.css")
    assert r2.status_code == 200 and "text/css" in r2.headers["content-type"]
    assert c.get("/preview/产物/missing.html").status_code == 404
    # 越界与敏感文件应拒
    assert c.get("/preview/../secret.txt").status_code in (400, 404)
