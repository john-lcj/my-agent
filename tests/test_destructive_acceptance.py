"""破坏性自验收 —— 基线篡改门禁、kill -9 断点续跑、写失败诚实汇报。"""
from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.mission import MissionStatus
from core.mission_runner import run_mission
from core.verification import Verification, run_verification
from memory.checkpoint_store import CheckpointStore
from memory.mission_store import MissionStore


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = os.path.join(ROOT, ".venv", "bin", "python")


def _run_evals(extra: list[str], evals_log: str) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["AGENT_EVALS_LOG_DIR"] = evals_log
    return subprocess.run(
        [PY, "scripts/run_evals.py", "--mock", "--limit", "2", *extra],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
    )


def test_baseline_tamper_triggers_exit_one(tmp_path):
    """篡改 baseline 抬高 10% 后,回归门禁应 exit 1。"""
    log_dir = tmp_path / "evals"
    log_dir.mkdir()
    baseline = {
        "avg_score": 0.99,
        "pass_rate": 0.99,
        "by_taxonomy": {},
        "cases": [],
    }
    (log_dir / "baseline.json").write_text(json.dumps(baseline), encoding="utf-8")

    r = _run_evals([], str(log_dir))
    assert r.returncode == 1, r.stdout + r.stderr
    assert "回归门禁未通过" in (r.stdout + r.stderr)


def test_baseline_tamper_no_gate_exits_zero(tmp_path):
    """同一篡改基线加 --no-gate 应 exit 0。"""
    log_dir = tmp_path / "evals"
    log_dir.mkdir()
    baseline = {"avg_score": 0.99, "pass_rate": 0.99, "by_taxonomy": {}, "cases": []}
    (log_dir / "baseline.json").write_text(json.dumps(baseline), encoding="utf-8")

    r = _run_evals(["--no-gate"], str(log_dir))
    assert r.returncode == 0, r.stdout + r.stderr


def test_checkpoint_survives_simulated_kill(tmp_path):
    """模拟 kill -9:落盘后新进程实例仍能读到未完成待办。"""
    base = str(tmp_path / "ck")
    store = CheckpointStore(base_dir=base)
    store.save("sess-kill", [
        {"text": "拉数据", "status": "done"},
        {"text": "写报告", "status": "doing"},
        {"text": "发邮件", "status": "pending"},
    ])
    assert not list((tmp_path / "ck").glob("*.tmp"))

    store2 = CheckpointStore(base_dir=base)
    assert store2.unfinished("sess-kill") == ["写报告", "发邮件"]


def test_checkpoint_resume_after_partial_then_crash(tmp_path):
    """中断→续跑→再中断:进度递增不丢。"""
    base = str(tmp_path / "ck")
    CheckpointStore(base_dir=base).save("s", [
        {"text": "a", "status": "done"},
        {"text": "b", "status": "pending"},
    ])
    store = CheckpointStore(base_dir=base)
    assert store.unfinished("s") == ["b"]
    store.save("s", [
        {"text": "a", "status": "done"},
        {"text": "b", "status": "done"},
        {"text": "c", "status": "pending"},
    ])
    assert CheckpointStore(base_dir=base).unfinished("s") == ["c"]


def test_mission_resume_skips_completed_after_kill(tmp_path):
    """executing mission 杀进程重启后,不重复已完成子任务。"""
    store = MissionStore(db_path=str(tmp_path / "m.db"))
    m = store.create("续跑目标")
    store.set_tasks(m["id"], ["第一步", "第二步", "第三步"])
    store.set_status(m["id"], MissionStatus.PLANNING.value)
    store.set_status(m["id"], MissionStatus.EXECUTING.value)
    t1 = store.get(m["id"])["tasks"][0]
    store.update_task(m["id"], t1["id"], status="done", result="已完成输出")

    calls: list[str] = []

    async def execute(prompt: str) -> str:
        calls.append(prompt[:12])
        return "ok"

    final = asyncio.run(run_mission(store, m["id"], execute))
    assert final["status"] == "completed"
    assert len(calls) == 2
    assert store.get(m["id"])["tasks"][0]["status"] == "done"
    assert store.get(m["id"])["tasks"][0]["result"] == "已完成输出"


def test_blocked_mission_not_in_executing_resume_list(tmp_path):
    """blocked mission 不应被 lifespan executing 恢复逻辑选中。"""
    store = MissionStore(db_path=str(tmp_path / "m.db"))
    m = store.create("卡住的任务")
    store.set_tasks(m["id"], ["待补资料"])

    async def execute(prompt: str) -> str:
        return "NEED_INPUT: 缺文件"

    final = asyncio.run(run_mission(store, m["id"], execute))
    assert final["status"] == "blocked"
    assert store.list(status="executing") == []


def test_verification_fails_on_missing_file(tmp_path, monkeypatch):
    """写失败/文件不存在时 verification 如实 fail,不假装 pass。"""
    monkeypatch.setenv("AGENT_WORKSPACE_ROOT", str(tmp_path))
    v = Verification(kind="read_file", target="产物/不存在.md")
    run_verification(v)
    assert v.status == "fail"
    assert "不存在" in v.evidence
