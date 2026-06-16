"""自我改进闭环:任务模式追踪 + 固化建议。"""
from __future__ import annotations

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from memory.pattern_tracker import PatternTracker


def test_recurring_triggers_suggestion():
    with tempfile.TemporaryDirectory() as d:
        t = PatternTracker(os.path.join(d, "p.json"))
        for _ in range(3):
            t.record("帮我给项目做一次代码体检并生成报告")
        # 第 3 次后,类似任务应触发固化建议
        tip = t.suggestion_for("给项目做个代码体检报告")
        assert tip and "skill_author" in tip


def test_below_threshold_no_suggestion():
    with tempfile.TemporaryDirectory() as d:
        t = PatternTracker(os.path.join(d, "p.json"))
        t.record("帮我给项目做一次代码体检并生成报告")
        t.record("帮我给项目做一次代码体检并生成报告")  # 仅 2 次,未达阈值
        assert t.suggestion_for("给项目做个代码体检报告") == ""


def test_distinct_tasks_not_clustered():
    with tempfile.TemporaryDirectory() as d:
        t = PatternTracker(os.path.join(d, "p.json"))
        for _ in range(3):
            t.record("帮我给项目做代码体检报告")
        # 完全不同的任务不该命中
        assert t.suggestion_for("帮我订一张去上海的高铁票") == ""


def test_mark_crystallized_silences():
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "p.json")
        t = PatternTracker(path)
        for _ in range(3):
            t.record("帮我给项目做代码体检报告")
        assert t.suggestion_for("项目代码体检报告") != ""
        t.mark_crystallized("帮我给项目做代码体检报告")
        # 固化后不再建议;新实例从磁盘读也一致
        assert PatternTracker(path).suggestion_for("项目代码体检报告") == ""


def test_short_task_ignored():
    with tempfile.TemporaryDirectory() as d:
        t = PatternTracker(os.path.join(d, "p.json"))
        for _ in range(5):
            t.record("你好")
        assert t.suggestion_for("你好") == ""
