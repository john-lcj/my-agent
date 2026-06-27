"""Mission 领域 + 持久化 —— 生命周期、非法转移拦截、子任务推进、注意力治理。"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.mission import (MissionStatus, AttentionLevel, can_transition,
                          is_terminal, attention_action)
from memory.mission_store import MissionStore


# ── 领域:状态机 ──────────────────────────────────────────────
def test_legal_transitions():
    assert can_transition("created", "planning")
    assert can_transition("planning", "executing")
    assert can_transition("executing", "blocked")
    assert can_transition("blocked", "executing")        # 恢复
    assert can_transition("executing", "executing")      # 推进进度(自转)
    assert can_transition("executing", "completed")


def test_illegal_transitions_rejected():
    assert not can_transition("created", "completed")     # 不能跳过执行
    assert not can_transition("completed", "executing")   # 终态不可复活
    assert not can_transition("cancelled", "executing")


def test_terminal():
    assert is_terminal("completed") and is_terminal("failed") and is_terminal("cancelled")
    assert not is_terminal("executing") and not is_terminal("blocked")


# ── 领域:注意力治理 ──────────────────────────────────────────
def test_attention_action():
    assert attention_action(AttentionLevel.AUTO) == "auto"
    assert attention_action(AttentionLevel.NOTIFY) == "notify"
    assert attention_action(AttentionLevel.EMAIL) == "block"
    assert attention_action(AttentionLevel.CONFIRM) == "block"
    assert attention_action(AttentionLevel.STOP) == "stop"


# ── 持久化:CRUD + 状态机 ────────────────────────────────────
def test_create_and_get(tmp_path):
    s = MissionStore(db_path=str(tmp_path / "m.db"))
    m = s.create("写德国市场分析", attention_level=AttentionLevel.EMAIL)
    assert m["status"] == "created" and m["goal"] == "写德国市场分析"
    assert m["attention_level"] == 2
    assert s.get(m["id"])["id"] == m["id"]


def test_store_rejects_illegal_transition(tmp_path):
    s = MissionStore(db_path=str(tmp_path / "m.db"))
    m = s.create("x")
    import pytest
    with pytest.raises(ValueError):
        s.set_status(m["id"], "completed")   # created→completed 非法
    # 合法链路 OK
    s.set_status(m["id"], "planning")
    s.set_status(m["id"], "executing")
    assert s.get(m["id"])["status"] == "executing"


def test_task_progression(tmp_path):
    s = MissionStore(db_path=str(tmp_path / "m.db"))
    m = s.create("多步任务")
    s.set_tasks(m["id"], ["调研", "写稿", "排版"])
    nt = s.next_task(m["id"])
    assert nt["text"] == "调研" and nt["status"] == "pending"
    s.update_task(m["id"], nt["id"], status="done", result="调研完成")
    assert s.next_task(m["id"])["text"] == "写稿"      # 推进到下一个


def test_block_and_resume(tmp_path):
    s = MissionStore(db_path=str(tmp_path / "m.db"))
    m = s.create("需营业执照的任务")
    s.set_status(m["id"], "planning")
    s.set_status(m["id"], "executing")
    s.set_status(m["id"], "blocked", reason="缺德国营业执照,请上传")
    blocked = s.get(m["id"])
    assert blocked["status"] == "blocked" and "营业执照" in blocked["blocked_reason"]
    # 用户上传后恢复
    s.set_status(m["id"], "executing")
    assert s.get(m["id"])["status"] == "executing"


def test_artifacts_notifications_and_list(tmp_path):
    s = MissionStore(db_path=str(tmp_path / "m.db"))
    m = s.create("交付任务")
    s.add_artifact(m["id"], "产物/德国市场分析.docx")
    s.add_artifact(m["id"], "产物/德国市场分析.docx")   # 去重
    s.add_notification(m["id"], AttentionLevel.EMAIL, "需要你确认版本 A/B")
    got = s.get(m["id"])
    assert got["artifacts"] == ["产物/德国市场分析.docx"]
    assert got["notifications"][0]["message"].startswith("需要你确认")
    # 持久化:重开 store 仍在(跨重启)
    s.close()
    s2 = MissionStore(db_path=str(tmp_path / "m.db"))
    assert s2.get(m["id"])["artifacts"] == ["产物/德国市场分析.docx"]
    assert len(s2.list()) == 1
