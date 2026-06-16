"""主动记忆(经验沉淀 + 注入)回归。"""
from __future__ import annotations

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.types import Message, Role, Step
from memory.base import MemoryItem
from memory.experience_miner import ExperienceMiner, format_experience_block


class _FakeMem:
    def __init__(self, items=None):
        self.items = list(items or [])

    def store(self, item):
        self.items.append(item)

    def retrieve(self, query, k=5):
        return self.items[:k]


class _FakeLLM:
    def __init__(self, text):
        self._text = text

    async def next_step(self, msgs, caps):
        return Step(text=self._text)


def _msgs():
    return [Message(role=Role.USER, content="给项目做体检"),
            Message(role=Role.ASSISTANT, content="已用 wc -l 统计并写了报告")]


def test_mine_stores_experience():
    mem = _FakeMem()
    llm = _FakeLLM('["有效:先用命令拿真实行数再填表", "教训:网页只描述不落盘会判不合格"]')
    stored = asyncio.run(ExperienceMiner(llm, mem).mine(_msgs()))
    assert len(stored) == 2
    assert all(i.kind == "experience" for i in mem.items)
    assert mem.items[0].importance == 0.7


def test_mine_dedup():
    mem = _FakeMem([MemoryItem(kind="experience", content="先用命令拿真实行数再填表", importance=0.7)])
    llm = _FakeLLM('["先用命令拿真实行数再填表"]')  # 与已有重复
    stored = asyncio.run(ExperienceMiner(llm, mem).mine(_msgs()))
    assert stored == []


def test_mine_empty_dialogue():
    mem = _FakeMem()
    assert asyncio.run(ExperienceMiner(_FakeLLM("[]"), mem).mine([])) == []


def test_format_experience_block():
    mem = _FakeMem([
        MemoryItem(kind="experience", content="先拿真实数字再写", importance=0.7),
        MemoryItem(kind="preference", content="主人喜欢简洁", importance=0.6),
    ])
    block = format_experience_block(mem, "写报告", k=3)
    assert block.startswith("[过往经验")
    assert "先拿真实数字再写" in block
    assert "主人喜欢简洁" not in block  # 只注入经验,不混入偏好


def test_format_block_empty_when_none():
    assert format_experience_block(_FakeMem([]), "x") == ""
