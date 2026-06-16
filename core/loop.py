"""编排器(主循环)—— agent 的心脏。

刻意保持简单:感知 -> 规划 -> (治理)-> 行动 -> 反思,循环往复。
它只依赖接口(LLM / CapabilityRegistry / PolicyEngine / EventBus / Budget),
不 import 任何具体实现。换模型、换工具、换策略,这里一行都不用改。

治理是循环里的一道硬关卡(不是 prompt 里的请求):
模型再想做什么,都必须先过 policy.review。这就是"分寸感"的物理位置。
"""
from __future__ import annotations

import asyncio
import json
import uuid
from typing import Awaitable, Callable, Optional

from core.bus import EventBus
from core.context import Context
from core.types import (
    CapabilityCall,
    CapabilityResult,
    Decision,
    Event,
    EventType,
    Risk,
    Role,
)
from governance.budget import BudgetGovernor

# 软边界确认回调:由 channel 提供(CLI 用 input,Web 用确认卡片)。
# confirm(call, decision, reason="") -> bool。reason 为治理给出的"为什么需要确认"。
ConfirmFn = Callable[..., Awaitable[bool]]


class Agent:
    def __init__(
        self,
        llm,
        registry,
        policy,
        bus: EventBus,
        budget: Optional[BudgetGovernor] = None,
        rollback=None,
        summarizer=None,
    ) -> None:
        self.llm = llm
        self.registry = registry
        self.policy = policy
        self.bus = bus
        self.budget = budget or BudgetGovernor()
        self.rollback = rollback
        self.summarizer = summarizer
        self.last_trace_id: Optional[str] = None
        # 写文件资源锁等待上限(秒);超时按"资源被占用"失败,防止整个 agent 卡死。
        self.write_lock_timeout: float = 15.0

    async def run(
        self,
        user_text: str,
        ctx: Context,
        confirm: ConfirmFn,
        *,
        record_user: bool = True,
        captain_phase_limit: int | None = None,
    ) -> str:
        trace_id = uuid.uuid4().hex
        self.last_trace_id = trace_id

        def emit(etype: EventType, payload: dict) -> None:
            self.bus.publish(Event(type=etype, payload=payload, trace_id=trace_id))

        # 自动召回:任务开始前,从长期记忆里取与本次输入相关的条目,作为一条
        # 瞬时 system 提示注入(不入库)。这让 agent 跨会话也能"想起你是谁"。
        self._inject_memories(user_text, ctx)
        self._inject_experience(user_text, ctx)
        self._inject_skill_suggestion(user_text, ctx)
        self._inject_journal(ctx)
        await self._prefetch_skills(user_text, ctx)

        if record_user:
            ctx.add_user(user_text)
            emit(EventType.USER_MESSAGE, {"text": user_text})
        ctx.task_auto_approve = False
        self.budget.reset()

        saved_max_steps: int | None = None
        if captain_phase_limit is not None and captain_phase_limit > 0:
            saved_max_steps = self.budget.max_steps
            self.budget.max_steps = min(saved_max_steps, captain_phase_limit)

        try:
            return await self._run_loop(user_text, ctx, confirm, record_user, captain_phase_limit)
        finally:
            if saved_max_steps is not None:
                self.budget.max_steps = saved_max_steps

    async def _run_loop(
        self,
        user_text: str,
        ctx: Context,
        confirm: ConfirmFn,
        record_user: bool,
        captain_phase_limit: int | None,
    ) -> str:
        trace_id = self.last_trace_id or uuid.uuid4().hex
        self.last_trace_id = trace_id

        def emit(etype: EventType, payload: dict) -> None:
            self.bus.publish(Event(type=etype, payload=payload, trace_id=trace_id))

        while True:
            if self.budget.exceeded():
                if captain_phase_limit is not None:
                    from core.captain_phase import CaptainPhaseExhausted, build_attempt_summary
                    raise CaptainPhaseExhausted(
                        build_attempt_summary(ctx, user_text),
                        user_text=user_text,
                    )
                msg = f"已停止:{self.budget.reason()}"
                emit(EventType.ERROR, {"message": msg})
                ctx.add_system(msg)
                return msg
            self.budget.charge_step()

            # 上下文工程:对话超长时先压缩早期对话(摘要),再规划。
            if self.summarizer is not None:
                await ctx.compact(self.summarizer)

            # 感知 + 规划:让模型决定下一步(终局文本可流式推送 token)
            async def emit_token(chunk: str) -> None:
                if chunk:
                    emit(EventType.ASSISTANT_TOKEN, {"token": chunk})

            # 计 input token:每轮都把全部历史 + 能力清单发给模型,input 才是成本大头。
            # 不计会让 token/金额统计严重偏低,max_cost_usd 刹车随之失真。
            self._charge_input(ctx)

            try:
                step = await self.llm.next_step(
                    ctx.llm_view(), self.registry.specs(), emit_token=emit_token,
                )
            except Exception as e:
                from llm.errors import format_llm_error
                text = format_llm_error(e)
                emit(EventType.ERROR, {"message": text})
                ctx.add_assistant(text)
                emit(EventType.ASSISTANT_MESSAGE, {"text": text})
                return text

            if step.is_final:
                text = step.text or ""
                self.budget.charge(text, getattr(self.llm, "name", ""))
                ctx.add_assistant(text)
                emit(EventType.ASSISTANT_MESSAGE, {
                    "text": text,
                    "budget": self.budget.summary(),
                    "budget_detail": {
                        "tokens": self.budget.tokens,
                        "cost_usd": self.budget.cost_usd,
                    },
                })
                return text

            call = step.call
            if not call.call_id:
                call.call_id = uuid.uuid4().hex
            # intent 也计入 token(它是模型输出的一部分)
            self.budget.charge(call.intent or call.name, getattr(self.llm, "name", ""))
            emit(EventType.CAPABILITY_CALL,
                 {"name": call.name, "args": call.args, "intent": call.intent})
            # 记录 assistant 的工具调用轮次。无论后续放行/拒绝/禁止,都必须补一条
            # 配对的 tool 结果消息,否则对话记录不合法(provider 会报错)。
            ctx.add_tool_call(
                call.call_id,
                call.name,
                call.args,
                call.intent,
                reasoning_content=step.reasoning_content,
            )

            # 治理:统一收口审查(硬边界 / 软边界)。用 review_detailed 拿到
            # "为什么"和"哪条规则",既回传给模型,也落 trace 供后续统计迭代。
            review = self.policy.review_detailed(call, ctx.identity, ctx)
            decision = review.decision
            emit(EventType.GOVERNANCE_DECISION, {
                "name": call.name, "decision": decision.value,
                "reason": review.reason, "rule": review.rule,
            })
            if decision == Decision.BLOCK:
                note = f"能力 [{call.name}] 被策略拒绝:{review.reason}"
                emit(EventType.CAPABILITY_RESULT, {"ok": False, "error": note})
                self._audit(ctx, call, "block", False, review.rule or review.reason)
                ctx.add_tool_result(note, call.call_id, name=call.name)
                continue
            if decision == Decision.ASK:
                approved = await confirm(call, decision, review.reason)
                emit(EventType.APPROVAL_RESULT, {"name": call.name, "approved": approved})
                if not approved:
                    note = f"用户拒绝了能力 [{call.name}]。"
                    emit(EventType.CAPABILITY_RESULT, {"ok": False, "error": note})
                    self._audit(ctx, call, "ask-denied", False, review.rule)
                    ctx.add_tool_result(note, call.call_id, name=call.name)
                    continue

            # 行动前:对写/破坏类且作用于文件的操作做可还原快照(让放手安全)。
            cap = self.registry.get(call.name)
            write_path = ""
            if cap is not None and cap.risk >= Risk.WRITE and call.args.get("path"):
                write_path = str(call.args["path"])
            if self.rollback is not None and write_path:
                try:
                    self.rollback.snapshot(write_path, trace_id, call.call_id)
                except Exception:
                    pass  # 快照失败不应阻断主流程

            # 行动:统一管线执行(异常也必须补 tool 结果,否则下一轮 LLM 请求 400)
            # 写文件前按路径加资源锁:并行专家/委托写同一文件时串行化,避免互相覆盖。
            try:
                if write_path:
                    import os as _os
                    from governance.resource_lock import default_lock
                    lock_key = _os.path.abspath(write_path)
                    guard = await default_lock.try_acquire(lock_key, timeout=self.write_lock_timeout)
                    if guard is None:
                        result = CapabilityResult(
                            ok=False,
                            error=f"资源被占用:{write_path} 正被其他任务写入,请稍后重试",
                        )
                    else:
                        try:
                            result = await self.registry.invoke(call.name, call.args, ctx)
                        finally:
                            guard.release()
                else:
                    result = await self.registry.invoke(call.name, call.args, ctx)
            except Exception as exc:
                result = CapabilityResult(ok=False, error=str(exc))
            emit(EventType.CAPABILITY_RESULT,
                 {"ok": result.ok, "output": result.output, "error": result.error})
            self._audit(ctx, call, decision.value, result.ok,
                        "" if result.ok else (result.error or "")[:200])
            body = result.output if result.ok else f"[失败] {result.error}"
            ctx.add_tool_result(body, call.call_id, name=call.name)

    def _charge_input(self, ctx: Context) -> None:
        """估算并计入本轮发送给模型的 input token(全部历史 + 能力清单)。"""
        try:
            parts: list[str] = []
            for m in ctx.llm_view():
                parts.append(str(getattr(m, "content", "") or ""))
                for tc in (getattr(m, "tool_calls", None) or []):
                    parts.append(f"{getattr(tc, 'name', '')}{getattr(tc, 'args', '')}")
            parts.append(json.dumps(self.registry.specs(), ensure_ascii=False))
            self.budget.charge("\n".join(parts), getattr(self.llm, "name", ""))
        except Exception:
            pass  # 计费失败不应阻断主流程

    async def _prefetch_skills(self, user_text: str, ctx: Context) -> None:
        """按任务文本匹配 READ skill,预调用并将结果注入上下文(仅轻量 skill,有上限)。"""
        from config import Config
        from skills.router import match_routes, routes_to_prefetch, should_route

        if not Config.SKILL_PREFETCH or not should_route(user_text):
            return

        routes = routes_to_prefetch(match_routes(user_text, max_routes=1))
        if not routes:
            return

        max_chars = max(200, Config.SKILL_PREFETCH_MAX_CHARS)
        blocks: list[str] = []
        for route in routes[:1]:
            cap = self.registry.get(f"skill.{route.name}")
            if cap is None:
                continue
            try:
                # 预取只为"提速开场",本身不能拖慢开场:超 1.5s 就放弃,
                # 让 agent 该调时自己再调,不阻塞首轮响应。
                result = await asyncio.wait_for(
                    cap.invoke(route.args, ctx), timeout=1.5,
                )
            except Exception:
                continue
            if not result.ok and not result.output:
                continue
            body = (result.output if result.ok else (result.error or "")).strip()
            if not body:
                continue
            if len(body) > max_chars:
                body = body[:max_chars] + "\n…(已截断,需要完整内容请再次调用 skill)"
            blocks.append(f"— skill.{route.name} ({route.reason})\n{body}")

        if not blocks:
            return

        block = (
            "[Skill 预加载 — 本任务已自动拉取相关规范/工具输出,请据此执行;"
            "需要时可再次调用 skill.* 补全或 preflight]\n"
            + "\n\n".join(blocks)
        )
        ctx.messages = [
            m for m in ctx.messages
            if not (m.role == Role.SYSTEM and m.content.startswith("[Skill 预加载"))
        ]
        ctx.add_system(block)

    def _inject_memories(self, user_text: str, ctx: Context) -> None:
        """检索相关长期记忆并注入为瞬时 system 消息(去重,避免反复堆叠)。"""
        mem = getattr(ctx, "longterm", None)
        if mem is None:
            return
        try:
            items = mem.retrieve(user_text, k=5)
        except Exception:
            return
        if not items:
            return
        block = "[关于主人的已知记忆,供参考]\n" + "\n".join(
            f"- [{getattr(it, 'source', 'agent')}] {it.content}" for it in items)
        # 移除上一轮注入的旧记忆块,只保留最新一份。
        ctx.messages = [m for m in ctx.messages
                        if not (m.role == Role.SYSTEM and m.content.startswith("[关于主人的已知记忆"))]
        ctx.add_system(block)

    def _audit(self, ctx: Context, call, decision: str, ok: bool, detail: str = "") -> None:
        """写一条审计记录(append-only),失败静默。只记安全相关字段,不记内容。"""
        try:
            from observability.audit import audit
            audit(
                trace_id=getattr(self, "last_trace_id", "") or "",
                agent=getattr(getattr(ctx, "identity", None), "agent_name", "") or "",
                capability=call.name, args=call.args,
                decision=decision, ok=ok, detail=detail,
            )
        except Exception:
            pass

    def _inject_skill_suggestion(self, user_text: str, ctx: Context) -> None:
        """若当前任务属于反复出现且未固化的类,注入"建议固化为 skill"的提示(自我改进闭环)。"""
        try:
            from memory.pattern_tracker import PatternTracker
            tip = PatternTracker().suggestion_for(user_text)
        except Exception:
            return
        if not tip:
            return
        ctx.messages = [m for m in ctx.messages
                        if not (m.role == Role.SYSTEM and m.content.startswith("[自我改进提示]"))]
        ctx.add_system(tip)

    def _inject_experience(self, user_text: str, ctx: Context) -> None:
        """注入与当前任务相关的"做法经验"(主动记忆),让 agent 复用有效做法、绕开坑。"""
        mem = getattr(ctx, "longterm", None)
        if mem is None:
            return
        try:
            from memory.experience_miner import format_experience_block
            block = format_experience_block(mem, user_text, k=3)
        except Exception:
            return
        if not block:
            return
        ctx.messages = [m for m in ctx.messages
                        if not (m.role == Role.SYSTEM and m.content.startswith("[过往经验"))]
        ctx.add_system(block)

    def _inject_journal(self, ctx: Context) -> None:
        """会话首轮注入"上次到哪了"协作简报(只在本会话第一轮注入一次)。"""
        # 已有用户消息说明不是首轮;已注入过简报也跳过,避免重复堆叠。
        for m in ctx.messages:
            if m.role == Role.USER:
                return
            if m.role == Role.SYSTEM and m.content.startswith("[我们的协作进展"):
                return
        try:
            from memory.journal import Journal
            briefing = Journal().render_briefing(2)
        except Exception:
            return
        if briefing:
            ctx.add_system(briefing)
