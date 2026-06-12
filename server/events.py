"""流式事件协议 —— 后端推给前端的统一 JSON 形态。

前端 handler 对照:
  user_message          -> (通常仅历史)
  assistant_token       -> 流式累加 agent 气泡(终局前)
  assistant_message     -> chatMsg agent / 流式气泡定稿
  capability_call       -> tool 条
  capability_result     -> tool 结果
  governance_decision   -> 治理审计条
  approval_result       -> 审批结果
  task_done             -> 结束 thinking
  status_bar            -> 输入框上方状态栏(模型/上下文/时长)
  error                 -> 错误 toast
"""
from __future__ import annotations

from core.types import Event, EventType  # noqa: F401


def to_wire(event: Event) -> dict:
    return {
        "type": event.type.value,
        "payload": event.payload,
        "trace_id": event.trace_id,
        "ts": event.ts,
    }
