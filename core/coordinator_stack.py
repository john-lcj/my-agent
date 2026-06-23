"""Agent 装配 —— main / server / 渠道共用。

架构:**单 agent + 待办清单 + 顺序执行**,不再有多 agent 编排(DAG/worker/roster/圆桌已移除)。
返回 (agent, bundle):agent 即 bundle.agent(Captain),与旧调用 `coordinator.run(task, ctx, confirm)`
完全兼容(Agent.run 同签名),所以上层无需改动。
"""
from __future__ import annotations

from typing import Any, Callable, Optional

from core.bootstrap import AgentBundle, build_agent_bundle
from core.types import Identity


def build_coordinator_stack(
    identity: Identity,
    *,
    profile: str = "interactive",
    longterm: Any = None,
    persona: Any = None,
    event_sink: Optional[Callable] = None,
    trace_echo: bool = False,
    with_rollback: bool = True,
    provider: Optional[str] = None,
    model: Optional[str] = None,
    max_cost_usd: Optional[float] = None,
    governance_mode: Optional[str] = None,
    max_steps: Optional[int] = None,
    roster_path: str = "agents/roster",   # 兼容旧签名;已不使用
) -> tuple[Any, AgentBundle]:
    bundle = build_agent_bundle(
        identity,
        profile=profile,
        longterm=longterm,
        persona=persona,
        event_sink=event_sink,
        trace_echo=trace_echo,
        with_rollback=with_rollback,
        provider=provider,
        model=model,
        max_cost_usd=max_cost_usd,
        governance_mode=governance_mode,
        max_steps=max_steps,
    )
    # bundle.agent 就是单体 Captain;直接当 coordinator 用(.run 同签名)。
    return bundle.agent, bundle
