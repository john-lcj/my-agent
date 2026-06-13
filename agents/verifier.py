"""验收官(verifier)—— 给 DAG 编排加一道"自检"。

每个子任务产出后,对照它的 acceptance(验收标准)判断是否达标;不达标则由执行器
触发一次有界返修。这是"叙述代替执行 / 偷工减料"这类问题的结构性解药:不是靠 prompt
祈祷模型做对,而是做完再查一遍,不对就打回重做一次。

返回 (ok: bool, reason: str)。解析失败时 fail-open(判通过),避免验收官自身抖动误杀产出。
"""
from __future__ import annotations

import json
import re

_PROMPT = """你是严格但务实的验收官。判断"产出"是否满足"验收标准"。

【子任务】
{sub_task}

【验收标准】
{acceptance}

【产出】
{output}

只输出 JSON(不要其他内容):
{{"ok": true或false, "reason": "30字内;不达标就指出差在哪、怎么补"}}"""


class LLMVerifier:
    def __init__(self, llm) -> None:
        self._llm = llm

    async def __call__(self, node, output: str) -> tuple[bool, str]:
        from core.types import Message, Role
        prompt = _PROMPT.format(
            sub_task=node.sub_task,
            acceptance=node.acceptance,
            output=(output or "")[:3000],
        )
        try:
            step = await self._llm.next_step([Message(role=Role.USER, content=prompt)], [])
        except Exception:
            return True, ""        # 验收官调用失败 → 不阻断
        m = re.search(r"\{.*\}", step.text or "", re.DOTALL)
        if not m:
            return True, ""        # 解析不出 → fail-open
        try:
            data = json.loads(m.group())
        except json.JSONDecodeError:
            return True, ""
        return bool(data.get("ok", True)), str(data.get("reason", ""))[:80]
