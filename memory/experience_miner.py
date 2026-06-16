"""经验沉淀 —— 会话结束后从"做过的事"里提炼"什么做法有效/无效",写入长期记忆。

这让记忆从"被动检索事实"升级为"主动吸取教训":下次遇到类似任务,开场就把
相关经验注入,让 agent 复用有效做法、绕开踩过的坑,而不是每次从零试错。

与 PreferenceMiner 的区别:
  - preference 抽"关于主人的耐用特征";experience 抽"关于怎么把活干好的方法论"。
  - 存为 kind="experience",在 core/loop 里单独成块注入(与偏好/事实区分开)。
失败静默,绝不影响主流程。
"""
from __future__ import annotations

import json
import re
from typing import Any

from core.types import Message, Role
from memory.base import MemoryItem

_MINER_PROMPT = """你是"经验沉淀器"。阅读下面这段协作过程,提炼"做法层面"的经验,供以后类似任务复用。

只抽符合全部条件的:
1. 是"怎么把事做对/做砸"的方法论,对未来类似任务有指导价值;
2. 有本次过程的明确依据(某做法成功了、或某错误导致返工),不要脑补;
3. 可操作,不是空话(如"先跑命令拿到真实数字再写报告"算;"要认真"不算)。

每条注明是「有效」还是「教训」。没有可抽取的就输出空数组。最多 3 条,每条不超过 50 字。

协作过程:
{dialogue}

严格只输出 JSON 数组(不要其他内容):
["有效:先用 wc -l 拿真实行数再填表，避免估算被判错", "教训:网页只描述不写文件会被判不合格，必须真落盘"]"""

_MAX_PER_SESSION = 3
_DIALOGUE_TURNS = 16


class ExperienceMiner:
    """从协作过程抽取"做法经验"写入长期记忆。llm 与 memory 均可注入,便于测试。"""

    def __init__(self, llm: Any, memory: Any) -> None:
        self._llm = llm
        self._memory = memory

    async def mine(self, messages: list[Message]) -> list[str]:
        dialogue = _format_dialogue(messages)
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
                    kind="experience", content=content,
                    importance=0.7, source="agent",
                ))
                stored.append(content)
            except Exception:
                continue
        return stored

    async def _extract(self, dialogue: str) -> list[str]:
        step = await self._llm.next_step(
            [Message(role=Role.USER, content=_MINER_PROMPT.format(dialogue=dialogue))], [])
        text = step.text or ""
        m = re.search(r"\[.*\]", text, re.DOTALL)
        if not m:
            return []
        data = json.loads(m.group())
        return [x for x in data if isinstance(x, str)]

    def _is_duplicate(self, content: str) -> bool:
        try:
            existing = self._memory.retrieve(content, k=5)
        except Exception:
            return False
        for item in existing:
            if getattr(item, "kind", "") != "experience":
                continue
            a, b = item.content.strip(), content.strip()
            if a == b or a in b or b in a:
                return True
        return False


def _format_dialogue(messages: list, turns: int = _DIALOGUE_TURNS) -> str:
    lines: list[str] = []
    for m in messages:
        if getattr(m, "role", None) == Role.USER and m.content:
            lines.append(f"主人: {m.content[:300]}")
        elif getattr(m, "role", None) == Role.ASSISTANT and m.content and not getattr(m, "tool_calls", None):
            lines.append(f"助理: {m.content[:200]}")
    return "\n".join(lines[-turns:])


def format_experience_block(memory: Any, query: str, k: int = 3) -> str:
    """检索与当前任务相关的经验,拼成开场注入块;无则空串。"""
    try:
        items = memory.retrieve(query, k=8)
    except Exception:
        return ""
    exps = [it.content for it in items if getattr(it, "kind", "") == "experience"][:k]
    if not exps:
        return ""
    return "[过往经验 · 供你借鉴,复用有效做法、避开踩过的坑]\n" + "\n".join(f"- {e}" for e in exps)
