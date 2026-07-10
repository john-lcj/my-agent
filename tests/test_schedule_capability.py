"""agent 自建定时任务能力 + 其权限裁决。"""
from __future__ import annotations

import asyncio
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.types import CapabilityCall, Decision, Identity


def _tool_with_temp_store():
    import capabilities.tools.schedule as sched
    from scheduler.store import TaskStore
    d = tempfile.mkdtemp()
    sched._STORE = TaskStore(db_path=os.path.join(d, "tasks.db"))
    return sched


def test_tool_create_list_delete_roundtrip():
    sched = _tool_with_temp_store()
    create, listt, delete = sched.ScheduleCreate(), sched.ScheduleList(), sched.ScheduleDelete()
    r = asyncio.run(create.invoke(
        {"name": "晨报", "prompt": "汇总昨天邮件", "schedule_type": "daily", "at_hhmm": "09:00"}, None))
    assert r.ok and "晨报" in r.output
    lst = asyncio.run(listt.invoke({}, None))
    assert "晨报" in lst.output
    # 取出 id 删除
    tid = sched._STORE.list()[0].id
    d = asyncio.run(delete.invoke({"id": tid}, None))
    assert d.ok
    assert sched._STORE.list() == []


def test_tool_rejects_bad_input():
    sched = _tool_with_temp_store()
    create = sched.ScheduleCreate()
    r = asyncio.run(create.invoke({"name": "", "prompt": "x", "schedule_type": "daily"}, None))
    assert not r.ok                                  # 缺 name
    r2 = asyncio.run(create.invoke({"name": "n", "prompt": "p", "schedule_type": "weekly"}, None))
    assert not r2.ok                                 # 非法 schedule_type


def _policy():
    from capabilities.base import CapabilityRegistry
    from capabilities.tools.schedule import ScheduleCreate, ScheduleList, ScheduleDelete
    from governance.engine import DeclarativePolicy
    reg = CapabilityRegistry([ScheduleCreate(), ScheduleList(), ScheduleDelete()])
    return DeclarativePolicy(reg, config_path="governance/policy.yaml")


class _Ctx:
    def __init__(self, coworker): self.coworker = coworker


def test_schedule_create_confirm_by_mode():
    os.environ.pop("AGENT_WORKSPACE_ROOT", None)
    pol = _policy()
    c = CapabilityCall(name="schedule.create", args={"name": "n", "prompt": "p", "schedule_type": "daily"})
    assert pol.review(c, Identity(), _Ctx(False)) == Decision.ASK
    assert pol.review(c, Identity(), _Ctx(True)) == Decision.ASK


def test_schedule_list_is_read_auto_allow():
    os.environ.pop("AGENT_WORKSPACE_ROOT", None)
    pol = _policy()
    c = CapabilityCall(name="schedule.list", args={})
    assert pol.review(c, Identity(), _Ctx(False)) == Decision.ALLOW  # 只读,自动放行


def test_whitelist_executor_yes_researcher_no():
    os.environ.pop("AGENT_WORKSPACE_ROOT", None)
    pol = _policy()
    c = CapabilityCall(name="schedule.create", args={"name": "n", "prompt": "p", "schedule_type": "daily"})
    # executor 角色:白名单含 schedule. -> 不被白名单拦(进入确认环节,Chat=ASK)
    assert pol.review(c, Identity(roles=("executor",)), _Ctx(False)) == Decision.ASK
    # researcher 角色(只读档,无 schedule.)-> 白名单直接 BLOCK
    assert pol.review(c, Identity(roles=("researcher",)), _Ctx(False)) == Decision.BLOCK
