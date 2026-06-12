"""调度循环 —— 到点把任务交给 agent 执行,并守住"无人值守"的安全底线。

关键安全设计(对应治理"拿不准就问"):
  定时任务运行时没有人在场确认,所以 confirm 回调一律返回 False(fail-safe)。
  这意味着:任何被治理判为 ASK(写/删/执行/花钱)的动作都会被自动拒绝,
  定时任务实际只能完成"读/分析/汇报"这类可逆操作。要让它能写,需要显式
  在 policy 里给定时任务的角色开白名单 —— 把放权变成一个明确的决定,而非默认。

执行产物可选地投递到某个渠道(邮件/微信/QQ),实现"按时给我发简报"这类需求。
"""
from __future__ import annotations

import asyncio
import time
from typing import Awaitable, Callable, Optional

from core.context import Context
from core.types import Identity
from scheduler.store import ScheduledTask, TaskStore

# run_task(task, actor) -> 执行结果文本
RunTaskFn = Callable[[ScheduledTask, Identity], Awaitable[str]]
# deliver(channel, to, subject, body) -> None
DeliverFn = Callable[[str, str, str, str], Awaitable[None]]


class Scheduler:
    def __init__(
        self,
        store: TaskStore,
        run_task: RunTaskFn,
        deliver: Optional[DeliverFn] = None,
        tick_sec: float = 5.0,
    ) -> None:
        self.store = store
        self._run_task = run_task
        self._deliver = deliver
        self.tick_sec = tick_sec
        self._task: Optional[asyncio.Task] = None
        self._running = False

    def start(self) -> None:
        if self._task and not self._task.done():
            return
        self._running = True
        self._task = asyncio.create_task(self._loop())

    def stop(self) -> None:
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()

    async def _loop(self) -> None:
        while self._running:
            try:
                await self._tick()
            except Exception as e:
                print(f"[scheduler] tick 异常: {e}")
            await asyncio.sleep(self.tick_sec)

    async def _tick(self) -> None:
        now = time.time()
        for task in self.store.list():
            if not task.enabled:
                continue
            if task.next_run and task.next_run > now:
                continue
            # 防止刚创建/刚跑完又立刻触发:next_run 为 0 视为"尽快跑一次"
            await self.run_once(task)

    async def run_once(self, task: ScheduledTask) -> ScheduledTask:
        """立即执行一个任务(供调度循环或"手动运行"调用)。"""
        # 定时任务的主体:带 scheduler 角色,便于 policy 单独管控其权限。
        actor = Identity(subject_id=f"scheduler:{task.id}", agent_name="scheduler",
                         channel="scheduler", roles=("scheduler",))
        try:
            result = await self._run_task(task, actor)
            task.last_status = "ok"
            task.last_result = (result or "")[:2000]
        except Exception as e:
            task.last_status = "error"
            task.last_result = str(e)[:2000]

        task.last_run = time.time()
        task.next_run = task.compute_next_run(task.last_run)
        self.store.save(task)

        # 投递结果
        if self._deliver and task.deliver and task.deliver != "none":
            try:
                await self._deliver(task.deliver, task.deliver_to,
                                    f"[定时任务] {task.name}", task.last_result)
            except Exception as e:
                print(f"[scheduler] 投递失败: {e}")
        return task
