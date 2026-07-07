from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.intent_router import classify_intent
from core.task_lifecycle import (
    PHASE_CHECK,
    PHASE_PLAN,
    PHASE_REPAIR,
    create_task_frame,
    final_gate,
    lifecycle_prompt_block,
    role_report_prompt,
    unfinished_steps,
    update_plan,
)


def test_create_task_frame_sets_role_criteria_and_phase():
    intent = classify_intent("继续完成 Windows 更新修复并跑测试")
    task = create_task_frame("继续完成 Windows 更新修复并跑测试", intent)
    assert task.role == "executor"
    assert task.phase == PHASE_PLAN
    assert any("验证" in c for c in task.acceptance_criteria)
    block = lifecycle_prompt_block(task)
    assert "目标理解 -> 计划 -> 执行 -> 自检 -> 必要时返修 -> 汇报" in block


def test_update_plan_tracks_checks_and_unfinished_steps():
    task = create_task_frame("修复并测试", classify_intent("修复并测试"))
    update_plan(task, [
        {"text": "改代码", "status": "done", "check": "相关测试通过"},
        {"text": "跑全量测试", "status": "doing", "check": "pytest 通过"},
    ])
    assert task.plan_steps[0]["check"] == "相关测试通过"
    assert unfinished_steps(task) == ["跑全量测试"]


def test_final_gate_blocks_unfinished_execution_plan_once():
    task = create_task_frame("继续完成修复并跑测试", classify_intent("继续完成修复并跑测试"))
    update_plan(task, [
        {"text": "改代码", "status": "done"},
        {"text": "跑测试", "status": "todo"},
    ])
    gate = final_gate(task, "已完成")
    assert "待办清单仍有未完成步骤" in gate
    assert task.phase == PHASE_REPAIR
    assert task.repair_count == 1


def test_final_gate_allows_completed_plan_and_sets_report_phase():
    task = create_task_frame("继续完成修复并跑测试", classify_intent("继续完成修复并跑测试"))
    update_plan(task, [
        {"text": "改代码", "status": "done"},
        {"text": "跑测试", "status": "done"},
    ])
    assert final_gate(task, "已完成") == ""
    assert task.phase == "report"


def test_role_report_prompt_uses_role_contract():
    task = create_task_frame("这个 token 怎么设置才安全", classify_intent("这个 token 怎么设置才安全"))
    prompt = role_report_prompt(task)
    assert "security" in prompt
    assert "没有回显 token" in prompt
    assert "对照完成标准汇报" in prompt


def test_agent_repairs_when_final_answer_has_unfinished_plan():
    import asyncio

    from capabilities.tools.plan import PlanUpdate
    from core.bus import EventBus
    from core.context import Context
    from core.loop import Agent
    from core.types import CapabilityCall, Decision, EventType, GovReview, Step

    class FakeLLM:
        name = "fake"

        def __init__(self):
            self.i = 0

        async def next_step(self, messages, specs, emit_token=None):
            self.i += 1
            if self.i == 1:
                return Step(call=CapabilityCall(
                    name="plan.update",
                    args={"steps": [
                        {"text": "改代码", "status": "done", "check": "相关测试通过"},
                        {"text": "跑测试", "status": "todo", "check": "pytest 通过"},
                    ]},
                    intent="记录执行计划",
                ))
            if self.i == 2:
                return Step(text="已完成。")
            return Step(text="部分完成:代码已改,但测试还没跑,需要继续验证。")

    class FakeRegistry:
        def __init__(self):
            self.plan = PlanUpdate()

        def specs_for(self, text):
            return [self.plan]

        def get(self, name):
            return self.plan if name == "plan.update" else None

        async def invoke(self, name, args, ctx):
            return await self.plan.invoke(args, ctx)

    class AllowPolicy:
        def review_detailed(self, call, actor, ctx):
            return GovReview(Decision.ALLOW, reason="ok", rule="test")

    events = []
    bus = EventBus()
    bus.subscribe(events.append)
    ctx = Context()
    ctx.coworker = True
    agent = Agent(FakeLLM(), FakeRegistry(), AllowPolicy(), bus)

    result = asyncio.run(agent.run("继续完成修复并跑测试", ctx, lambda *a, **k: True))
    assert "部分完成" in result
    assert ctx.task_frame.repair_count >= 2
    assert any("生命周期自检" in m.content for m in ctx.messages)
    assistant_events = [e for e in events if e.type == EventType.ASSISTANT_MESSAGE]
    assert assistant_events[-1].payload["text"] == result
