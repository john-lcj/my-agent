from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.context import Context
from core.intent_router import classify_intent, intent_prompt_block
from core.types import Step


def test_rule_roles_cover_common_intents():
    cases = [
        ("帮我看看这个有没有 bug", "reviewer"),
        ("继续完成上次重构并跑测试", "executor"),
        ("这个 token 怎么设置才安全", "security"),
        ("你觉得这个产品方向怎么样", "pm"),
        ("查一下最新 Windows 安装脚本最佳实践", "researcher"),
        ("解释一下这个函数怎么实现", "advisor"),
    ]
    for text, role in cases:
        assert classify_intent(text).role == role


def test_coworker_ambiguous_text_defaults_to_executor():
    ctx = Context()
    ctx.coworker = True
    frame = classify_intent("帮我处理一下", ctx)
    assert frame.role == "executor"
    assert frame.needs_plan is True


def test_prompt_block_is_internal_and_actionable():
    frame = classify_intent("帮我看看这个有没有 bug")
    block = intent_prompt_block(frame)
    assert "内部使用" in block
    assert "不要向用户复述" in block
    assert "reviewer" in block
    assert "默认可改文件:否" in block


def test_agent_injects_intent_frame_without_user_visible_message():
    from core.bus import EventBus
    from core.loop import Agent
    from core.types import EventType, Role

    class FakeLLM:
        name = "fake"

        def __init__(self):
            self.seen = []

        async def next_step(self, messages, specs, emit_token=None):
            self.seen = messages
            return Step(text="我先按审阅方式看。")

    class FakeRegistry:
        def specs_for(self, text):
            return []

    events = []
    bus = EventBus()
    bus.subscribe(events.append)
    llm = FakeLLM()
    ctx = Context()
    agent = Agent(llm, FakeRegistry(), policy=None, bus=bus)

    import asyncio

    out = asyncio.run(agent.run("帮我看看这个有没有 bug", ctx, lambda *a, **k: True))
    assert out == "我先按审阅方式看。"
    assert ctx.intent_frame.role == "reviewer"
    system_blocks = [m.content for m in llm.seen if m.role == Role.SYSTEM]
    assert any("本轮语境判断" in b and "reviewer" in b for b in system_blocks)
    assistant_events = [e for e in events if e.type == EventType.ASSISTANT_MESSAGE]
    assert len(assistant_events) == 1
    assert "本轮语境判断" not in assistant_events[0].payload["text"]
