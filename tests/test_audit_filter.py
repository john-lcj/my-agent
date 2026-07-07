"""审计筛选。"""
from __future__ import annotations

import json

from observability.audit import read_recent


def test_audit_filter_by_capability(tmp_path, monkeypatch):
    log = tmp_path / "audit.log"
    monkeypatch.setattr("observability.audit._audit_path", lambda: str(log))
    with open(log, "w", encoding="utf-8") as f:
        f.write(json.dumps({"cap": "fs.write", "agent": "main", "decision": "allow", "ok": True}) + "\n")
        f.write(json.dumps({"cap": "shell.run", "agent": "main", "decision": "block", "ok": False}) + "\n")
    rows = read_recent(10, capability="fs.write")
    assert len(rows) == 1
    assert rows[0]["cap"] == "fs.write"
