"""LLMRouter —— 按角色/任务把请求路由到不同 provider。

多 agent 阶段很有用:规划者用强模型(Claude),批量执行用便宜模型(DeepSeek)。
它自身实现 LLM 接口,对上层而言就是"一个模型",可无缝替换。

路由规则(按优先级):先看角色,再看任务类型,都没命中则用默认。
"""
from __future__ import annotations

from typing import Optional

from core.types import Message, Step
from llm.base import LLM
from llm.streaming import EmitTokenFn


class LLMRouter:
    name = "router"

    def __init__(
        self,
        providers: dict[str, LLM],
        default: str,
        role_rules: Optional[dict[str, str]] = None,
        task_rules: Optional[dict[str, str]] = None,
    ) -> None:
        if default not in providers:
            raise ValueError(f"默认 provider {default!r} 不在 providers 中")
        self.providers = providers
        self.default = default
        self.role_rules = role_rules or {}      # 如 {"规划者": "claude", "执行者": "deepseek"}
        self.task_rules = task_rules or {}      # 如 {"summarize": "deepseek"}

    def pick(self, role: str = "", task_kind: str = "") -> LLM:
        name = self.role_rules.get(role) or self.task_rules.get(task_kind) or self.default
        return self.providers.get(name, self.providers[self.default])

    async def next_step(
        self,
        messages: list[Message],
        capabilities: list[dict],
        emit_token: Optional[EmitTokenFn] = None,
    ) -> Step:
        return await self.pick().next_step(messages, capabilities, emit_token=emit_token)

    async def summarize(self, text: str) -> str:
        # 摘要是典型的"便宜任务",按 task 规则路由(默认走默认 provider)。
        provider = self.pick(task_kind="summarize")
        fn = getattr(provider, "summarize", None)
        if fn is None:
            return ""
        return await fn(text)
