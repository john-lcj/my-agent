"""事件总线 —— 平台的脊椎。

多 agent + 多 channel + 流式,本质都是"事件流动"。从第一天就立这根主干:
所有单向通知(用户消息、token、工具调用、结果、完成)都发布到总线,
订阅者(观测、渲染、未来的 agent 间通信)各取所需。

注:双向交互(如软边界确认)不走总线,而是用直接回调,见 loop.confirm。
"""
from __future__ import annotations

import logging
from typing import Callable

from core.types import Event

Handler = Callable[[Event], None]

_log = logging.getLogger("agent.bus")


class EventBus:
    def __init__(self) -> None:
        self._handlers: list[Handler] = []

    def subscribe(self, handler: Handler) -> None:
        self._handlers.append(handler)

    def publish(self, event: Event) -> None:
        for h in self._handlers:
            try:
                h(event)
            except Exception:
                # 订阅者出错不应影响主流程或其他订阅者,但绝不静默吞掉——
                # 记录下来,否则渲染/观测里的 bug 会隐形,极难排查。
                _log.exception(
                    "事件订阅者处理 %s 时抛出异常(已隔离,不影响其他订阅者)",
                    getattr(event, "type", "?"),
                )
