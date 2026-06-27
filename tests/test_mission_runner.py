"""Mission 执行引擎 —— 用假 execute 离线验证:规划→顺序执行→完成/失败。"""
from __future__ import annotations

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.mission_runner import run_mission, _parse_tasks
from memory.mission_store import MissionStore


def test_parse_tasks_strips_numbering():
    txt = "1. 调研市场\n- 写报告\n• 排版\n\n第三步：复核"
    assert _parse_tasks(txt) == ["调研市场", "写报告", "排版", "复核"]


def test_full_run_completes(tmp_path):
    s = MissionStore(db_path=str(tmp_path / "m.db"))
    m = s.create("写德国市场分析")
    calls = []

    async def fake_execute(prompt: str) -> str:
        calls.append(prompt)
        if "拆成" in prompt:                    # 规划阶段
            return "调研法规\n收集数据\n撰写报告"
        return f"完成:{prompt[:10]}"            # 执行阶段

    final = asyncio.run(run_mission(s, m["id"], fake_execute))
    assert final["status"] == "completed"
    assert [t["text"] for t in final["tasks"]] == ["调研法规", "收集数据", "撰写报告"]
    assert all(t["status"] == "done" for t in final["tasks"])
    # 1 次规划 + 3 次执行
    assert len(calls) == 4


def test_run_uses_preset_tasks_without_planning(tmp_path):
    s = MissionStore(db_path=str(tmp_path / "m.db"))
    m = s.create("目标")
    s.set_tasks(m["id"], ["A", "B"])           # 预置子任务 → 不再规划

    async def fake_execute(prompt: str) -> str:
        assert "拆成" not in prompt            # 不应触发规划
        return "ok"

    final = asyncio.run(run_mission(s, m["id"], fake_execute))
    assert final["status"] == "completed"
    assert [t["status"] for t in final["tasks"]] == ["done", "done"]


def test_task_failure_marks_mission_failed(tmp_path):
    s = MissionStore(db_path=str(tmp_path / "m.db"))
    m = s.create("会失败的任务")
    s.set_tasks(m["id"], ["好任务", "坏任务", "不该执行"])

    async def fake_execute(prompt: str) -> str:
        if prompt == "坏任务":
            raise RuntimeError("工具炸了")
        return "ok"

    final = asyncio.run(run_mission(s, m["id"], fake_execute))
    assert final["status"] == "failed"
    sts = {t["text"]: t["status"] for t in final["tasks"]}
    assert sts["好任务"] == "done" and sts["坏任务"] == "failed"
    assert sts["不该执行"] == "pending"        # 失败后停止,后续不跑


def test_emit_events(tmp_path):
    s = MissionStore(db_path=str(tmp_path / "m.db"))
    m = s.create("g")
    s.set_tasks(m["id"], ["x"])
    seen = []

    async def fake_execute(p): return "ok"
    asyncio.run(run_mission(s, m["id"], fake_execute,
                            emit=lambda k, p: seen.append(k)))
    assert "mission.started" in seen and "mission.completed" in seen and "task.done" in seen
