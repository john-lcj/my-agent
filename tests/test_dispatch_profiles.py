"""阶段0 后:动态子代理(权限档)的派发回归 —— 用真实 roster 规格做关键词路由断言。"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agents.dispatcher import KeywordDispatcher
from agents.spec import load_specs_from_roster

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class _W:
    """轻量 worker:带 name + spec(供关键词路由读 trigger_keywords)。"""
    def __init__(self, spec):
        self.name = spec.name
        self.role = spec.role
        self.description = spec.description
        self.spec = spec


def _workers():
    specs = {s.name: s for s in load_specs_from_roster(os.path.join(ROOT, "agents", "roster"))}
    return [_W(specs[n]) for n in ("researcher", "executor", "adler_counselor_agent")]


def test_roster_is_two_profiles_plus_counselor():
    names = {w.name for w in _workers()}
    assert names == {"researcher", "executor", "adler_counselor_agent"}
    # 旧域专家已不在
    specs = {s.name for s in load_specs_from_roster(os.path.join(ROOT, "agents", "roster"))}
    assert not ({"code_agent", "web_agent", "data_analyst_agent", "ops_notify_agent"} & specs)


def test_readonly_task_routes_to_researcher():
    plan = KeywordDispatcher().route("帮我查一下最新的资料并分析", _workers())
    names = [a.agent_name for a in plan.assignments]
    assert "researcher" in names


def test_write_task_routes_to_executor():
    plan = KeywordDispatcher().route("帮我写一个网页并生成文件", _workers())
    names = [a.agent_name for a in plan.assignments]
    assert "executor" in names


def test_chitchat_routes_to_nobody():
    plan = KeywordDispatcher().route("你好呀", _workers())
    assert plan.assignments == []


def test_profiles_have_correct_capabilities():
    specs = {s.name: s for s in load_specs_from_roster(os.path.join(ROOT, "agents", "roster"))}
    assert "fs.write" not in specs["researcher"].capabilities  # 只读档不能写
    assert "fs.write" in specs["executor"].capabilities        # 可写档能写
