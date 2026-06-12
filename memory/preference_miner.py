"""偏好自动沉淀 —— 会话结束后从对话中抽取"耐用事实",写入长期记忆。

专属感的来源:agent 记得你纠正过它什么、你习惯怎么被称呼、你常用什么路径。
persona.yaml 管"恒定人格"(手写、长期稳定),本模块管"动态认知"(自动学、可删除)。

设计约束:
  - 只抽"对未来会话仍然有用"的偏好/事实,不抽一次性任务细节。
  - 每次最多沉淀 3 条,宁缺毋滥(错误记忆会污染未来所有对话)。
  - 与已有记忆去重(精确/包含匹配 + 检索相似),重复不写。
  - LLM 可注入(测试用假 LLM,生产用轻量模型),失败静默跳过不影响主流程。
"""
from __future__ import annotations

import json
import re
from typing import Any

from core.types import Message, Role
from memory.base import MemoryItem

_MINER_PROMPT = """你是"偏好沉淀器"。阅读下面的对话片段,抽取关于"主人"的耐用偏好/事实。

只抽符合全部条件的内容:
1. 对未来的会话仍然有用(称呼习惯、表达偏好、技术栈偏好、常用路径/工具、被主人纠正过的行为);
2. 是稳定特征,不是本次任务的一次性细节(如"帮我写个网页"不算,"网页永远要暗色主题"算);
3. 你有较高把握(对话中有明确依据,不要脑补)。

没有可抽取的就输出空数组。最多 3 条,每条不超过 50 字,以第三人称陈述(如"主人偏好简洁的中文回复")。

对话片段:
{dialogue}

严格只输出 JSON 数组(不要其他内容):
["...", "..."]"""

_MAX_PER_SESSION = 3
_DIALOGUE_TURNS = 8  # 取最近 N 条 user/assistant 消息


class PreferenceMiner:
    """从对话抽取偏好写入长期记忆。llm 与 memory 均可注入,便于测试。"""

    def __init__(self, llm: Any, memory: Any) -> None:
        self._llm = llm
        self._memory = memory

    async def mine(self, messages: list[Message]) -> list[str]:
        """抽取并存储,返回本次新沉淀的偏好内容列表。失败返回 []。"""
        dialogue = self._format_dialogue(messages)
        if not dialogue.strip():
            return []
        try:
            candidates = await self._extract(dialogue)
        except Exception:
            return []

        stored: list[str] = []
        for content in candidates[:_MAX_PER_SESSION]:
            content = str(content).strip()
            if not content or self._is_duplicate(content):
                continue
            try:
                self._memory.store(MemoryItem(
                    kind="preference", content=content,
                    importance=0.6, source="agent",
                ))
                stored.append(content)
            except Exception:
                continue
        return stored

    async def _extract(self, dialogue: str) -> list[str]:
        prompt = _MINER_PROMPT.format(dialogue=dialogue)
        step = await self._llm.next_step(
            [Message(role=Role.USER, content=prompt)], [],
        )
        text = step.text or ""
        m = re.search(r"\[.*\]", text, re.DOTALL)
        if not m:
            return []
        data = json.loads(m.group())
        return [x for x in data if isinstance(x, str)]

    def _is_duplicate(self, content: str) -> bool:
        """精确/包含匹配已有偏好即视为重复。"""
        try:
            existing = self._memory.retrieve(content, k=5)
        except Exception:
            return False
        for item in existing:
            if item.kind != "preference":
                continue
            a, b = item.content.strip(), content.strip()
            if a == b or a in b or b in a:
                return True
        return False

    @staticmethod
    def _format_dialogue(messages: list[Message], turns: int = _DIALOGUE_TURNS) -> str:
        lines: list[str] = []
        for m in messages:
            if m.role == Role.USER and m.content:
                lines.append(f"主人: {m.content[:300]}")
            elif m.role == Role.ASSISTANT and m.content and not m.tool_calls:
                lines.append(f"助理: {m.content[:200]}")
        return "\n".join(lines[-turns:])


def format_preference_block(memory: Any, k: int = 8) -> str:
    """从长期记忆取 top-N 偏好,渲染成可注入系统提示词的块。无偏好返回空串。"""
    fn = getattr(memory, "list_by_kind", None)
    if not callable(fn):
        return ""
    try:
        rows = fn("preference", limit=k)
    except Exception:
        return ""
    if not rows:
        return ""
    lines = ["# 主人偏好(历次会话自动沉淀,遵循但别复述)"]
    lines += [f"- {r['content']}" for r in rows]
    return "\n".join(lines)
