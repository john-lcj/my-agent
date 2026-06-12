"""统一能力层 —— 系统的"安全收口"。

核心洞察:agent 想"做的任何事"(调工具、跑 skill、控制 GUI、委托子 agent)
都抽象成同一个 Capability,并通过同一条调用管线执行。这样无论以后加多少种能力,
治理层永远只有一个收口要审查,安全模型不会分裂。

约定:每个 Capability 必须自报 risk,治理层据此裁决。
"""
from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from core.types import CapabilityResult, Risk


@runtime_checkable
class Capability(Protocol):
    name: str
    risk: Risk
    description: str
    schema: dict          # 参数的 JSON Schema,供模型做 function calling

    async def invoke(self, args: dict, ctx: Any) -> CapabilityResult:
        ...


class CapabilityRegistry:
    """能力注册表:按名字解析能力,并向 LLM 暴露可用能力的描述。

    工具、skill、GUI、子 agent 委托都注册到这里,实现"统一发现 + 统一调用"。
    """

    def __init__(self, capabilities: list[Capability] | None = None) -> None:
        self._caps: dict[str, Capability] = {}
        for c in capabilities or []:
            self.register(c)

    def register(self, cap: Capability) -> None:
        if cap.name in self._caps:
            raise ValueError(f"能力重名:{cap.name}")
        self._caps[cap.name] = cap

    def get(self, name: str) -> Capability | None:
        return self._caps.get(name)

    def capabilities(self) -> list[Capability]:
        """返回已注册能力实例列表(供 Worker 白名单过滤等)。"""
        return list(self._caps.values())

    def specs(self) -> list[dict]:
        """供 LLM 选择调用的能力清单(name/description/schema/risk)。"""
        return [
            {
                "name": c.name,
                "description": c.description,
                "schema": c.schema,
                "risk": int(c.risk),
            }
            for c in self._caps.values()
        ]

    async def invoke(self, name: str, args: dict, ctx: Any) -> CapabilityResult:
        cap = self.get(name)
        if cap is None:
            return CapabilityResult(ok=False, error=f"未知能力:{name}")
        try:
            return await cap.invoke(args, ctx)
        except Exception as e:  # 能力执行失败不应炸掉主循环
            return CapabilityResult(ok=False, error=f"{type(e).__name__}: {e}")
