"""P0–P6 路线图代码补齐回归。"""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.delivery_gate import delivery_reference_gate, unified_final_gate
from core.task_lifecycle import TaskFrame
from core.workflow_templates import apply_workflow_verifications, prompt_with_verifications, verification_marker
from memory.base import MemoryItem
from memory.longterm_sqlite import SQLiteMemory
from memory.task_rating import _heuristic_rating


def test_verification_marker():
    m = verification_marker([{"kind": "read_file", "target": "产物/x.md"}])
    assert "【自动验证项】" in m
    assert "read_file:产物/x.md" in m


def test_apply_workflow_verifications():
    tf = TaskFrame(objective="x", role="executor", task_kind="execute")
    apply_workflow_verifications(tf, "做报告\n【自动验证项】read_file:产物/a.md|run_test:pytest -q")
    kinds = {v.kind for v in tf.verification_items}
    assert "read_file" in kinds and "run_test" in kinds


def test_unified_gate_missing_file():
    tf = TaskFrame(objective="写报告", role="executor", task_kind="execute")
    gate = unified_final_gate(tf, "写报告", "已完成,见 产物/不存在.md")
    assert gate and "不存在" in gate


def test_stale_fact_recall(tmp_path):
    mem = SQLiteMemory(db_path=str(tmp_path / "m.db"))
    import time
    item = MemoryItem(kind="fact", content="旧事实", created_at=time.time() - 86400 * 200,
                      expires_at=time.time() - 3600)
    mem.store(item)
    rows = mem.retrieve("旧事实", k=3)
    assert len(rows) == 1
    assert rows[0].stale is True
    assert "需刷新" in rows[0].content


def test_heuristic_rating():
    class M:
        def __init__(self, c):
            self.content = c
    msgs = [M("ok")] * 10
    s, _ = _heuristic_rating(msgs)
    assert s == 5


def test_prompt_with_verifications():
    from core.workflow_templates import WORKFLOW_TEMPLATES
    p = prompt_with_verifications(WORKFLOW_TEMPLATES[0])
    assert "【自动验证项】" in p
