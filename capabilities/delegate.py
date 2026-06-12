"""委托子 agent —— "调用另一个 agent"本身是一种 Capability,走统一治理管线。

这正是统一能力层的威力:多 agent 协同不需要在主循环里开特例。
委托会触发目标 agent 跑一轮 run,结果作为工具返回值回喂给发起方。

安全约束:
- 发起方只能委托注册在 AgentRegistry 里的目标。
- 委托深度受 max_depth 限制(防止 A→B→A 死循环)。
- 目标 agent 的 budget 独立计算,但消耗汇总到父级(防止烧爆额度)。
"""
from __future__ import annotations

import contextvars
from typing import Any

from core.types import CapabilityResult, Risk

# 委托深度跟随调用链(asyncio task)而非实例:并发委托互不干扰,A→B→A 仍受限。
_delegate_depth: contextvars.ContextVar[int] = contextvars.ContextVar(
    "delegate_depth", default=0,
)


class DelegateToAgent:
    name = "agent.delegate"
    risk = Risk.WRITE
    description = "把一个子任务委托给另一个具名 agent 执行,并取回其结果。"
    schema = {
        "type": "object",
        "properties": {
            "agent": {"type": "string", "description": "目标 agent 名称"},
            "task": {"type": "string", "description": "交给它的任务描述"},
        },
        "required": ["agent", "task"],
    }

    def __init__(self, agent_registry, max_depth: int = 3) -> None:
        self._registry = agent_registry
        self.max_depth = max_depth

    async def invoke(self, args: dict, ctx: Any) -> CapabilityResult:
        target_name = str(args.get("agent", "")).strip()
        task = str(args.get("task", "")).strip()

        if not target_name or not task:
            return CapabilityResult(ok=False, error="缺少参数 agent 或 task")
        depth = _delegate_depth.get()
        if depth >= self.max_depth:
            return CapabilityResult(
                ok=False,
                error=f"委托深度已达上限({self.max_depth}),拒绝继续委托防止死循环",
            )
        target = self._registry.get(target_name)
        if target is None:
            available = ", ".join(self._registry.names()) or "(无)"
            return CapabilityResult(
                ok=False,
                error=f"未找到 agent '{target_name}'。可用:{available}",
            )

        # 优先复用已注册的 WorkerAgent(有自己的 auto_confirm 策略)。
        # 若 target 是 WorkerAgent,直接调用 run;若是旧式 Agent,构建临时 Context。
        from agents.worker import WorkerAgent as _WorkerAgent

        token = _delegate_depth.set(depth + 1)
        try:
            if isinstance(target, _WorkerAgent):
                # WorkerAgent 已含 auto_confirm 策略,直接运行
                result_text = await target.run(task)
            else:
                from core.context import Context
                from core.types import Identity
                sub_ctx = Context(identity=Identity(
                    subject_id=getattr(ctx, "identity", None) and ctx.identity.subject_id or "delegate",
                    agent_name=target_name,
                    channel="delegate",
                ))
                async def no_confirm(call, decision, reason=""):
                    return False
                result_text = await target.run(task, sub_ctx, no_confirm)
        except Exception as e:
            return CapabilityResult(ok=False, error=f"子 agent 异常:{e}")
        finally:
            _delegate_depth.reset(token)

        return CapabilityResult(ok=True, output=result_text)
