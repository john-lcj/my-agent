"""final_gate 证据与不确定性门禁。"""
from __future__ import annotations

from core.task_lifecycle import TaskFrame, final_gate
from core.uncertainty import gate_unverified_facts
from core.verification import Verification, append_verification


def test_final_gate_requires_evidence(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_WORKSPACE_ROOT", str(tmp_path))
    tf = TaskFrame(objective="写报告", role="executor", task_kind="doc")
    append_verification(tf, "read_file", "产物/r.md")
    p = tmp_path / "产物" / "r.md"
    p.parent.mkdir(parents=True)
    p.write_text("report body here", encoding="utf-8")
    assert final_gate(tf, "已完成。")


def test_final_gate_passes_with_evidence(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_WORKSPACE_ROOT", str(tmp_path))
    tf = TaskFrame(objective="写报告", role="executor", task_kind="doc")
    append_verification(tf, "read_file", "产物/r.md")
    p = tmp_path / "产物" / "r.md"
    p.parent.mkdir(parents=True)
    p.write_text("report body here", encoding="utf-8")
    assert not final_gate(tf, "已完成,回读片段: report body here")


def test_uncertainty_gate_blocks_bare_stats():
    gate = gate_unverified_facts("2024年营收增长 35.2%。", [])
    assert gate
