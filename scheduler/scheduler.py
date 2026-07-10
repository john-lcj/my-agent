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
from core.task_outcome import (
    TaskExecutionResult,
    TaskStatus,
    normalize_execution_result,
)
from scheduler.store import ScheduledTask, TaskStore

# run_task(task, actor) -> 执行结果文本
RunTaskFn = Callable[[ScheduledTask, Identity], Awaitable[str | TaskExecutionResult]]
# deliver(channel, to, subject, body) -> None
DeliverFn = Callable[[str, str, str, str], Awaitable[None]]


class TaskAlreadyRunning(RuntimeError):
    """Raised when the same scheduled task is triggered concurrently."""


class Scheduler:
    def __init__(
        self,
        store: TaskStore,
        run_task: RunTaskFn,
        deliver: Optional[DeliverFn] = None,
        tick_sec: float = 5.0,
        durable_jobs=None,
    ) -> None:
        self.store = store
        self._run_task = run_task
        self._deliver = deliver
        self.tick_sec = tick_sec
        self.durable_jobs = durable_jobs
        self._task: Optional[asyncio.Task] = None
        self._running = False
        self._running_task_ids: set[str] = set()

    def start(self) -> None:
        if self._task and not self._task.done():
            return
        self._running = True
        self._task = asyncio.create_task(self._loop())

    def stop(self) -> None:
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()

    async def wait_stopped(self) -> None:
        task = self._task
        if task is None:
            return
        try:
            await task
        except asyncio.CancelledError:
            pass
        finally:
            self._task = None

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
            if self.is_running(task.id):
                continue
            # 防止刚创建/刚跑完又立刻触发:next_run 为 0 视为"尽快跑一次"
            await self.run_once(task)

    def is_running(self, task_id: str) -> bool:
        return task_id in self._running_task_ids

    async def run_once(self, task: ScheduledTask) -> ScheduledTask:
        """立即执行一个任务(供调度循环或"手动运行"调用)。"""
        if self.is_running(task.id):
            raise TaskAlreadyRunning(f"task {task.id} is already running")
        self._running_task_ids.add(task.id)
        durable = None
        try:
            if self.durable_jobs is not None:
                durable = self.durable_jobs.create_job(
                    "scheduled", {"task_id": task.id, "name": task.name},
                    idempotency_key=f"scheduled:{task.id}:{int(time.time())}",
                )
                durable = self.durable_jobs.claim(durable["id"], f"scheduler:{task.id}", lease_seconds=120)
                if durable:
                    self.durable_jobs.add_steps(durable["id"], [{"name": "execute"}, {"name": "deliver"}])
                    self.durable_jobs.checkpoint(durable["id"], {"phase": "execute", "task_id": task.id})
            # 定时任务的主体:带 scheduler 角色,便于 policy 单独管控其权限。
            actor = Identity(subject_id=f"scheduler:{task.id}", agent_name="scheduler",
                             channel="scheduler", roles=("scheduler",))
            try:
                outcome = normalize_execution_result(await self._run_task(task, actor))
                task.execution_status = outcome.status
                task.last_status = outcome.status
                task.last_result = (outcome.output or outcome.error or "")[:2000]
                task.last_error = (outcome.error or "")[:2000]
            except Exception as e:
                task.execution_status = TaskStatus.FAILED.value
                task.last_status = TaskStatus.FAILED.value
                task.last_result = str(e)[:2000]
                task.last_error = str(e)[:2000]

            task.last_run = time.time()
            task.next_run = task.compute_next_run(task.last_run)
            task.delivery_status = "not_requested"
            task.last_delivery_error = ""

            # 投递结果
            if self._deliver and task.deliver and task.deliver != "none":
                try:
                    await self._deliver(task.deliver, task.deliver_to,
                                        f"[定时任务] {task.name}", task.last_result)
                    task.delivery_status = TaskStatus.SUCCEEDED.value
                except Exception as e:
                    task.delivery_status = TaskStatus.FAILED.value
                    task.last_delivery_error = str(e)[:2000]
                    task.last_status = TaskStatus.DELIVERY_FAILED.value
                    print(f"[scheduler] 投递失败: {e}")
            self.store.save(task)
            if durable:
                self.durable_jobs.checkpoint(durable["id"], {"phase": "finished", "status": task.last_status})
                self.durable_jobs.set_state(durable["id"], "completed" if task.last_status == TaskStatus.SUCCEEDED.value else "failed", error=task.last_error)
            return task
        finally:
            self._running_task_ids.discard(task.id)
