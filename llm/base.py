"""LLM 接口 —— 模型是可替换的零件。

agent 核心只认这个接口,不认任何具体厂商。想换 Claude/OpenAI/DeepSeek/本地,
只需新增一个实现并在组合根(main.py)里换一行。这就是依赖倒置。

next_step 的契约:
- 输入:对话消息 + 当前可用能力的描述(供 function calling)。
- 输出:一个 Step —— 要么是给用户的最终回复(text),要么是一次能力调用(call)。
"""
from __future__ import annotations

from typing import Awaitable, Callable, Optional, Protocol, runtime_checkable

from core.types import Message, Step

# 终局纯文本回复时按 chunk 回调;tool_call 路径不流式。
EmitTokenFn = Callable[[str], Awaitable[None]]


@runtime_checkable
class LLM(Protocol):
    name: str

    async def next_step(
        self,
        messages: list[Message],
        capabilities: list[dict],
        emit_token: Optional[EmitTokenFn] = None,
    ) -> Step:
        """根据对话历史与可用能力,决定下一步。

        capabilities 中每一项形如:
            {"name": str, "description": str, "schema": dict, "risk": int}
        provider 负责把它翻译成自家的 function/tool 调用格式,
        并把模型返回的 tool_call 解析回统一的 CapabilityCall。
        """
        ...
