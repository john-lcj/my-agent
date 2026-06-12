"""Web / IM 渠道 —— 用队列把 WebSocket 桥接到 agent。

聊天界面的重点:流式输出 + 可中断 + 确认卡片。这里实现 Channel 契约:
- emit:把事件投递到出站队列(由 server 的发送任务推给前端);
- confirm:遇到软边界时,推一个 approval_request 给前端,并 await 一个 future,
  直到前端点了"允许/拒绝"(server 调 feed_approval 兑现)。
- receive:从入站队列取用户消息(server 收到前端消息后 feed_user)。

任务代际(task_gen):同一 WebSocket 上并发/取消任务时,旧任务的 token/确认
不应覆盖新任务;emit 自动打上当前 asyncio 任务的代际号。
"""
from __future__ import annotations

import asyncio
from typing import Optional

from channels.task_scope import current_task_gen
from core.types import CapabilityCall, Decision, Event, EventType, Identity


class WebChannel:
    name = "web"

    def __init__(self, subject_id: str = "web-user") -> None:
        self.subject_id = subject_id
        self.outbound: asyncio.Queue = asyncio.Queue()
        self._user: asyncio.Queue = asyncio.Queue()
        # (task_gen, future) —— 仅接受同代际的 feed_approval
        self._approval: Optional[tuple[int, asyncio.Future]] = None

    async def receive(self) -> Optional[str]:
        return await self._user.get()

    def emit(self, event: Event) -> None:
        payload = dict(event.payload or {})
        gen = current_task_gen()
        if gen:
            payload.setdefault("task_gen", gen)
        self.outbound.put_nowait(Event(
            type=event.type,
            payload=payload,
            trace_id=event.trace_id,
            ts=event.ts,
        ))

    async def confirm(self, call: CapabilityCall, decision: Decision, reason: str = "") -> bool:
        loop = asyncio.get_event_loop()
        gen = current_task_gen()
        fut = loop.create_future()
        self._approval = (gen, fut)
        self.emit(Event(
            type=EventType.APPROVAL_REQUEST,
            payload={"name": call.name, "args": call.args, "intent": call.intent,
                     "reason": reason},
        ))
        try:
            return await fut
        except asyncio.CancelledError:
            self.cancel_pending_approval()
            raise

    def identity(self) -> Identity:
        return Identity(subject_id=self.subject_id, agent_name="main", channel="web")

    def cancel_pending_approval(self) -> None:
        """新任务开始或旧任务取消:作废未决确认,避免串线。"""
        if self._approval is None:
            return
        _, fut = self._approval
        if not fut.done():
            fut.set_result(False)
        self._approval = None

    # --- server 侧喂入 ---
    def feed_user(self, text: Optional[str]) -> None:
        self._user.put_nowait(text)

    def feed_approval(self, approved: bool, *, task_gen: int | None = None) -> None:
        if self._approval is None:
            return
        gen, fut = self._approval
        if task_gen is not None and gen != task_gen:
            return
        if not fut.done():
            fut.set_result(approved)
        self._approval = None
