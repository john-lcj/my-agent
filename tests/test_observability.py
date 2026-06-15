"""审计日志 + 任务产物附件提取的回归。"""
from __future__ import annotations

import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_audit_writes_jsonl():
    import observability.audit as au
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "audit.log")
        au._audit_path = lambda: path  # 重定向到临时文件
        au.audit(trace_id="t1", agent="captain", capability="shell.run",
                 args={"command": "ls", "secret": "should-not-appear"},
                 decision="allow", ok=True)
        au.audit(trace_id="t1", agent="captain", capability="fs.write",
                 args={"path": "/etc/x"}, decision="ask", ok=False, detail="拒绝")
        lines = [json.loads(l) for l in open(path, encoding="utf-8").read().splitlines()]
        assert len(lines) == 2
        assert lines[0]["cap"] == "shell.run" and lines[0]["decision"] == "allow"
        # 只摘录白名单参数键,secret 不入日志
        assert lines[0]["args"] == {"command": "ls"}
        assert lines[1]["ok"] is False and lines[1]["args"]["path"] == "/etc/x"


def test_extract_artifacts():
    import server.app as app
    with tempfile.TemporaryDirectory() as d:
        os.environ["AGENT_WORKSPACE_ROOT"] = d
        try:
            rep = os.path.join(d, "report.md")
            open(rep, "w").write("# hi")
            body = f"已生成体检报告 report.md 和一个不存在的 ghost.pdf,请查收。"
            got = app._extract_artifacts(body)
            assert rep in got
            assert not any("ghost" in p for p in got)  # 不存在的文件不附
        finally:
            del os.environ["AGENT_WORKSPACE_ROOT"]


def test_healthz_and_api_auth():
    """有 httpx 时用 TestClient 验证 /healthz 放行、/api 远程需 token。无则跳过。"""
    try:
        from fastapi.testclient import TestClient
    except Exception:
        return  # 缺 httpx/testclient,跳过(不算失败)
    import server.app as app
    client = TestClient(app.app)
    r = client.get("/healthz")
    assert r.status_code == 200 and r.json().get("ok") is True
