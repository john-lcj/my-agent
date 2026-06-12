"""协调层 —— 模式 A+：Captain 先自治，步数用尽再升级专家；/专家名 为快捷通道。"""
from __future__ import annotations

import asyncio
import re
from typing import Optional

from agents.commands import format_experts_help, parse_slash_command
from agents.dispatcher import DispatchPlan
from agents.registry import AgentRegistry
from config import Config
from core.bus import EventBus
from core.captain_phase import CaptainPhaseExhausted
from core.context import Context
from core.types import Event, EventType, Role
from governance.resource_lock import ResourceLock

_CHAT_ONLY = re.compile(
    r"^(你好|嗨|hi|hello|谢谢|好的|嗯|在吗|你是谁|你能做什么)[\s!?。.~]*$",
    re.I,
)


class Coordinator:
    """Captain 入口：默认 Captain 在 CAPTAIN_MAX_STEPS 内自治；用尽后路由专家。"""

    def __init__(
        self,
        main_agent,
        worker_registry: AgentRegistry,
        dispatcher=None,
        resource_lock: Optional[ResourceLock] = None,
        bus: Optional[EventBus] = None,
    ) -> None:
        self._main = main_agent
        self._workers = worker_registry
        self._dispatcher = dispatcher
        self._lock = resource_lock or ResourceLock()
        self._bus = bus or EventBus()

    async def run(self, task: str, ctx: Context, confirm) -> str:
        names = set(self._workers.names())
        cmd = parse_slash_command(task, names, skill_names=set())

        if cmd.kind == "list_experts":
            workers = [self._workers.get(n) for n in self._workers.names()]
            workers = [w for w in workers if w is not None]
            text = format_experts_help(workers)
            self._emit(EventType.ASSISTANT_MESSAGE, {"text": text, "source": "coordinator"})
            return text

        if cmd.kind in ("list_skills", "invoke_skill", "list_models", "set_model"):
            text = "该命令由会话层处理(/skills、/skill、/model)。"
            self._emit(EventType.ASSISTANT_MESSAGE, {"text": text, "source": "coordinator"})
            return text

        if cmd.kind == "unknown":
            text = f"未知命令 `/{cmd.target}`。输入 /experts 或 /skills 查看帮助。"
            self._emit(EventType.ASSISTANT_MESSAGE, {"text": text, "source": "coordinator"})
            return text

        if cmd.kind == "invoke_expert":
            return await self._invoke_worker(
                cmd.target, cmd.task, ctx, confirm, original_task=task,
            )

        if getattr(ctx, "captain_only", False):
            return await self._main.run(task, ctx, confirm)

        if self._is_casual_chat(task):
            return await self._main.run(task, ctx, confirm)

        return await self._run_captain_then_maybe_escalate(task, ctx, confirm)

    async def _run_captain_then_maybe_escalate(self, task: str, ctx: Context, confirm) -> str:
        limit = max(1, Config.CAPTAIN_MAX_STEPS)
        try:
            return await self._main.run(
                task, ctx, confirm, captain_phase_limit=limit,
            )
        except CaptainPhaseExhausted as exc:
            return await self._escalate_to_expert(
                task, ctx, confirm, exc.summary,
            )

    async def _escalate_to_expert(
        self, task: str, ctx: Context, confirm, captain_summary: str,
    ) -> str:
        self._emit(EventType.ASSISTANT_MESSAGE, {
            "text": (
                f"Captain 在 {Config.CAPTAIN_MAX_STEPS} 步内未能完成，正在请专家接手…"
            ),
            "source": "coordinator",
        })

        if self._dispatcher is None:
            return (
                f"Captain 在限定步数内未能完成任务。\n\n{captain_summary}\n\n"
                "（未配置专家路由，请使用 /专家名 指定专家。）"
            )

        workers = [self._workers.get(n) for n in self._workers.names()]
        workers = [w for w in workers if w is not None]
        route_text = (
            f"{task.strip()}\n\n"
            f"[Captain 已尝试但未完成]\n{captain_summary}"
        )
        plan = await self._dispatcher.route(route_text, workers)
        if plan.is_empty():
            return (
                f"Captain 在限定步数内未能完成，且暂无合适专家可承接。\n\n"
                f"{captain_summary}\n\n"
                "请换用 /experts 查看专家并显式调用。"
            )

        reason = plan.reason or f"Captain {Config.CAPTAIN_MAX_STEPS} 步用尽后升级"
        return await self._execute_plan(
            task, plan, ctx, confirm, captain_summary=captain_summary, route_reason=reason,
        )

    async def _execute_plan(
        self,
        original_task: str,
        plan: DispatchPlan,
        ctx: Context,
        confirm,
        *,
        captain_summary: str = "",
        route_reason: str = "",
    ) -> str:
        if not self._has_user_turn(ctx, original_task):
            ctx.add_user(original_task)
            self._emit(EventType.USER_MESSAGE, {"text": original_task})

        reason = route_reason or plan.reason or "升级专家"
        self._emit(EventType.CAPABILITY_CALL, {
            "name": "coordinator.dispatch",
            "args": {
                "assignments": [
                    {"agent": a.agent_name, "sub_task": a.sub_task}
                    for a in plan.assignments
                ],
                "parallel": plan.parallel,
                "captain_summary": captain_summary[:300] if captain_summary else "",
            },
            "intent": reason,
        })

        results = await self._run_assignments(plan, original_task, captain_summary)
        self._emit(EventType.CAPABILITY_RESULT, {
            "ok": True,
            "output": f"已完成 {len(results)} 个专家任务",
        })
        return await self._captain_synthesize(original_task, results, reason, ctx, confirm)

    async def _run_assignments(
        self,
        plan: DispatchPlan,
        original_task: str,
        captain_summary: str = "",
    ) -> list[tuple[str, str]]:
        if plan.parallel and len(plan.assignments) > 1:
            coros = [
                self._run_one_worker(
                    a.agent_name,
                    self._pack_worker_task(original_task, a.sub_task, captain_summary),
                )
                for a in plan.assignments
            ]
            pairs = await asyncio.gather(*coros)
            return list(pairs)

        results: list[tuple[str, str]] = []
        for a in plan.assignments:
            packed = self._pack_worker_task(original_task, a.sub_task, captain_summary)
            results.append(await self._run_one_worker(a.agent_name, packed))
        return results

    async def _run_one_worker(self, agent_name: str, sub_task: str) -> tuple[str, str]:
        worker = self._workers.get(agent_name)
        if worker is None:
            return agent_name, f"[{agent_name}] 未找到专家"
        try:
            result = await worker.run(sub_task)
            return agent_name, result or "(无输出)"
        except Exception as e:
            return agent_name, f"[{agent_name}] 执行失败: {e}"

    async def _invoke_worker(
        self,
        agent_name: str,
        sub_task: str,
        ctx: Context,
        confirm,
        *,
        original_task: str,
    ) -> str:
        if not self._has_user_turn(ctx, original_task):
            ctx.add_user(original_task)
            self._emit(EventType.USER_MESSAGE, {"text": original_task})

        packed = self._pack_worker_task(
            original_task,
            sub_task,
            self._dialogue_hint(ctx),
        )
        self._emit(EventType.CAPABILITY_CALL, {
            "name": "coordinator.invoke",
            "args": {"agent": agent_name, "task": sub_task},
            "intent": f"显式调用专家 {agent_name}",
        })
        name, result = await self._run_one_worker(agent_name, packed)
        ok = "执行失败" not in result
        self._emit(EventType.CAPABILITY_RESULT, {
            "ok": ok,
            "output": f"[{name}] {(result or '')[:200]}",
        })

        display = (result or "").strip() or "(无输出)"
        worker = self._workers.get(agent_name)
        role_label = getattr(worker, "role", None) if worker else None

        # 显式 /专家名:直接展示专家答复,不经 Captain 二次汇总(避免专业内容被稀释)
        ctx.add_assistant(display, name=name)
        self._emit(EventType.ASSISTANT_MESSAGE, {
            "text": display,
            "source": name,
            "expert_role": role_label or name,
            "direct_expert": True,
        })
        return display

    @staticmethod
    def _pack_worker_task(
        original_task: str,
        sub_task: str,
        captain_context: str = "",
    ) -> str:
        parts = [f"【主人原始任务】\n{original_task.strip()}"]
        if captain_context.strip():
            parts.append(f"【Captain 上下文】\n{captain_context.strip()}")
        parts.append(f"【请你执行】\n{sub_task.strip()}")
        return "\n\n".join(parts)

    @staticmethod
    def _dialogue_hint(ctx: Context, max_turns: int = 4) -> str:
        lines: list[str] = []
        for m in ctx.messages[-max_turns * 2 :]:
            if m.role == Role.USER:
                lines.append(f"主人: {(m.content or '')[:200]}")
            elif m.role == Role.ASSISTANT and m.content and not m.tool_calls:
                lines.append(f"Captain: {(m.content or '')[:200]}")
        return "\n".join(lines) if lines else ""

    @staticmethod
    def _is_casual_chat(task: str) -> bool:
        t = (task or "").strip()
        return bool(t and _CHAT_ONLY.match(t))

    async def _captain_synthesize(
        self,
        original_task: str,
        results: list[tuple[str, str]],
        route_reason: str,
        ctx: Context,
        confirm,
    ) -> str:
        blocks = []
        for name, text in results:
            blocks.append(f"### {name}\n{text}")
        expert_block = "\n\n".join(blocks)

        synthesis_task = (
            "[内部汇总任务 — 以下专家已完成执行，请由 Captain 向主人回复]\n\n"
            f"主人原始消息:\n{original_task}\n\n"
            f"派发理由: {route_reason or '执行任务'}\n\n"
            f"专家执行结果:\n{expert_block}\n\n"
            "请用 Captain 口吻向主人汇总:说明做了什么、关键结果/产物路径、是否成功。"
            "简洁有条理，不要粘贴专家原文全文，不要暴露内部调度术语。"
        )

        ctx.captain_only = True
        try:
            return await self._main.run(
                synthesis_task, ctx, confirm, record_user=False,
            )
        finally:
            ctx.captain_only = False

    @staticmethod
    def _has_user_turn(ctx: Context, text: str) -> bool:
        return any(
            m.role == Role.USER and (m.content or "").strip() == text.strip()
            for m in ctx.messages
        )

    def _emit(self, etype: EventType, payload: dict) -> None:
        self._bus.publish(Event(type=etype, payload=payload))
