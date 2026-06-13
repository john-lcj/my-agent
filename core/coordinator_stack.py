"""Coordinator 装配 —— main / server 共用,避免 Web 与 CLI 行为分叉。"""
from __future__ import annotations

from typing import Any, Callable, Optional

from agents.coordinator import Coordinator
from agents.registry import AgentRegistry
from agents.worker import WorkerFactory
from config import Config
from core.bootstrap import AgentBundle, build_agent_bundle
from core.types import Identity
from governance.engine import DeclarativePolicy
from governance.resource_lock import ResourceLock
from llm.factory import build_llm


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
    roster_path: str = "agents/roster",
) -> tuple[Coordinator, AgentBundle]:
    """装配 AgentBundle + Coordinator(含 roster worker;Captain 步数用尽后升级专家)。"""
    resource_lock = ResourceLock()
    worker_registry = AgentRegistry()

    bundle = build_agent_bundle(
        identity,
        profile=profile,
        longterm=longterm,
        persona=persona,
        event_sink=event_sink,
        trace_echo=trace_echo,
        with_rollback=with_rollback,
        worker_registry=worker_registry,
        provider=provider,
        model=model,
        max_cost_usd=max_cost_usd,
        governance_mode=governance_mode,
    )

    from agents.dispatcher import AutoDispatcher
    from agents.graph_dispatcher import GraphDispatcher
    from llm.model_registry import default_model_id, get_model, normalize_model_id

    mode = governance_mode or Config.GOVERNANCE_MODE
    model_id = (
        normalize_model_id(model or "")
        or normalize_model_id(provider or "")
        or default_model_id()
    )
    prov = get_model(model_id).provider
    factory = WorkerFactory(
        base_registry=bundle.registry,
        base_policy_cls=lambda reg: DeclarativePolicy(reg, Config.POLICY_PATH, mode=mode),
        base_llm_factory=build_llm,
        resource_lock=resource_lock,
        default_model=model_id,
    )
    worker_registry.load_from_roster(roster_path, factory)

    coordinator = Coordinator(
        main_agent=bundle.agent,
        worker_registry=worker_registry,
        resource_lock=resource_lock,
        bus=bundle.bus,
        dispatcher=AutoDispatcher(build_llm(model=model_id)),
        graph_dispatcher=GraphDispatcher(build_llm(model=model_id)),
    )
    return coordinator, bundle
