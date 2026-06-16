"""WorkerAgent —— 有工具调用能力的专家 agent。

与 ChatAgent(只参与讨论)不同,WorkerAgent 包装了完整的 Agent(主循环),
拥有自己的:
  - 能力子集(由 AgentSpec.capabilities 白名单决定)
  - LLM(可覆盖全局配置)
  - 独立 Budget(超步数自动停止)
  - auto_confirm 标志(由 Dispatcher 分配的任务自动放行写操作)

多个 WorkerAgent 协作时通过 ResourceLock 防止写冲突。
"""
from __future__ import annotations

import asyncio
import re
from typing import Any, Optional

from core.bus import EventBus
from core.context import Context
from core.loop import Agent, ConfirmFn
from core.types import CapabilityCall, Decision, Identity
from agents.spec import AgentSpec
from governance.budget import BudgetGovernor


# 无人值守专家即便 auto_confirm,也不能自动批准的高危子集。
# 删除/移动/装依赖/提权/写系统路径等危险 shell,以及控屏与付费。
_HIGH_RISK_SHELL = re.compile(
    r"\brm\b|\bmv\b|\bdd\b|\bmkfs\b|\bshred\b|\bchmod\b|\bchown\b|\bsudo\b"
    r"|\b(pip|pip3|npm|yarn|pnpm|brew|apt|apt-get|gem|cargo)\s+(install|add|i)\b"
    r"|>\s*/(etc|usr|bin|sbin|dev|boot|sys|proc|lib|var)\b",
    re.I,
)


def resolve_worker_model(name: str, spec_llm: str, default_model: str) -> str:
    """按权限档分模型:优先级 环境变量 AGENT_<NAME>_MODEL > YAML 的 llm > 全局默认。
    例:AGENT_EXECUTOR_MODEL=deepseek-v4-pro 让可写档用强模型,researcher 仍用便宜的。
    返回"原始模型串",由调用方再 normalize。"""
    import os
    env_model = os.environ.get(f"AGENT_{name.upper()}_MODEL", "").strip()
    return env_model or (spec_llm or "").strip() or (default_model or "").strip()


def _is_high_risk_unattended(call: CapabilityCall) -> bool:
    """该调用是否属于"无人值守也不应自动放行"的高危子集。"""
    if call.name.startswith("gui.") or call.name.startswith("payment."):
        return True
    if call.name == "shell.run":
        return bool(_HIGH_RISK_SHELL.search(str(call.args.get("command", ""))))
    return False


class WorkerAgent:
    """能干活的专家 agent。由 AgentSpec 描述,由 WorkerFactory 构建。"""

    def __init__(
        self,
        spec: AgentSpec,
        agent: Agent,
        resource_lock=None,
    ) -> None:
        self.spec = spec
        self.name = spec.name
        self.role = spec.role
        self.description = spec.description
        self._agent = agent
        self._lock = resource_lock

    async def run(self, task: str, ctx: Optional[Context] = None, confirm: Optional[ConfirmFn] = None) -> str:
        """执行一个任务,返回文字结果。"""
        if ctx is None:
            # roles=专家名:治理白名单按专家名配置(policy.yaml capability_whitelist),
            # 每个专家的权限是一条明确的声明,而不是 prompt 约定。
            ctx = Context(identity=Identity(
                subject_id="coordinator",
                agent_name=self.name,
                channel="internal",
                roles=(self.name,),
            ))
            from core.prompts import build_system_prompt
            ctx.add_system(
                self.spec.system_prompt or
                build_system_prompt(self._agent.registry.specs())
            )

        if confirm is None:
            confirm = self._make_confirm()

        return await self._agent.run(task, ctx, confirm)

    def _make_confirm(self) -> ConfirmFn:
        """根据 auto_confirm 决定确认策略。

        注意:专家在无人值守下执行,没有真人可以应答确认。因此:
        - auto_confirm=True:放手写工作区,但对「高危子集」仍然自动**拒绝**
          (危险 shell、控屏、付费),避免无人确认地删文件/装依赖/控制屏幕。
          硬边界 BLOCK 仍由治理层先行拦截,这里是第二道纵深防御。
        - auto_confirm=False:一律拒绝,专家退化为只读/搜索。
        """
        if self.spec.auto_confirm:
            async def guarded_yes(call: CapabilityCall, decision: Decision, reason: str = "") -> bool:
                return not _is_high_risk_unattended(call)
            return guarded_yes
        else:
            async def auto_no(call: CapabilityCall, decision: Decision, reason: str = "") -> bool:
                return False
            return auto_no

    # ChatAgent 兼容接口(圆桌/流水线可以混用)
    async def step(self, task: str, conversation: list) -> object:
        from core.types import Message, Role
        result = await self.run(task)
        return Message(role=Role.ASSISTANT, content=result, name=self.name)


class WorkerFactory:
    """把 AgentSpec 实例化为 WorkerAgent。
    
    与主 agent 共用同一套 LLM/策略基础设施,但每个 worker 有独立的:
    - 能力注册表(只含白名单内的能力)
    - Budget
    - 系统 prompt
    """

    def __init__(
        self,
        base_registry,
        base_policy_cls,
        base_llm_factory,
        resource_lock=None,
        default_model: str | None = None,
    ) -> None:
        self._base_registry = base_registry
        self._policy_cls = base_policy_cls
        self._llm_factory = base_llm_factory
        self._lock = resource_lock
        self._default_model = default_model

    def build(self, spec: AgentSpec) -> WorkerAgent:
        from capabilities.base import CapabilityRegistry
        from governance.engine import DeclarativePolicy
        from config import Config

        # 过滤能力:只保留白名单前缀匹配的
        all_caps = self._base_registry.capabilities()
        if spec.capabilities:
            filtered = [
                c for c in all_caps
                if any(c.name.startswith(prefix) for prefix in spec.capabilities)
            ]
        else:
            filtered = list(all_caps)

        registry = CapabilityRegistry(filtered)
        from llm.model_registry import default_model_id, get_model, normalize_model_id

        # 按权限档分模型:AGENT_<NAME>_MODEL > YAML llm > 全局默认
        chosen = resolve_worker_model(spec.name, spec.llm, self._default_model or "")
        model_id = normalize_model_id(chosen or "") or default_model_id()
        spec_meta = get_model(model_id)
        llm = self._llm_factory(model=model_id)
        policy = self._policy_cls(registry)
        bus = EventBus()
        budget = BudgetGovernor(
            max_steps=spec.max_steps or Config.MAX_STEPS,
            max_cost_usd=Config.MAX_COST_USD,
            provider=spec_meta.provider,
        )

        # Python 扩展类优先
        agent_obj = Agent(
            llm=llm,
            registry=registry,
            policy=policy,
            bus=bus,
            budget=budget,
            summarizer=getattr(llm, "summarize", None),
        )

        if spec.python_class is not None:
            return spec.python_class(spec=spec, agent=agent_obj, resource_lock=self._lock)
        return WorkerAgent(spec=spec, agent=agent_obj, resource_lock=self._lock)
