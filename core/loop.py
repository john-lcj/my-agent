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
import re
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
from core.intent_router import classify_intent, intent_prompt_block
from core.task_lifecycle import (
    cognitive_runtime_block,
    create_task_frame,
    lifecycle_prompt_block,
    ready_execution_step,
    record_capability_result,
    role_report_prompt,
    update_plan as lifecycle_update_plan,
)
from core.task_outcome import RunOutcome, TaskStatus

# 软边界确认回调:由 channel 提供(CLI 用 input,Web 用确认卡片)。
# confirm(call, decision, reason="") -> bool。reason 为治理给出的"为什么需要确认"。
ConfirmFn = Callable[..., Awaitable[bool]]

_MISSION_MODE_PROMPT = (
    "[Mission 执行模式] 你在执行主人下达的独立任务,不是闲聊续接。\n"
    "禁止替主人做选择,禁止写「你已确认/点头/定了」。\n"
    "缺资料、方向不明、需主人决策时,只回一行 NEED_INPUT: …\n"
    "完成后给出可验证产物(File path、链接、数据),不要只反问「还要做什么」。"
)


def _is_mission_ctx(ctx: Context) -> bool:
    ch = getattr(getattr(ctx, "identity", None), "channel", "") or ""
    return ch == "mission" or bool(getattr(ctx, "mission_mode", False))


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
        # 单步工具超时(秒):防止某次工具调用(浏览器/网络)挂死拖垮整轮。
        import os as _os
        self.step_timeout: float = float(_os.environ.get("AGENT_STEP_TIMEOUT", "300"))
        # 卡死/打转检测:连续 N 次完全相同的工具调用 → 先劝一次,再多就强制收尾。
        self._stall_nudge_at = int(_os.environ.get("AGENT_STALL_NUDGE_AT", "3"))
        self._stall_stop_at = int(_os.environ.get("AGENT_STALL_STOP_AT", "5"))
        # 防 thrash:同一能力反复失败(哪怕换参数)→ 多半不可用,先劝换路、再多就收尾。
        # 比"同名同参"更宽:抓的是"换着花样试同一个用不了的能力"那种空转(如缺 key 的文生图)。
        self._cap_fail_nudge_at = int(_os.environ.get("AGENT_CAP_FAIL_NUDGE_AT", "2"))
        self._cap_fail_stop_at = int(_os.environ.get("AGENT_CAP_FAIL_STOP_AT", "4"))
        self._delivery_nudged = False
        self._role_llms: dict[str, object] = {}

    async def run(
        self,
        user_text: str,
        ctx: Context,
        confirm: ConfirmFn,
        *,
        record_user: bool = True,
    ) -> str:
        trace_id = uuid.uuid4().hex
        self.last_trace_id = trace_id
        self._session_id = getattr(ctx, "session_id", "") or ""
        self._delivery_nudged = False   # 交付校验门:每轮 run 只拦一次,防死循环
        self._model_ms_total = 0.0      # 本轮模型累计耗时(诊断"慢在哪")
        ctx.run_outcome = RunOutcome()

        def emit(etype: EventType, payload: dict) -> None:
            self.bus.publish(Event(type=etype, payload=payload, trace_id=trace_id))

        # 记录本轮任务文本，供 _run_loop 内各步做能力路由（按需发 specs 子集）。
        self._current_user_text = user_text

        frame = classify_intent(user_text, ctx)
        ctx.intent_frame = frame
        ctx.add_system(intent_prompt_block(frame))
        task_frame = create_task_frame(user_text, frame)
        ctx.task_frame = task_frame
        ctx.add_system(lifecycle_prompt_block(task_frame))
        ctx.add_system(role_report_prompt(task_frame))

        self._inject_credentials_manifest(ctx)
        if _is_mission_ctx(ctx):
            ctx.add_system(_MISSION_MODE_PROMPT)
        else:
            self._inject_opening_memory(user_text, ctx)
            self._inject_anti_sycophancy(user_text, ctx)
            self._inject_journal(ctx)
        self._inject_skill_suggestion(user_text, ctx)
        await self._prefetch_skills(user_text, ctx)

        if record_user:
            ctx.add_user(user_text)
            emit(EventType.USER_MESSAGE, {"text": user_text})
            ctx.task_auto_approve = False
        self.budget.reset()

        ctx.confirm_fn = confirm
        try:
            result = await self._run_loop(user_text, ctx, confirm, record_user)
            ctx.run_outcome.finalize()
            return result
        except Exception as exc:
            ctx.run_outcome.stop(TaskStatus.FAILED.value, str(exc))
            raise
        finally:
            ctx.confirm_fn = None

    async def _run_loop(
        self,
        user_text: str,
        ctx: Context,
        confirm: ConfirmFn,
        record_user: bool,
    ) -> str:
        trace_id = self.last_trace_id or uuid.uuid4().hex
        self.last_trace_id = trace_id

        def emit(etype: EventType, payload: dict) -> None:
            self.bus.publish(Event(type=etype, payload=payload, trace_id=trace_id))

        # 可读 transcript:把这轮全过程写成 Markdown,供"读 transcript 迭代"诊断。
        try:
            from observability.transcript import Transcript
            tr = Transcript(trace_id)
            tr.start(user_text, getattr(ctx, "coworker", False))
        except Exception:
            tr = None
        recent_sigs: list[str] = []   # 卡死检测:近期工具调用签名
        stall_nudged = False
        cap_fail_counts: dict[str, int] = {}   # 防 thrash:每个能力的连续失败次数
        cap_fail_nudged: set[str] = set()      # 已就某能力劝过换路,避免反复刷提示

        while True:
            cancel_check = getattr(ctx, "cancel_check", None)
            if cancel_check is not None and cancel_check():
                ctx.run_outcome.stop(TaskStatus.BLOCKED.value, "job cancellation requested")
                return "任务已取消。"
            if self.budget.exceeded():
                reason = self.budget.reason()
                # 部分成果抢救:步数/预算用尽时,别只返回"已停止"把已收集的数据丢掉,
                # 而是把最近的工具产出(搜索/抓取/读到的真实数据)打包标为「部分完成」,
                # 让下游节点或 Captain 能接着用,而不是从零重来。
                partial = self._salvage_partial(ctx)
                if partial:
                    msg = ("【执行摘要】步数用尽,提交已收集的阶段性成果(未全部完成)\n"
                           f"【产物/数据】\n{partial}\n"
                           f"【状态】部分完成（{reason}）")
                else:
                    msg = f"已停止:{reason}"
                status = (
                    TaskStatus.PARTIAL.value
                    if ctx.run_outcome.successful_actions
                    else TaskStatus.FAILED.value
                )
                ctx.run_outcome.stop(status, reason)
                emit(EventType.ERROR, {"message": f"已停止:{reason}"})
                ctx.add_system(f"已停止:{reason}")
                return msg
            self.budget.charge_step()

            # 上下文工程:对话超长时先压缩早期对话(摘要),再规划。
            if self.summarizer is not None:
                await ctx.compact(self.summarizer)

            # 感知 + 规划:让模型决定下一步(终局文本可流式推送 token)
            async def emit_token(chunk: str) -> None:
                if chunk:
                    emit(EventType.ASSISTANT_TOKEN, {"token": chunk})

            self._refresh_cognitive_context(ctx)
            active_llm = self._select_cognitive_llm(ctx)
            # 计 input token:每轮都把全部历史 + 能力清单发给模型,input 才是成本大头。
            # 不计会让 token/金额统计严重偏低,max_cost_usd 刹车随之失真。
            self._charge_input(ctx)

            try:
                import time as _t
                _mt0 = _t.time()
                step = await active_llm.next_step(
                    ctx.llm_view(),
                    self.registry.specs_for(getattr(self, "_current_user_text", "")),
                    emit_token=emit_token,
                )
                _mdt = _t.time() - _mt0
                self._model_ms_total = getattr(self, "_model_ms_total", 0.0) + _mdt
                if tr is not None and _mdt > 2.0:
                    tr.note(f"模型这一步耗时 {_mdt:.1f}s(模型/网络慢,非本地处理)")
            except Exception as e:
                from llm.errors import format_llm_error
                text = format_llm_error(e)
                ctx.run_outcome.stop(TaskStatus.FAILED.value, text)
                emit(EventType.ERROR, {"message": text})
                ctx.add_assistant(text)
                emit(EventType.ASSISTANT_MESSAGE, {"text": text})
                return text

            if step.is_final:
                text = step.text or ""
                task_frame = getattr(ctx, "task_frame", None)
                gate = ""
                needs_gate = (
                    task_frame is not None
                    and (
                        getattr(task_frame, "role", "") in ("executor", "researcher")
                        or getattr(task_frame, "verification_items", None)
                    )
                ) or getattr(ctx, "coworker", False)
                if needs_gate and task_frame is not None:
                    from core.delivery_gate import unified_final_gate
                    gate = unified_final_gate(task_frame, user_text, text)
                elif needs_gate:
                    from core.delivery_gate import delivery_reference_gate
                    gate = delivery_reference_gate(user_text, text)
                if gate:
                    if tr is not None:
                        tr.note("交付/生命周期自检未过:" + gate[:120])
                    ctx.add_assistant(text)
                    ctx.add_system(gate)
                    self.budget.charge(text, getattr(self.llm, "name", ""))
                    if task_frame is None or task_frame.repair_count <= task_frame.max_repairs:
                        continue
                if not gate and getattr(ctx, "coworker", False):
                    try:
                        gate = await self._content_judge(user_text, text)
                    except Exception:
                        gate = ""
                    if gate:
                        if tr is not None:
                            tr.note("内容质检未过:" + gate[:120])
                        ctx.add_assistant(text)
                        ctx.add_system(gate)
                        self.budget.charge(text, getattr(self.llm, "name", ""))
                        continue
                self.budget.charge(text, getattr(self.llm, "name", ""))
                if tr is not None:
                    tr.note(f"本轮模型累计耗时 ~{getattr(self, '_model_ms_total', 0.0):.1f}s"
                            f"(若偏大,瓶颈在模型/网络,不是本地处理)")
                    tr.final(text)
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

            # ── 卡死/打转检测:连续相同的工具调用(同名同参)说明模型在原地打转 ──
            try:
                _sig = call.name + "|" + json.dumps(call.args, ensure_ascii=False, sort_keys=True)
            except Exception:
                _sig = call.name + "|" + str(call.args)
            recent_sigs.append(_sig)
            _streak = 0
            for s in reversed(recent_sigs):
                if s == _sig:
                    _streak += 1
                else:
                    break
            if _streak >= self._stall_stop_at:
                # 反复同一动作仍无进展 → 强制收尾,交回已收集的阶段性成果,别再烧步数。
                if tr is not None:
                    tr.note(f"连续 {_streak} 次重复调用 {call.name},判定卡死,强制收尾。")
                partial = self._salvage_partial(ctx)
                msg = (f"已停止:检测到反复执行同一动作({call.name})且无进展。\n"
                       + (f"【已收集的阶段性成果】\n{partial}" if partial else "未能取得有效进展。"))
                emit(EventType.ERROR, {"message": f"卡死保护:反复调用 {call.name}"})
                status = (
                    TaskStatus.PARTIAL.value
                    if ctx.run_outcome.successful_actions
                    else TaskStatus.FAILED.value
                )
                ctx.run_outcome.stop(status, f"repeated capability call: {call.name}")
                ctx.add_assistant(msg)
                emit(EventType.ASSISTANT_MESSAGE, {"text": msg})
                return msg
            if _streak == self._stall_nudge_at and not stall_nudged:
                stall_nudged = True
                if tr is not None:
                    tr.note(f"连续 {_streak} 次重复 {call.name},注入换路提示。")
                ctx.add_system(
                    f"[卡死提醒] 你已连续多次执行同一动作「{call.name}」且参数相同、没有进展。"
                    "停止重复——换个方法/工具/参数,或如果确实无更优解,就直接收尾给出结论或如实说明卡点。")
                continue  # 跳过这次重复,让模型带着提示重新决策

            # intent 也计入 token(它是模型输出的一部分)
            self.budget.charge(call.intent or call.name, getattr(self.llm, "name", ""))
            emit(EventType.CAPABILITY_CALL,
                 {"name": call.name, "args": call.args, "intent": call.intent})
            if tr is not None:
                tr.call(call.name, call.intent or "", call.args)
            # 待办清单:把 plan.update 调用翻译成 Progress 面板要的 plan_update 事件。
            if call.name == "plan.update":
                self._emit_plan(emit, call.args)
                try:
                    from capabilities.tools.plan import normalize_steps
                    task_frame = getattr(ctx, "task_frame", None)
                    if task_frame is not None:
                        lifecycle_update_plan(task_frame, normalize_steps(call.args.get("steps")))
                except Exception:
                    pass
            # 记录 assistant 的工具调用轮次。无论后续放行/拒绝/禁止,都必须补一条
            # 配对的 tool 结果消息,否则对话记录不合法(provider 会报错)。
            ctx.add_tool_call(
                call.call_id,
                call.name,
                call.args,
                call.intent,
                reasoning_content=step.reasoning_content,
            )

            # P6 executor gate: real capability invocations may only advance
            # the next dependency-ready cognitive step. plan.update itself is
            # declarative and is intentionally excluded.
            cognitive_step_id = ""
            task_frame = getattr(ctx, "task_frame", None)
            if call.name != "plan.update" and task_frame is not None:
                cognitive_step = ready_execution_step(task_frame)
                state = getattr(task_frame, "cognitive_state", None)
                if state is not None and state.plan.steps:
                    if cognitive_step is None:
                        note = ("[P6 execution gate] No dependency-ready plan step remains. "
                                "Update the plan with a bounded repair or report the verified result.")
                        ctx.run_outcome.action_blocked(note)
                        emit(EventType.CAPABILITY_RESULT, {"ok": False, "error": note, "name": call.name})
                        ctx.add_tool_result(note, call.call_id, name=call.name)
                        ctx.add_system(note)
                        continue
                    cognitive_step_id = cognitive_step.step_id

            # 治理:统一收口审查(硬边界 / 软边界)。用 review_detailed 拿到
            # "为什么"和"哪条规则",既回传给模型,也落 trace 供后续统计迭代。
            review = self.policy.review_detailed(call, ctx.identity, ctx)
            decision = review.decision
            emit(EventType.GOVERNANCE_DECISION, {
                "name": call.name, "decision": decision.value,
                "reason": review.reason, "rule": review.rule,
            })
            if tr is not None:
                tr.decision(decision.value, review.reason or "")
            if decision == Decision.BLOCK:
                note = f"能力 [{call.name}] 被策略拒绝:{review.reason}"
                ctx.run_outcome.action_blocked(note)
                emit(EventType.CAPABILITY_RESULT, {"ok": False, "error": note})
                self._audit(ctx, call, "block", False, review.rule or review.reason)
                ctx.add_tool_result(note, call.call_id, name=call.name)
                continue
            if decision == Decision.ASK:
                approved = await confirm(call, decision, review.reason)
                emit(EventType.APPROVAL_RESULT, {"name": call.name, "approved": approved})
                if not approved:
                    note = f"用户拒绝了能力 [{call.name}]。"
                    ctx.run_outcome.action_blocked(note)
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
                            result = await asyncio.wait_for(
                                self.registry.invoke(call.name, call.args, ctx),
                                timeout=self.step_timeout)
                        finally:
                            guard.release()
                else:
                    result = await asyncio.wait_for(
                        self.registry.invoke(call.name, call.args, ctx),
                        timeout=self.step_timeout)
            except (asyncio.TimeoutError, TimeoutError):
                result = CapabilityResult(
                    ok=False,
                    error=f"工具 {call.name} 执行超过 {self.step_timeout:.0f}s 超时(可能卡住),已中断该步。")
            except Exception as exc:
                result = CapabilityResult(ok=False, error=str(exc))
            cap_payload = {"ok": result.ok, "output": result.output, "error": result.error,
                           "name": call.name}
            if result.ok and call.name == "fs.write":
                path = str((call.args or {}).get("path") or "")
                task_frame = getattr(ctx, "task_frame", None)
                if task_frame is not None and path:
                    try:
                        from core.verification import append_verification
                        append_verification(task_frame, "read_file", path)
                        append_verification(task_frame, "evidence_in_reply", path)
                        if path.lower().endswith((".html", ".htm")):
                            append_verification(task_frame, "check_link", path)
                            append_verification(task_frame, "visual_check", path)
                    except Exception:
                        pass
            if result.ok and call.name == "dev.run_tests":
                target = str((call.args or {}).get("target") or "")
                task_frame = getattr(ctx, "task_frame", None)
                if task_frame is not None and target:
                    try:
                        from core.verification import append_verification
                        append_verification(task_frame, "run_test", target)
                    except Exception:
                        pass
            if result.ok and call.name == "image.generate" and result.output:
                import re as _re
                _m = _re.search(r"已生成图片[:：]\s*(.+)", str(result.output).strip())
                if _m:
                    _ap = _m.group(1).strip().replace("\\", "/")
                    _i = _ap.find("产物/")
                    if _i >= 0:
                        _ap = _ap[_i:]
                    _ap = _ap.rstrip("，。；、！？）)]")
                    if _ap:
                        cap_payload["artifact_path"] = _ap
            emit(EventType.CAPABILITY_RESULT, cap_payload)
            if result.ok:
                ctx.run_outcome.action_succeeded()
            else:
                ctx.run_outcome.action_failed(result.error or f"{call.name} failed")
            if tr is not None:
                tr.result(result.ok, result.output or "", result.error or "")
            self._audit(ctx, call, decision.value, result.ok,
                        "" if result.ok else (result.error or "")[:200])
            body = result.output if result.ok else f"[失败] {result.error}"
            ctx.add_tool_result(body, call.call_id, name=call.name)
            if cognitive_step_id and task_frame is not None:
                try:
                    record_capability_result(
                        task_frame,
                        cognitive_step_id,
                        succeeded=result.ok,
                        evidence=(result.output if result.ok else (result.error or call.name)),
                    )
                except Exception:
                    # A state-recording failure must not make an already-run
                    # capability look successful to the next model turn.
                    ctx.add_system("[P6 execution gate] Capability completed but its durable plan transition could not be recorded. Stop and verify state.")

            # ── 防 thrash:同一能力反复失败(换参数也算)→ 多半不可用,劝换路/强制收尾 ──
            if result.ok:
                cap_fail_counts[call.name] = 0          # 有进展,清零
            else:
                cap_fail_counts[call.name] = cap_fail_counts.get(call.name, 0) + 1
                _fc = cap_fail_counts[call.name]
                if _fc >= self._cap_fail_stop_at:
                    if tr is not None:
                        tr.note(f"能力 {call.name} 已失败 {_fc} 次,判定不可用,强制收尾。")
                    partial = self._salvage_partial(ctx)
                    msg = (f"已停止:能力「{call.name}」反复失败 {_fc} 次(最近:{(result.error or '')[:120]}),"
                           "判定为当前不可用,停止空转。\n"
                           + (f"【已收集的阶段性成果】\n{partial}" if partial
                              else "请补齐该能力所需配置(如缺 key),或改用其它方案。"))
                    status = (
                        TaskStatus.PARTIAL.value
                        if ctx.run_outcome.successful_actions
                        else TaskStatus.FAILED.value
                    )
                    ctx.run_outcome.stop(status, result.error or f"{call.name} repeatedly failed")
                    emit(EventType.ERROR, {"message": f"thrash 保护:{call.name} 反复失败"})
                    ctx.add_assistant(msg)
                    emit(EventType.ASSISTANT_MESSAGE, {"text": msg})
                    return msg
                if _fc >= self._cap_fail_nudge_at and call.name not in cap_fail_nudged:
                    cap_fail_nudged.add(call.name)
                    if tr is not None:
                        tr.note(f"能力 {call.name} 失败 {_fc} 次,注入换路提示。")
                    ctx.add_system(
                        f"[能力失败提醒]「{call.name}」已失败 {_fc} 次(最近原因:{(result.error or '')[:120]})。"
                        "这往往意味着它当前不可用或缺配置(如缺 key/权限)。别再换着参数反复试同一能力——"
                        "要么换一个完全不同的工具/方案,要么如实说明缺口、给出替代后收尾。")

    def _refresh_cognitive_context(self, ctx: Context) -> None:
        """Expose only the current P6 package, without persisting a message per step."""
        task = getattr(ctx, "task_frame", None)
        if task is None:
            return
        block = cognitive_runtime_block(task)
        if not block:
            return
        from core.types import Message, Role
        ctx.messages = [
            message for message in ctx.messages
            if not (message.role == Role.SYSTEM and message.content.startswith("[P6 runtime state"))
        ]
        # This message is intentionally ephemeral: a fresh package replaces it
        # on every decision, rather than bloating persisted conversation history.
        ctx.messages.append(Message(role=Role.SYSTEM, content=block))

    def _select_cognitive_llm(self, ctx: Context):
        """Route planning and verification to configured stronger role models.

        Each role model is built through the normal factory, so its configured
        fallback chain preserves the same tool-call conversation contract.
        """
        task = getattr(ctx, "task_frame", None)
        state = getattr(task, "cognitive_state", None)
        route = state.routes[-1] if state is not None and state.routes else None
        if route is None or route.preferred_tier != "strong":
            return self.llm
        role_name = "planner" if route.role.value == "planner" else "judge"
        if role_name not in self._role_llms:
            try:
                from llm.factory import build_role_llm
                self._role_llms[role_name] = build_role_llm(role_name)
            except Exception:
                self._role_llms[role_name] = None
        return self._role_llms.get(role_name) or self.llm

    def _referenced_files(self, text: str) -> list:
        """从回复里抽出引用的文件,返回 [(原始写法, 存在的绝对路径 或 None)]。"""
        import os
        import re
        ws = os.environ.get("AGENT_WORKSPACE_ROOT", "").strip() or os.getcwd()
        out: list = []
        seen = set()
        for c in re.findall(
                r"[\w一-鿿./_-]+\.(?:md|html|htm|pdf|docx|xlsx|xls|csv|pptx|png|jpg|jpeg|json|txt)",
                text or ""):
            c = c.strip().lstrip("./")
            if not c or " " in c or c in seen:
                continue
            seen.add(c)
            cands = [c if os.path.isabs(c) else os.path.join(ws, c),
                     os.path.join(ws, "产物", os.path.basename(c))]
            full = next((p for p in cands if os.path.exists(p)), None)
            out.append((c, full))
        return out

    def _completion_gate(self, task: str, text: str) -> str:
        """第一层(确定性):引用的文件在不在 + 基本结构(空文件 / 公众号却给纯 md)。

        只拦明确、客观的问题,近乎零误伤;返回非空=拦下。
        """
        import os
        if not text:
            return ""
        refs = self._referenced_files(text)
        missing = [c for c, f in refs if f is None]
        if missing:
            return ("[交付校验] 你声称已交付,但这些文件在工作区里并不存在:"
                    + "、".join(missing[:5])
                    + "。请真正写到 产物/ 目录(fs.write/对应技能),写完回读确认;做不到就如实说缺口,绝不谎报完成。")
        problems: list[str] = []
        is_wechat = any(k in (task or "") for k in ("公众号", "推文", "微信文章"))
        for c, f in refs:
            try:
                size = os.path.getsize(f)
            except OSError:
                continue
            if size < 20 and not f.lower().endswith((".png", ".jpg", ".jpeg")):
                problems.append(f"{c} 几乎是空的({size} 字节),不像真交付了内容")
                continue
            if is_wechat and f.lower().endswith(".md"):
                try:
                    head = open(f, encoding="utf-8", errors="ignore").read(3000)
                except OSError:
                    head = ""
                if "<section" not in head and "style=" not in head and "<p" not in head:
                    problems.append(f"{c} 还是纯 Markdown;公众号需要内联样式 HTML,请用 wechat.format 生成后再交付")
        if problems:
            return "[交付校验] " + ";".join(problems[:5]) + "。请补正后再给结论。"
        return ""

    def _get_judge_llm(self):
        """质检用的"判断脑":优先角色模型(AGENT_JUDGE_MODEL,默认 reasoner 档),否则用主模型。"""
        if getattr(self, "_judge_llm_cached", "unset") == "unset":
            try:
                from llm.factory import build_role_llm
                self._judge_llm_cached = build_role_llm("judge")
            except Exception:
                self._judge_llm_cached = None
        return self._judge_llm_cached or self.llm

    async def _content_judge(self, task: str, text: str) -> str:
        """第二层(语义):让模型读一遍产物,判断是否真的完成了任务,没完成就指出缺什么。

        判断默认用更会想的"判断脑"(AGENT_JUDGE_MODEL,默认 deepseek-v4-pro/reasoner),
        执行仍用便宜的主模型。最佳努力:未配模型/无产物/调用失败都安静放行。AGENT_CONTENT_JUDGE=0 可关。
        """
        import os
        if os.environ.get("AGENT_CONTENT_JUDGE", "1").strip() == "0" or self.llm is None:
            return ""
        judge_llm = self._get_judge_llm()
        files = [f for _, f in self._referenced_files(text) if f]
        if not files:
            return ""
        blob: list[str] = []
        total = 0
        for f in files[:3]:
            if f.lower().endswith((".png", ".jpg", ".jpeg", ".pdf", ".xlsx", ".docx", ".pptx")):
                blob.append(f"[{os.path.basename(f)}:二进制产物,已生成]")
                continue
            try:
                c = open(f, encoding="utf-8", errors="ignore").read(4000)
            except OSError:
                continue
            blob.append(f"=== {os.path.basename(f)} ===\n{c}")
            total += len(c)
            if total >= 8000:
                break
        if not blob:
            return ""
        from core.types import Message, Role
        prompt = (
            f"任务:{task}\n\n已交付的产物内容:\n" + "\n\n".join(blob)
            + "\n\n请严格判断:这份产物是否真正完成了上述任务?完成就**只回复 OK** 两个字母;"
            "没完成就用一句话指出具体缺什么(如:缺数据来源 / 跑题 / 格式不符 / 内容太单薄)。不要客套、不要复述任务。")
        try:
            step = await judge_llm.next_step(
                [Message(role=Role.SYSTEM, content="你是严格但简洁的交付质检员,只判断产物是否达成任务。"),
                 Message(role=Role.USER, content=prompt)], [], None)
            verdict = (getattr(step, "text", "") or "").strip()
        except Exception:
            return ""
        if not verdict or verdict.upper().replace(".", "").startswith("OK"):
            return ""
        if len(verdict) > 400:   # 判词过长多半是模型跑偏,放行避免误伤
            return ""
        return "[交付校验·内容] 质检发现:" + verdict + " —— 请据此补正产物,或如实说明为何无法满足。"

    def _salvage_partial(self, ctx: Context, max_chars: int = 4000) -> str:
        """步数/预算用尽时,从对话里抢救最近的工具产出与Body text,作为阶段性成果交回。"""
        try:
            msgs = list(ctx.llm_view())
        except Exception:
            return ""
        chunks: list[str] = []
        total = 0
        for m in reversed(msgs):
            role = getattr(getattr(m, "role", None), "value", "") or str(getattr(m, "role", ""))
            if role not in ("tool", "assistant"):
                continue
            content = (getattr(m, "content", "") or "").strip()
            if not content or content.startswith("已停止:"):
                continue
            piece = content[:1500]
            chunks.append(piece)
            total += len(piece)
            if total >= max_chars:
                break
        return "\n---\n".join(reversed(chunks))[:max_chars + 1200]

    def _emit_plan(self, emit, args: dict) -> None:
        """把 plan.update 的入参翻译成右侧 Progress 面板要的 plan_update 事件。"""
        try:
            from capabilities.tools.plan import normalize_steps
            steps = normalize_steps(args.get("steps"))
            if not steps:
                return
            _MAP = {"todo": "pending", "pending": "pending", "doing": "running",
                    "running": "running", "done": "done", "failed": "failed"}
            nodes = [{"id": f"t{i + 1}", "sub_task": s["text"]} for i, s in enumerate(steps)]
            emit(EventType.PLAN_UPDATE, {"type": "plan", "nodes": nodes})
            for i, s in enumerate(steps):
                st = _MAP.get(s["status"], "pending")
                if st != "pending":
                    emit(EventType.PLAN_UPDATE, {"type": "node", "id": f"t{i + 1}", "status": st})
            # 断点续跑:把待办快照落盘,会话中断后可接着干。
            sid = getattr(self, "_session_id", "") or ""
            if sid:
                try:
                    from memory.checkpoint_store import CheckpointStore
                    CheckpointStore().save(sid, steps)
                except Exception:
                    pass
        except Exception:
            pass

    def _charge_input(self, ctx: Context) -> None:
        """估算并计入本轮发送给模型的 input token(全部历史 + 能力清单)。"""
        try:
            parts: list[str] = []
            for m in ctx.llm_view():
                parts.append(str(getattr(m, "content", "") or ""))
                for tc in (getattr(m, "tool_calls", None) or []):
                    parts.append(f"{getattr(tc, 'name', '')}{getattr(tc, 'args', '')}")
            parts.append(json.dumps(
                self.registry.specs_for(getattr(self, "_current_user_text", "")),
                ensure_ascii=False,
            ))
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
            if cap is None or cap.risk != Risk.READ:
                continue
            try:
                # 预取只为"提速开场",本身不能拖慢开场:超 1.5s 就放弃,
                # 让 agent 该调时自己再调,不阻塞首轮响应。
                from governance.gateway import invoke_governed
                result = await asyncio.wait_for(
                    invoke_governed(
                        self.registry,
                        self.policy,
                        CapabilityCall(name=cap.name, args=route.args, intent="skill prefetch"),
                        ctx.identity,
                        ctx,
                    ),
                    timeout=1.5,
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

    def _inject_opening_memory(self, user_text: str, ctx: Context) -> None:
        """统一注入 journal + experience + recall(S23)。"""
        try:
            from memory.inject import build_opening_memory_block
            block = build_opening_memory_block(ctx, user_text)
        except Exception:
            return
        if not block:
            return
        prefixes = ("[上次协作进度", "[过往经验", "[关于主人的已知记忆")
        ctx.messages = [
            m for m in ctx.messages
            if not (m.role == Role.SYSTEM and any(
                (getattr(m, "content", None) or "").startswith(p) for p in prefixes
            ))
        ]
        ctx.add_system(block)

    def _inject_memories(self, user_text: str, ctx: Context) -> None:
        """检索相关长期记忆并注入为瞬时 system 消息(去重,避免反复堆叠)。"""
        mem = getattr(ctx, "longterm", None)
        if mem is None:
            return
        try:
            # 隔离:只检索当前对接/项目 + 全局偏好的记忆,避免跨会话/跨对接串味。
            _scope = getattr(ctx, "mem_scope", None)
            if _scope is None:
                _ch = getattr(getattr(ctx, "identity", None), "channel", "") or ""
                _scope = f"{_ch}|" if _ch else None
            items = mem.retrieve(user_text, k=5, scope=_scope)
        except Exception:
            return
        if not items:
            return
        block = "[关于主人的已知记忆,供参考]\n" + "\n".join(
            f"- [{getattr(it, 'source', 'agent')}] {it.content}" for it in items)
        try:
            from memory.policy import inject_with_budget, INJECT_CHAR_BUDGET
            block = inject_with_budget([block], max_chars=INJECT_CHAR_BUDGET)
        except Exception:
            pass
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
                authority=str(getattr(ctx, "authority", "owner") or "owner"),
                evidence=f"result:{'ok' if ok else 'failed'}",
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

    # 迎合压力信号:主人在诱导附和。命中才注入提醒 → 平时零开销,该提醒时不漏。
    _SYCOPHANCY_CUES = (
        "顺着我说", "顺着我", "你就同意", "就同意吧", "别反驳", "不要反驳",
        "难道不是", "对吧", "对不对", "是不是这样", "你也觉得", "你不觉得",
        "众所周知", "我说得对", "认同我", "附和", "迎合",
    )

    def _inject_anti_sycophancy(self, user_text: str, ctx: Context) -> None:
        """检测"迎合压力"话术 → 作答前注入抗谄媚提醒(零额外推理,机制级兜底)。

        谄媚多发生在主人预设错误前提 + 诱导附和时;此处不替模型判断对错,
        只在该警惕的时刻强制它"先核对前提、错就纠正",把抗谄媚从"提示词劝"变成"触发即提醒"。
        """
        t = user_text or ""
        if not any(cue in t for cue in self._SYCOPHANCY_CUES):
            return
        # 去重:同一轮只注一条
        ctx.messages = [m for m in ctx.messages
                        if not (m.role == Role.SYSTEM and m.content.startswith("[抗谄媚]"))]
        ctx.add_system(
            "[抗谄媚] 主人这句带了诱导你附和的语气(如'顺着我说/对吧/众所周知')。"
            "先独立核对其中预设的事实/前提:若有错,礼貌但明确地先纠正(给出正确事实),再继续;"
            "绝不为讨好而附和明显错误的说法——主人要的是真话。")

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
        try:
            from memory.policy import inject_with_budget, INJECT_CHAR_BUDGET
            block = inject_with_budget([block], max_chars=INJECT_CHAR_BUDGET)
        except Exception:
            pass
        ctx.messages = [m for m in ctx.messages
                        if not (m.role == Role.SYSTEM and m.content.startswith("[过往经验"))]
        ctx.add_system(block)

    def _inject_credentials_manifest(self, ctx: Context) -> None:
        """把 vault 里保存的凭据元信息（不含密钥值）注入 system 消息。

        让 agent 每轮都知道"手里有哪些 key、能做什么"，不再遗忘。
        只注入有描述或权限信息的凭据（纯 name 的不注入，避免干扰）。
        """
        vault = getattr(ctx, "vault", None)
        if vault is None:
            return
        try:
            rows = vault.list()
        except Exception:
            return
        if not rows:
            return
        # 只展示有元信息的条目
        lines: list[str] = []
        for r in rows:
            name = r.get("name", "")
            desc = r.get("description", "").strip()
            scope = r.get("scope", "").strip()
            if not desc and not scope:
                continue   # 没有描述的纯 key，不注入（减少噪音）
            line = f"- {name}"
            if desc:
                line += f"（{desc}）"
            if scope:
                line += f"：{scope}"
            lines.append(line)
        if not lines:
            return
        block = (
            "[可用凭据 — 执行部署/API/登录任务前请优先使用这些已保存的 key，无需再问用户]\n"
            + "\n".join(lines)
            + "\n→ 需要实际密钥值时调用 secret.list 获取名称，再用 secret:<name> 引用。"
        )
        ctx.messages = [m for m in ctx.messages
                        if not (m.role == Role.SYSTEM and m.content.startswith("[可用凭据"))]
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
            try:
                from memory.policy import inject_with_budget, INJECT_CHAR_BUDGET
                briefing = inject_with_budget([briefing], max_chars=INJECT_CHAR_BUDGET)
            except Exception:
                pass
            ctx.add_system(briefing)
