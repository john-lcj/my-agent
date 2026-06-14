"""伙伴记忆(协作日志)回归 —— 确定性断言,无需真实模型。

覆盖三件事:
1. Journal 存取:append / recent / render_briefing,人类可读 markdown。
2. JournalConsolidator:用 fake LLM 把对话总结成一条日志(含空对话/坏 JSON 兜底)。
3. 开场注入:Agent._inject_journal 只在会话首轮注入一次"上次到哪了"。
"""
from __future__ import annotations

import asyncio
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.loop import Agent
from core.types import Message, Role, Step
from memory.journal import Journal, JournalConsolidator


def test_journal_append_and_recent():
    with tempfile.TemporaryDirectory() as d:
        jp = os.path.join(d, "journal.md")
        j = Journal(jp)
        j.append("接通 DAG 编排", ["走依赖图"], ["压测"])
        j.append("修了 data-quick", ["计数附命令证据"], ["重跑确认"])
        recent = j.recent(1)
        assert len(recent) == 1
        assert "data-quick" in recent[0]
        assert "DAG" not in recent[0]
        assert len(j.recent(5)) == 2
        raw = open(jp, encoding="utf-8").read()
        assert raw.startswith("# 协作日志")
        assert "**做了**" in raw and "**决定**" in raw and "**下一步**" in raw


def test_journal_empty_summary_ignored():
    with tempfile.TemporaryDirectory() as d:
        j = Journal(os.path.join(d, "j.md"))
        j.append("   ")
        assert j.recent(3) == []
        assert j.render_briefing() == ""


def test_journal_briefing_header():
    with tempfile.TemporaryDirectory() as d:
        j = Journal(os.path.join(d, "j.md"))
        j.append("做了某事")
        b = j.render_briefing(2)
        assert b.startswith("[我们的协作进展")
        assert "做了某事" in b


class _FakeLLM:
    def __init__(self, text):
        self._text = text

    async def next_step(self, messages, caps):
        return Step(text=self._text)


def test_consolidator_writes_entry():
    with tempfile.TemporaryDirectory() as d:
        j = Journal(os.path.join(d, "j.md"))
        llm = _FakeLLM('前言{"summary":"讨论AGI与记忆","decisions":["先做伙伴记忆"],'
                       '"next_steps":["跑通开场简报"]}后语')
        msgs = [Message(role=Role.USER, content="做个长期伙伴"),
                Message(role=Role.ASSISTANT, content="好,先解决记忆")]
        assert asyncio.run(JournalConsolidator(llm, j).consolidate(msgs)) is True
        entry = j.recent(1)[0]
        assert "讨论AGI与记忆" in entry and "先做伙伴记忆" in entry


def test_consolidator_empty_dialogue_writes_nothing():
    with tempfile.TemporaryDirectory() as d:
        j = Journal(os.path.join(d, "j.md"))
        # 没有任何可用对话(空 / 只有助理消息)→ 不沉淀
        assert asyncio.run(JournalConsolidator(_FakeLLM("{}"), j).consolidate([])) is False
        only_assistant = [Message(role=Role.ASSISTANT, content="在的")]
        assert asyncio.run(JournalConsolidator(_FakeLLM("not json"), j).consolidate(only_assistant)) is False
        assert j.recent(3) == []


def test_consolidator_fallback_on_bad_llm():
    """模型返回非 JSON 时,仍用对话兜底写一条最简日志(记忆不丢)。"""
    with tempfile.TemporaryDirectory() as d:
        j = Journal(os.path.join(d, "j.md"))
        msgs = [Message(role=Role.USER, content="帮我做项目自体检\n第二行"),
                Message(role=Role.ASSISTANT, content="好的")]
        assert asyncio.run(JournalConsolidator(_FakeLLM("彻底不是json"), j).consolidate(msgs)) is True
        entry = j.recent(1)[0]
        assert "自动记录" in entry and "项目自体检" in entry
        assert "第二行" not in entry  # 只取首行


def test_inject_journal_first_turn_only():
    from core.context import Context

    with tempfile.TemporaryDirectory() as d:
        jp = os.path.join(d, "journal.md")
        Journal(jp).append("上次接通了编排", ["走依赖图"], ["压测"])

        # 用最小 Agent 外壳:只测 _inject_journal,绕开完整装配。
        agent = Agent.__new__(Agent)
        # _inject_journal 用默认路径 Journal(),改 cwd 让它命中临时文件。
        cwd = os.getcwd()
        os.chdir(d)
        os.makedirs("logs", exist_ok=True)
        os.replace(jp, os.path.join("logs", "journal.md"))
        try:
            ctx = Context()
            ctx.messages = []
            agent._inject_journal(ctx)
            sysmsgs = [m for m in ctx.messages
                       if m.role == Role.SYSTEM and m.content.startswith("[我们的协作进展")]
            assert len(sysmsgs) == 1
            assert "上次接通了编排" in sysmsgs[0].content
            # 再次调用不重复注入
            agent._inject_journal(ctx)
            assert len([m for m in ctx.messages
                        if m.content.startswith("[我们的协作进展")]) == 1
            # 一旦出现 USER 消息(非首轮),不再注入
            ctx2 = Context()
            ctx2.messages = [Message(role=Role.USER, content="你好")]
            agent._inject_journal(ctx2)
            assert not any(m.content.startswith("[我们的协作进展") for m in ctx2.messages)
        finally:
            os.chdir(cwd)
