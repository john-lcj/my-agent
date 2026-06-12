"""多 agent 基础接口 —— 先留接口空壳。

要点:
- AgentNode 是"一个可被组织的 agent",每个有自己的角色与能力子集(最小权限)。
- "调用另一个 agent"通过 capabilities/delegate.py 走统一能力管线,同样过治理。
- 不同协同模式(圆桌/辩论/分层)都是 Orchestration 的不同实现。
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class AgentNode(Protocol):
    name: str
    role: str                 # "规划者" / "批评者" / "执行者" ...
    # capabilities: 该 agent 被允许使用的能力名单(最小权限)

    async def step(self, conversation) -> object:
        """读取共享对话,产出自己这一轮的发言/动作。"""
        ...


@runtime_checkable
class Orchestration(Protocol):
    async def run(self, agents: list[AgentNode], task: str) -> object:
        ...
