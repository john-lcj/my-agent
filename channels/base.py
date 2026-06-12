"""Channel 抽象 —— 把"消息从哪来/回哪去"与 agent 核心彻底解耦。

CLI、Web、Slack、Telegram、企业微信都是 Channel 的实现。三个核心职责:
- receive:收一条用户消息
- emit:把 agent 产生的事件(文本/工具动作/完成)呈现出去(可流式)
- confirm:软边界确认 —— 当治理判定 ASK 时,向用户征求同意
- identity:回答"这条消息是谁发的"(治理按主体鉴权的前提)
"""
from __future__ import annotations

from typing import Optional, Protocol, runtime_checkable

from core.types import CapabilityCall, Decision, Event, Identity


@runtime_checkable
class Channel(Protocol):
    name: str

    async def receive(self) -> Optional[str]:
        """取下一条用户输入;返回 None 表示会话结束。"""
        ...

    def emit(self, event: Event) -> None:
        """呈现一个事件(给用户看)。"""
        ...

    async def confirm(self, call: CapabilityCall, decision: Decision, reason: str = "") -> bool:
        """请求用户确认一次能力调用(软边界)。reason 是治理给出的原因。返回是否放行。"""
        ...

    def identity(self) -> Identity:
        """当前消息的主体身份。"""
        ...
