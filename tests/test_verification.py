"""verification 引擎单测。"""
from __future__ import annotations

import os

from core.task_lifecycle import TaskFrame, final_gate
from core.verification import Verification, append_verification, run_verification


def test_read_file_verification(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_WORKSPACE_ROOT", str(tmp_path))
    p = tmp_path / "产物" / "a.txt"
    p.parent.mkdir(parents=True)
    p.write_text("hello world", encoding="utf-8")
    v = Verification(kind="read_file", target="产物/a.txt")
    run_verification(v)
    assert v.status == "pass"
    assert "hello" in v.evidence


def test_final_gate_evidence(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_WORKSPACE_ROOT", str(tmp_path))
    tf = TaskFrame(objective="写文件", role="executor", task_kind="code")
    append_verification(tf, "read_file", "产物/x.md")
    p = tmp_path / "产物" / "x.md"
    p.parent.mkdir(parents=True)
    p.write_text("content here", encoding="utf-8")
    gate = final_gate(tf, "已完成,请查收。")
    assert gate  # 缺证据应打回
