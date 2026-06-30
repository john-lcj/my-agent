from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.context import Context
from core.intent_router import ROLE_BEHAVIORS, classify_intent, intent_prompt_block
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
    assert "角色行为契约" in block
    assert "发现优先" in block
    assert "默认可改文件:否" in block


def test_all_roles_have_detailed_behavior_contracts():
    required = {
        "advisor": ("顾问", "默认不改文件"),
        "reviewer": ("审阅者", "按严重程度"),
        "executor": ("执行者", "完成后必须验证"),
        "researcher": ("研究员", "权威"),
        "pm": ("产品经理", "优先级"),
        "security": ("安全官", "不要回显秘密"),
    }
    for role, (label, phrase) in required.items():
        behavior = ROLE_BEHAVIORS[role]
        assert behavior.label == label
        block = intent_prompt_block(
            classify_intent({
                "advisor": "解释一下这个函数",
                "reviewer": "帮我看看有没有 bug",
                "executor": "继续完成修复并跑测试",
                "researcher": "查一下最新资料",
                "pm": "你觉得产品方向怎么走",
                "security": "这个 token 怎么设置安全",
            }[role])
        )
        assert label in block
        assert phrase in block
        assert "工具策略" in block
        assert "确认边界" in block
        assert "验证标准" in block
        assert "禁止事项" in block


def test_pm_takes_precedence_for_product_advice():
    frame = classify_intent("你有什么建议吗？这个产品方向怎么实现更好？")
    assert frame.role == "pm"


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
