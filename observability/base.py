"""观测接口 —— 让你能"放心放手"的前提:每一步都有记录、可回放。

接口以 Event 为单位,天然带 trace_id:单 agent 够用;多 agent 后,
同一任务跨多个 agent/工具的事件可凭 trace_id 串成一条完整链路(分布式追踪)。
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable

from core.types import Event


@runtime_checkable
class Tracer(Protocol):
    def log(self, event: Event) -> None: ...
