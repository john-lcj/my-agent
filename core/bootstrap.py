"""统一装配(bootstrap)—— 一处构建 Agent + Context + 能力注册表。

server / main / scheduler 之前各自 copy 一套装配逻辑,改一处漏三处。
本模块把"怎么拼一个能跑的 agent"收敛到这里,组合根只负责选 profile 和接线。

Profile 说明:
  interactive  Web/CLI 对话:读写 + 记忆 + skill + 回滚
  external     外部渠道:interactive + 主动通知(notify.*)
  scheduler    定时任务:interactive 但无回滚(无人值守)
  cli          CLI 完整版:interactive + delegate(需传入 worker_registry)
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Optional

from config import Config
from capabilities.base import CapabilityRegistry
from capabilities.tools.fs import ListDir, ReadFile, WriteFile
from capabilities.tools.shell import RunShell
from capabilities.tools.memory import RememberMemory, RecallMemory
from capabilities.tools.program_memory import ProgramList, ProgramRecall, ProgramRemember
from capabilities.tools.web import WebFetch, WebSearch
from core.bus import EventBus
from core.context import Context
from core.loop import Agent
from core.prompts import build_system_prompt
from core.types import Identity
from governance.budget import BudgetGovernor
from governance.engine import DeclarativePolicy
from llm.factory import build_llm
from observability.rollback import RollbackManager
from observability.trace import FileTracer


@dataclass
class AgentBundle:
    """一次装配的产物 —— agent 与其运行所需的上下文/总线/注册表。"""
    agent: Agent
    ctx: Context
    registry: CapabilityRegistry
    bus: EventBus
    rollback: Optional[RollbackManager] = None


def _gui_capable_profiles() -> frozenset[str]:
    """有人值守的对话场景才注册 GUI;定时/外部 webhook 不暴露桌面控制。"""
    return frozenset({"interactive", "cli"})


# 全局附加能力(如启动时连接的 MCP 工具)。在 build_registry 末尾并入每个新建的
# registry,使外部连接器的工具对 agent 可用,且照样走治理。
_EXTRA_CAPABILITIES: list = []


def register_extra_capability(cap) -> None:
    """注册一个全局附加能力,后续每次 build_registry 都会带上它(重名跳过)。"""
    _EXTRA_CAPABILITIES.append(cap)


def build_registry(
    profile: str = "interactive",
    *,
    worker_registry: Any = None,
) -> CapabilityRegistry:
    """按 profile 注册能力 + 加载 skill 插件 + 并入全局附加能力(MCP 等)。"""
    from capabilities.tools.schedule import ScheduleCreate, ScheduleList, ScheduleDelete, ScheduleUpdate, ScheduleRun
    from capabilities.tools.plan import PlanUpdate
    from capabilities.tools.fs_search import FsSearch
    from capabilities.tools.browser import (
        BrowserOpen, BrowserText, BrowserClick, BrowserFill,
        BrowserWait, BrowserScreenshot, BrowserUpload, BrowserDownload,
        BrowserLoginAssist, BrowserClose, BrowserAccessibility, BrowserPreview, BrowserTakeover,
    )
    from capabilities.tools.vision import VisionSee
    from capabilities.tools.http_request import HttpRequest
    from capabilities.tools.secret import SecretSave, SecretList, SecretIssueHandle
    from capabilities.tools.wechat import WechatFormat
    from capabilities.tools.skill_scaffold import SkillScaffold
    from capabilities.tools.multimodal import ImageOCR, ImageGenerate
    from capabilities.tools.monitor import MonitorCreate, MonitorList, MonitorDelete
    from capabilities.tools.goal import GoalSet, GoalList, GoalRemove
    from capabilities.tools.channel import ChannelStatus, ChannelConfigure
    from capabilities.tools.model_key import ModelKeySave, ModelKeyList, ModelKeyClear
    from capabilities.tools.exa_search import ExaSearch
    from capabilities.tools.suggest import SuggestAdd, SuggestList
    from capabilities.tools.git_tool import GitRead, GitCommit
    from capabilities.tools.calendar_tool import CalendarAdd, CalendarList, CalendarRemove
    from capabilities.tools.dev import RunTests
    caps = [ReadFile(), ListDir(), WriteFile(), RunShell(), RunTests(),
            WebSearch(), WebFetch(), FsSearch(),
            RememberMemory(), RecallMemory(),
            ProgramRemember(), ProgramRecall(), ProgramList(),
            ScheduleCreate(), ScheduleList(), ScheduleDelete(), ScheduleUpdate(), ScheduleRun(),
            PlanUpdate(),
            BrowserOpen(), BrowserText(), BrowserClick(), BrowserFill(),
            BrowserWait(), BrowserScreenshot(), BrowserUpload(), BrowserDownload(),
            BrowserLoginAssist(), BrowserClose(), BrowserAccessibility(), BrowserPreview(), BrowserTakeover(),
            VisionSee(), HttpRequest(),
            SecretSave(), SecretList(), SecretIssueHandle(), WechatFormat(), SkillScaffold(),
            ImageOCR(), ImageGenerate(),
            MonitorCreate(), MonitorList(), MonitorDelete(),
            GoalSet(), GoalList(), GoalRemove(),
            ChannelStatus(), ChannelConfigure(),
            ModelKeySave(), ModelKeyList(), ModelKeyClear(),
            ExaSearch(),
            SuggestAdd(), SuggestList(),
            GitRead(), GitCommit(),
            CalendarAdd(), CalendarList(), CalendarRemove()]
    if profile in _gui_capable_profiles():
        from capabilities.gui import GUIControl, GUIObserve
        caps.extend([GUIObserve(), GUIControl()])
    if profile == "external":
        from capabilities.tools.notify import SendEmail
        caps.append(SendEmail())
    # 声明式连接器(connectors/*.json)→ 每个 action 注册成能力(github.list_repos 等)。
    try:
        from capabilities.connector_loader import build_connector_tools
        caps += build_connector_tools()
    except Exception as _ce:
        print(f"[bootstrap] 连接器加载失败(跳过): {_ce}")
    # 多 agent 委托(delegate)已移除:单 agent 架构不再派活给别的 agent。
    registry = CapabilityRegistry(caps)
    from skills.paths import build_skill_registry
    build_skill_registry().load_all_into(registry)
    # 附加能力(MCP 外部工具等):重名跳过,不覆盖内置。
    for cap in _EXTRA_CAPABILITIES:
        try:
            registry.register(cap)
        except ValueError:
            pass
    return registry


def build_agent_bundle(
    identity: Identity,
    *,
    profile: str = "interactive",
    longterm: Any = None,
    persona: Any = None,
    event_sink: Optional[Callable] = None,
    trace_echo: bool = False,
    with_rollback: bool = True,
    worker_registry: Any = None,
    provider: Optional[str] = None,
    model: Optional[str] = None,
    max_cost_usd: Optional[float] = None,
    governance_mode: Optional[str] = None,
    max_steps: Optional[int] = None,
) -> AgentBundle:
    """装配一套完整可运行的 agent。

    event_sink: 通常为 channel.emit,把事件推给 UI/外部渠道。
    with_rollback: 定时任务等无人值守场景可关闭。
    """
    from llm.model_registry import default_model_id, get_model, normalize_model_id

    registry = build_registry(profile, worker_registry=worker_registry)
    model_id = (
        normalize_model_id(model or "")
        or normalize_model_id(provider or "")
        or default_model_id()
    )
    spec = get_model(model_id)
    llm = build_llm(model=model_id)
    budget_provider = spec.provider
    policy = DeclarativePolicy(
        registry,
        Config.POLICY_PATH,
        mode=governance_mode or Config.GOVERNANCE_MODE,
    )
    bus = EventBus()
    # max_steps<=0 视为"无限制"(用极大数,避免下游 min() 逻辑出 0)
    _ms = Config.MAX_STEPS if max_steps is None else max_steps
    if _ms is not None and _ms <= 0:
        _ms = 1_000_000
    budget = BudgetGovernor(
        max_steps=_ms,
        max_cost_usd=max_cost_usd if max_cost_usd is not None else Config.MAX_COST_USD,
        provider=budget_provider,
    )

    ctx = Context(identity=identity)
    ctx.add_system(build_system_prompt(registry.specs(), persona))
    # 邮件等外部渠道:追加"纯文本自然段"排版指引,避免 Markdown 符号原样漏进邮件。
    if profile == "external":
        from core.prompts import email_style_block
        ctx.add_system(email_style_block())
    if longterm is not None:
        ctx.longterm = longterm
        # 偏好注入:persona 管恒定人格,长期记忆里的偏好管动态认知,两者叠加。
        from memory.preference_miner import format_preference_block
        pref_block = format_preference_block(longterm)
        if pref_block:
            ctx.add_system(pref_block)
    from memory.program_store import ProgramMemoryStore
    ctx.program = ProgramMemoryStore(db_path=f"{Config.LOG_DIR}/program_memory.db")
    # 凭据保险库:加密存登录信息,供 secret.* 与 browser.fill 的 secret: 解引用。
    try:
        from memory.secrets_vault import SecretsVault
        ctx.vault = SecretsVault(db_path=f"{Config.LOG_DIR}/vault.db",
                                 key_file=f"{Config.LOG_DIR}/.vault_key")
        from governance.secret_broker import SecretBroker
        ctx.secret_broker = SecretBroker(ctx.vault)
    except Exception as _e:
        ctx.vault = None
        ctx.secret_broker = None
        print(f"[bootstrap] 凭据保险库初始化失败(降级为不可用): {_e}")
    from memory.monitor_store import MonitorStore
    ctx.monitors = MonitorStore(path=f"{Config.LOG_DIR}/monitors.json")
    from memory.goals_store import GoalsStore
    ctx.goals = GoalsStore(path=f"{Config.LOG_DIR}/goals.json")
    from memory.suggestions_store import SuggestionsStore
    ctx.suggestions = SuggestionsStore(path=f"{Config.LOG_DIR}/suggestions.json")

    tracer = FileTracer(log_dir=Config.LOG_DIR, echo=trace_echo)
    bus.subscribe(tracer.log)
    if event_sink is not None:
        bus.subscribe(event_sink)

    rollback = RollbackManager(snapshot_dir=f"{Config.LOG_DIR}/snapshots") if with_rollback else None
    summarizer = getattr(llm, "summarize", None)
    agent = Agent(
        llm=llm, registry=registry, policy=policy, bus=bus,
        budget=budget, rollback=rollback, summarizer=summarizer,
    )
    return AgentBundle(agent=agent, ctx=ctx, registry=registry, bus=bus, rollback=rollback)
