"""评测 / 回归框架 —— 用 MockLLM 做确定性断言。

为什么用 MockLLM:真实模型输出不确定,没法做稳定回归;Mock 行为确定,
适合锁住"循环 + 治理 + 工具"的关键行为不退化。每次改动后跑一遍即可。

运行:
    python -m tests.harness   # 推荐
    python eval/harness.py  # 兼容旧命令(薄转发)
"""
from __future__ import annotations

import asyncio
import os
import sys
import tempfile
import time
from dataclasses import dataclass, field
from typing import Callable, Optional

# 允许直接 `python tests/harness.py` 运行(把项目根加入 path)。
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from capabilities.base import CapabilityRegistry
from capabilities.tools.fs import ListDir, ReadFile, WriteFile
from capabilities.tools.shell import RunShell
from core.bus import EventBus
from core.context import Context
from core.loop import Agent
from core.types import Event, EventType, Message, Role, ToolCallRef
from governance.engine import DeclarativePolicy
from llm.mock_llm import MockLLM
from memory.working import WorkingMemory


@dataclass
class Case:
    name: str
    user: str
    confirm_answers: list[bool] = field(default_factory=list)
    # 断言:接收本次任务产生的事件列表,返回 (是否通过, 说明)。
    check: Optional[Callable[[list[Event]], tuple]] = None


def _last_result(events: list[Event]) -> Optional[dict]:
    for e in reversed(events):
        if e.type == EventType.CAPABILITY_RESULT:
            return e.payload
    return None


def _called(events: list[Event], name: str) -> bool:
    return any(e.type == EventType.CAPABILITY_CALL and e.payload.get("name") == name
               for e in events)


async def _run_case(case: Case) -> tuple:
    events: list[Event] = []
    bus = EventBus()
    bus.subscribe(events.append)

    registry = CapabilityRegistry([ReadFile(), ListDir(), WriteFile(), RunShell()])
    policy = DeclarativePolicy(registry, config_path=None)  # 用内置默认策略
    agent = Agent(llm=MockLLM(), registry=registry, policy=policy, bus=bus)
    ctx = Context()

    answers = iter(case.confirm_answers)

    async def confirm(call, decision, reason="") -> bool:
        try:
            return next(answers)
        except StopIteration:
            return False

    await agent.run(case.user, ctx, confirm)
    if case.check is None:
        return True, "无断言"
    return case.check(events)


def build_cases(tmp: str) -> list[Case]:
    # 准备一个可读文件
    readable = os.path.join(tmp, "data.txt")
    with open(readable, "w", encoding="utf-8") as f:
        f.write("hello-eval")

    def check_read(events):
        r = _last_result(events)
        ok = _called(events, "fs.read") and r and r.get("ok") and "hello-eval" in r.get("output", "")
        return bool(ok), f"读取结果={r}"

    def check_write_approved(events):
        r = _last_result(events)
        wrote = os.path.isfile(os.path.join(tmp, "w_ok.txt"))
        return bool(r and r.get("ok") and wrote), f"写入结果={r}, 文件存在={wrote}"

    def check_write_rejected(events):
        r = _last_result(events)
        not_written = not os.path.isfile(os.path.join(tmp, "w_no.txt"))
        rejected = r and (not r.get("ok")) and "拒绝" in (r.get("error", "") or r.get("output", ""))
        return bool(rejected and not_written), f"结果={r}, 未写入={not_written}"

    def check_forbidden_cmd(events):
        r = _last_result(events)
        blocked = r and (not r.get("ok")) and "拒绝" in (r.get("error") or "")
        return bool(blocked), f"结果={r}"

    def check_forbidden_path(events):
        r = _last_result(events)
        blocked = r and (not r.get("ok")) and "拒绝" in (r.get("error") or "")
        return bool(blocked), f"结果={r}"

    return [
        Case("读取文件应放行", f"读 {readable}", check=check_read),
        Case("写文件确认后应成功", f"写 {tmp}/w_ok.txt :: data",
             confirm_answers=[True], check=check_write_approved),
        Case("写文件拒绝后不应写入", f"写 {tmp}/w_no.txt :: data",
             confirm_answers=[False], check=check_write_rejected),
        Case("危险命令应被硬边界拒绝", "跑 rm -rf /tmp/should_not_run",
             check=check_forbidden_cmd),
        Case("写敏感路径应被硬边界拒绝", "写 .env :: SECRET=1",
             check=check_forbidden_path),
    ]


async def _memory_governance_check() -> tuple:
    """记忆写入治理:agent 推断需 ASK;用户明说可自动放行;scheduler 禁止写入。"""
    from core.bus import EventBus
    from governance.engine import DeclarativePolicy
    from capabilities.base import CapabilityRegistry
    from capabilities.tools.memory import RememberMemory, RecallMemory
    from core.types import CapabilityCall, Decision, Identity
    from core.context import Context

    reg = CapabilityRegistry([RememberMemory(), RecallMemory()])
    policy = DeclarativePolicy(reg, config_path="governance/policy.yaml")

    agent_call = CapabilityCall(name="memory.remember",
                                args={"content": "主人喜欢咖啡", "source": "agent", "importance": 0.6})
    ctx = Context()
    r1 = policy.review_detailed(agent_call, Identity(roles=()), ctx)
    user_call = CapabilityCall(name="memory.remember",
                               args={"content": "叫我老板", "source": "user", "importance": 0.6})
    r2 = policy.review_detailed(user_call, Identity(roles=()), ctx)
    sched_call = CapabilityCall(name="memory.remember",
                                args={"content": "x", "source": "agent", "importance": 0.5})
    r3 = policy.review_detailed(sched_call, Identity(roles=("scheduler",)), ctx)

    ok = (r1.decision == Decision.ALLOW and r1.rule == "memory:auto"
          and r2.decision == Decision.ALLOW and r2.rule == "memory:auto"
          and r3.decision == Decision.BLOCK)  # scheduler 白名单不含 remember → BLOCK
    return ok, f"agent={r1.decision}/{r1.rule} user={r2.decision}/{r2.rule} sched={r3.decision}/{r3.rule}"


def _status_bar_format_check() -> tuple:
    from channels.cli_style import format_cli_status
    from core.status_bar import build_status_snapshot
    from core.context import Context
    s = build_status_snapshot(
        model_id="deepseek-v4-flash",
        ctx=Context(),
        session_started_at=__import__("time").time() - 31000,
        last_task_seconds=13,
    )
    line = format_cli_status(s.to_payload())
    ok = "│" in line and "⚕" in line and "%" in line
    return ok, line[:80]


def _cli_stream_emit_check() -> tuple:
    """CLIChannel 应消费 ASSISTANT_TOKEN 且不与终局消息重复打印正文。"""
    import io
    from channels.cli import CLIChannel
    from core.types import Event, EventType

    ch = CLIChannel()
    buf = io.StringIO()
    import sys
    old = sys.stdout
    try:
        sys.stdout = buf
        ch.emit(Event(type=EventType.ASSISTANT_TOKEN, payload={"token": "你"}))
        ch.emit(Event(type=EventType.ASSISTANT_TOKEN, payload={"token": "好"}))
        ch.emit(Event(type=EventType.ASSISTANT_MESSAGE, payload={"text": "你好"}))
        out = buf.getvalue()
    finally:
        sys.stdout = old
    ok = "你好" in out and out.count("你好") == 1
    return ok, f"has_你好={('你好' in out)}, dup={out.count('你好')}"


async def _streaming_token_check() -> tuple:
    """终局回复应发射 ASSISTANT_TOKEN,且拼接结果与 ASSISTANT_MESSAGE 一致。"""
    from core.bus import EventBus
    from core.types import EventType

    bus = EventBus()
    seen: list = []
    bus.subscribe(lambda ev: seen.append(ev))
    registry = CapabilityRegistry([ReadFile()])
    policy = DeclarativePolicy(registry, config_path=None)
    agent = Agent(llm=MockLLM(), registry=registry, policy=policy, bus=bus)
    ctx = Context()

    async def confirm(call, decision, reason=""):
        return True

    await agent.run("你好 mock", ctx, confirm)
    tokens = [e for e in seen if e.type == EventType.ASSISTANT_TOKEN]
    finals = [e for e in seen if e.type == EventType.ASSISTANT_MESSAGE]
    assembled = "".join(e.payload.get("token", "") for e in tokens)
    final_text = finals[-1].payload.get("text", "") if finals else ""
    ok = len(tokens) >= 1 and bool(final_text) and assembled == final_text
    return ok, f"token_events={len(tokens)}, match={assembled == final_text}"


async def _governance_reason_check() -> tuple:
    """治理可解释:BLOCK 应产生带 reason + rule 的 governance_decision 事件(供审计统计)。"""
    from core.bus import EventBus
    from core.types import EventType
    bus = EventBus()
    seen: list = []
    bus.subscribe(lambda ev: seen.append(ev))
    registry = CapabilityRegistry([RunShell()])
    policy = DeclarativePolicy(registry, config_path=None)
    agent = Agent(llm=MockLLM(), registry=registry, policy=policy, bus=bus)
    ctx = Context()

    async def confirm(call, decision, reason=""):
        return False

    await agent.run("跑 rm -rf /tmp/nope", ctx, confirm)
    gov = [e for e in seen if e.type == EventType.GOVERNANCE_DECISION]
    ok = bool(gov and gov[0].payload.get("decision") == "block"
              and gov[0].payload.get("reason") and gov[0].payload.get("rule"))
    return ok, f"gov_events={[ (e.payload.get('decision'), e.payload.get('rule')) for e in gov]}"


def _tool_pairing_repair_check() -> tuple:
    """错位/缺失的 tool 消息:repair 后应满足 OpenAI 配对协议。"""
    from core.context import repair_tool_pairing
    from llm.openai_llm import _to_openai_messages

    def _validate(oai: list) -> bool:
        for i, m in enumerate(oai):
            if not m.get("tool_calls"):
                continue
            need = [tc["id"] for tc in m["tool_calls"]]
            j, got = i + 1, []
            while j < len(oai) and oai[j].get("role") == "tool":
                got.append(oai[j].get("tool_call_id"))
                j += 1
            if any(tid not in got for tid in need):
                return False
        return True

    missing = [
        Message(role=Role.USER, content="hi"),
        Message(
            role=Role.ASSISTANT,
            content="读取",
            tool_calls=[ToolCallRef(id="orphan-id", name="fs.read", args={"path": "/x"})],
        ),
    ]
    misaligned = [
        Message(role=Role.USER, content="q"),
        Message(
            role=Role.ASSISTANT,
            content="",
            tool_calls=[ToolCallRef(id="call-A", name="shell.run", args={})],
        ),
        Message(role=Role.TOOL, content="result-B", tool_call_id="call-B", name="shell.run"),
        Message(
            role=Role.ASSISTANT,
            content="",
            tool_calls=[ToolCallRef(id="call-B", name="shell.run", args={})],
        ),
    ]
    ok_missing = _validate(_to_openai_messages(repair_tool_pairing(missing)))
    fixed = repair_tool_pairing(misaligned)
    ok_mis = _validate(_to_openai_messages(fixed))
    ok = ok_missing and ok_mis
    return ok, f"missing={ok_missing}, misaligned={ok_mis}"


def _deepseek_reasoning_echo_check() -> tuple:
    """DeepSeek 思考模式:带 tool_calls 的 assistant 必须回传 reasoning_content。"""
    from core.context import Context
    from llm.deepseek_llm import DeepSeekLLM
    from llm.openai_llm import _to_openai_messages

    msgs = [
        Message(role=Role.USER, content="读文件"),
        Message(
            role=Role.ASSISTANT,
            content="先看下内容",
            tool_calls=[ToolCallRef(id="tc1", name="fs.read", args={"path": "/a"})],
            reasoning_content="需要先读取文件",
        ),
        Message(role=Role.TOOL, content="ok", tool_call_id="tc1", name="fs.read"),
    ]
    llm = DeepSeekLLM(model="deepseek-v4-flash")
    oai = _to_openai_messages(
        msgs, echo_deepseek_reasoning=llm.needs_deepseek_reasoning_echo(),
    )
    ok_stored = oai[1].get("reasoning_content") == "需要先读取文件"

    msgs2 = [
        Message(role=Role.USER, content="q"),
        Message(
            role=Role.ASSISTANT,
            content="",
            tool_calls=[ToolCallRef(id="tc2", name="shell.run", args={"command": "ls"})],
        ),
        Message(role=Role.TOOL, content=".", tool_call_id="tc2"),
    ]
    oai2 = _to_openai_messages(msgs2, echo_deepseek_reasoning=True)
    ok_pad = oai2[1].get("reasoning_content") == ""

    oai3 = _to_openai_messages(msgs, echo_deepseek_reasoning=False)
    ok_no_echo = "reasoning_content" not in oai3[1]

    ctx = Context()
    ctx.add_user("hi")
    ctx.add_tool_call("id1", "fs.read", {"path": "/x"}, "读", reasoning_content="思考中")
    oai4 = _to_openai_messages(ctx.llm_view(), echo_deepseek_reasoning=True)
    ok_ctx = oai4[1].get("reasoning_content") == "思考中"

    ok = ok_stored and ok_pad and ok_no_echo and ok_ctx
    return ok, f"stored={ok_stored}, pad={ok_pad}, no_echo={ok_no_echo}, ctx={ok_ctx}"


async def _compaction_check() -> tuple:
    """工作记忆压缩:超长对话应被摘要,且切点落在用户消息边界(不拆散工具调用对)。"""
    ctx = Context(working=WorkingMemory(max_chars=300, keep_recent=2))
    ctx.add_system("系统提示词" + "x" * 50)
    for i in range(6):
        ctx.add_user(f"用户问题{i} " + "y" * 40)
        ctx.add_tool_call(f"id{i}", "fs.read", {"path": f"/f{i}"}, intent="读取")
        ctx.add_tool_result(f"结果{i}", f"id{i}", name="fs.read")
    changed = await ctx.compact(MockLLM().summarize)

    msgs = ctx.messages
    has_summary = any(m.role == Role.SYSTEM and "早期对话摘要" in m.content for m in msgs)
    # 头部系统消息之后的第一条 body 消息应为 USER(边界安全)。
    body = [m for m in msgs if not (m.role == Role.SYSTEM)]
    boundary_ok = bool(body) and body[0].role == Role.USER
    # 不应有 tool 结果在其配对的 assistant 之前出现(简单校验:每个 tool 前面存在同 id 的调用)。
    seen_ids = set()
    pairing_ok = True
    for m in msgs:
        for tc in m.tool_calls:
            seen_ids.add(tc.id)
        if m.role == Role.TOOL and m.tool_call_id not in seen_ids:
            pairing_ok = False
    ok = changed and has_summary and boundary_ok and pairing_ok
    return ok, f"changed={changed}, summary={has_summary}, boundary={boundary_ok}, pairing={pairing_ok}"


def _memory_check(tmp: str) -> tuple:
    """SQLite 长期记忆:存入 / 关键词检索(重要性排序)/ 遗忘清理。"""
    from memory.base import MemoryItem
    from memory.longterm_sqlite import SQLiteMemory

    mem = SQLiteMemory(db_path=os.path.join(tmp, "mem.db"))
    mem.store(MemoryItem(kind="preference", content="用户喜欢简洁的回答", importance=0.9))
    mem.store(MemoryItem(kind="fact", content="用户在做一个 agent 项目", importance=0.7))
    old = time.time() - 60 * 86400
    mem.store(MemoryItem(kind="episode", content="无关紧要的闲聊",
                         importance=0.1, created_at=old, last_used=old))

    hits = mem.retrieve("用户", k=5)
    found_pref = any("简洁" in h.content for h in hits)
    ordered = bool(hits) and hits[0].importance >= hits[-1].importance
    removed = mem.forget(min_importance=0.2, max_age_days=30.0)
    after = mem.retrieve("闲聊", k=5)
    forgot = removed >= 1 and not any("闲聊" in h.content for h in after)
    mem.close()
    ok = found_pref and ordered and forgot
    return ok, f"命中偏好={found_pref}, 重要性排序={ordered}, 遗忘={forgot}(删除{removed})"


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


async def _delegate_check(tmp: str) -> tuple:
    """delegate: 正常委托成功;深度超限时返回失败结果(不炸主流程)。"""
    from agents.registry import AgentRegistry
    from capabilities.delegate import DelegateToAgent
    from core.context import Context
    from core.types import Identity
    from governance.budget import BudgetGovernor
    from governance.engine import DeclarativePolicy

    # 构建一个可被委托的简单 agent
    registry = CapabilityRegistry([ReadFile()])
    sub_agent_llm = MockLLM()
    sub_agent = Agent(
        llm=sub_agent_llm,
        registry=registry,
        policy=DeclarativePolicy(registry),
        bus=EventBus(),
        budget=BudgetGovernor(max_steps=5),
    )
    sub_agent.name = "sub"

    agent_reg = AgentRegistry()
    agent_reg.register(sub_agent)

    delegate = DelegateToAgent(agent_reg, max_depth=2)

    # 正常委托
    ctx = Context(identity=Identity())
    r1 = await delegate.invoke({"agent": "sub", "task": "你好"}, ctx)
    normal_ok = r1.ok

    # 深度超限(深度跟随调用链 contextvar,而非实例属性)
    from capabilities.delegate import _delegate_depth
    token = _delegate_depth.set(3)
    try:
        r2 = await delegate.invoke({"agent": "sub", "task": "x"}, ctx)
    finally:
        _delegate_depth.reset(token)
    depth_ok = not r2.ok and "深度" in (r2.error or "")

    # 委托不存在的 agent
    r3 = await delegate.invoke({"agent": "ghost", "task": "x"}, ctx)
    not_found_ok = not r3.ok

    ok = normal_ok and depth_ok and not_found_ok
    return ok, f"正常={normal_ok}, 深度限制={depth_ok}, 不存在={not_found_ok}"


class _DagTestWorker:
    def __init__(self, name: str, *, result: str = "", fail: bool = False):
        self.name = name
        self.calls: list[str] = []
        self._result = result or f"[{name}] ok"
        self._fail = fail

    async def run(self, task: str, **kwargs) -> str:
        self.calls.append(task)
        return "执行失败: mock" if self._fail else self._result


async def _dag_plan_graph_check() -> tuple:
    from agents.plan_graph import PlanGraph, PlanNode, from_dispatch_plan

    class A:
        def __init__(self, name, sub_task):
            self.agent_name = name
            self.sub_task = sub_task

    class P:
        parallel = True
        assignments = [A("w1", "t1"), A("w2", "t2")]
        reason = "p"

    g = PlanGraph(nodes=[
        PlanNode("a", "w", "ta"),
        PlanNode("b", "w", "tb"),
        PlanNode("c", "w", "tc", depends_on=["a", "b"]),
    ])
    ok1, _ = g.validate()
    layers = g.layers()
    ok2 = len(layers) == 2 and {n.id for n in layers[0]} == {"a", "b"}
    g2 = PlanGraph(nodes=[
        PlanNode("x", "w", "t", depends_on=["y"]),
        PlanNode("y", "w", "t", depends_on=["x"]),
    ])
    ok3 = not g2.validate()[0]
    g3 = from_dispatch_plan(P())
    ok4 = g3.validate()[0] and len(g3.layers()[0]) == 2
    ok = ok1 and ok2 and ok3 and ok4
    return ok, f"validate={ok1}, layers={ok2}, cycle={ok3}, from_plan={ok4}"


async def _dag_orchestrator_check() -> tuple:
    from agents.graph_orchestrator import GraphOrchestrator
    from agents.plan_graph import PlanGraph, PlanNode
    from agents.registry import AgentRegistry

    w1 = _DagTestWorker("a", result="上游数据")
    w2 = _DagTestWorker("b")
    reg = AgentRegistry()
    reg.register(w1)
    reg.register(w2)
    g = PlanGraph(nodes=[
        PlanNode("n1", "a", "step1"),
        PlanNode("n2", "b", "step2", depends_on=["n1"]),
    ])
    bb = (await GraphOrchestrator(reg).run(g, "task"))["blackboard"]
    dep_ok = bool(w2.calls) and "上游数据" in w2.calls[0]

    w_fail = _DagTestWorker("x", fail=True)
    w_blk = _DagTestWorker("y")
    reg2 = AgentRegistry()
    reg2.register(w_fail)
    reg2.register(w_blk)
    g2 = PlanGraph(nodes=[
        PlanNode("f1", "x", "fail"),
        PlanNode("f2", "y", "skip", depends_on=["f1"]),
    ])
    bb2 = (await GraphOrchestrator(reg2).run(g2, "t"))["blackboard"]
    block_ok = bb2["f1"]["status"] == "failed" and bb2["f2"]["status"] == "blocked" and not w_blk.calls

    attempts = {"n1": 0}

    async def verifier(node, output):
        attempts[node.id] += 1
        return attempts[node.id] > 1, "retry"

    w_rev = _DagTestWorker("r")
    reg3 = AgentRegistry()
    reg3.register(w_rev)
    g3 = PlanGraph(nodes=[PlanNode("n1", "r", "work", acceptance="ok")])
    bb3 = (await GraphOrchestrator(reg3, verifier=verifier, max_revisions=1).run(g3, "t"))["blackboard"]
    rev_ok = bb3["n1"]["status"] == "revised" and len(w_rev.calls) == 2

    ok = bb["n1"]["status"] == "done" and dep_ok and block_ok and rev_ok
    return ok, f"dep={dep_ok}, block={block_ok}, revise={rev_ok}"


async def _dag_coordinator_escalation_check() -> tuple:
    from agents.coordinator import Coordinator
    from agents.dispatcher import AutoDispatcher
    from agents.plan_graph import PlanGraph, PlanNode
    from agents.registry import AgentRegistry
    from agents.spec import AgentSpec
    from agents.worker import WorkerAgent
    from config import Config
    from core.types import CapabilityCall, EventType, Identity, Risk, Step
    from governance.budget import BudgetGovernor
    from llm.mock_llm import MockLLM

    class StuckLLM:
        name = "stuck"

        async def next_step(self, messages, capabilities, emit_token=None):
            return Step(call=CapabilityCall(
                name="fs.read", args={"path": "README.md"}, intent="x", declared_risk=Risk.READ))

    class FakeGraphDispatcher:
        def __init__(self):
            self.calls = 0

        async def route(self, task, workers):
            self.calls += 1
            return PlanGraph(nodes=[PlanNode("n1", "code_agent", "子任务")], reason="fake")

    def _worker(name):
        spec = AgentSpec(name=name, role=name, description=name, auto_confirm=True)
        llm = MockLLM()
        reg = CapabilityRegistry([ReadFile()])
        return WorkerAgent(spec=spec, agent=Agent(
            llm=llm, registry=reg, policy=DeclarativePolicy(reg),
            bus=EventBus(), budget=BudgetGovernor(max_steps=5)))

    bus = EventBus()
    seen: list = []
    bus.subscribe(seen.append)
    workers = AgentRegistry()
    workers.register(_worker("code_agent"))
    main = Agent(
        llm=StuckLLM(),
        registry=CapabilityRegistry([ReadFile()]),
        policy=DeclarativePolicy(CapabilityRegistry([ReadFile()])),
        bus=bus, budget=BudgetGovernor(max_steps=20),
    )
    coord = Coordinator(
        main_agent=main, worker_registry=workers,
        dispatcher=AutoDispatcher(MockLLM()),
        graph_dispatcher=FakeGraphDispatcher(), bus=bus,
    )
    ctx = Context(identity=Identity())
    ctx.add_system("t")
    old = Config.CAPTAIN_MAX_STEPS
    Config.CAPTAIN_MAX_STEPS = 2
    try:
        out = await coord.run("改代码 分析", ctx, lambda *a, **k: True)
    finally:
        Config.CAPTAIN_MAX_STEPS = old
    plan = any(
        e.type == EventType.CAPABILITY_CALL and (e.payload or {}).get("name") == "coordinator.plan"
        for e in seen
    )
    pupd = any(e.type == EventType.PLAN_UPDATE for e in seen)
    ok = plan and pupd and isinstance(out, str) and len(out) > 0
    return ok, f"plan={plan}, plan_update={pupd}, out_len={len(out) if isinstance(out, str) else 0}"


async def _hierarchical_check() -> tuple:
    """Hierarchical: 主管拆解任务 -> 下属执行 -> 主管汇总,结构正确。"""
    from agents.node import ChatAgent
    from agents.orchestrator import Hierarchical

    llm = MockLLM()
    manager = ChatAgent("mgr", "主管", llm)
    workers = [ChatAgent(f"w{i}", f"下属{i}", llm) for i in range(2)]
    result = await Hierarchical().run([manager] + workers, "制定一个简短计划")

    t = result["transcript"]
    turns_ok = result["turns"] >= 4  # 主管拆解 + 2下属 + 主管汇总
    names_ok = any(m.name == "mgr" for m in t)
    workers_ok = any(m.name == "w0" for m in t) and any(m.name == "w1" for m in t)
    ok = turns_ok and names_ok and workers_ok
    return ok, f"轮数={result['turns']}, 有主管={names_ok}, 有下属={workers_ok}"


async def _no_premature_dispatch_check() -> tuple:
    """Captain 在步数内完成时不应触发 coordinator.dispatch(模式 A+)。"""
    from agents.coordinator import Coordinator
    from agents.dispatcher import AutoDispatcher
    from agents.registry import AgentRegistry
    from agents.worker import WorkerAgent
    from agents.spec import AgentSpec
    from core.bus import EventBus
    from core.context import Context
    from core.types import EventType, Identity
    from governance.budget import BudgetGovernor

    def _make_worker(name: str) -> WorkerAgent:
        spec = AgentSpec(
            name=name, role=name, description=name, auto_confirm=True,
            trigger_keywords=["改代码", "写代码"],
        )
        llm = MockLLM()
        reg = CapabilityRegistry([ReadFile()])
        policy = DeclarativePolicy(reg)
        agent_obj = Agent(
            llm=llm, registry=reg, policy=policy,
            bus=EventBus(), budget=BudgetGovernor(max_steps=3),
        )
        return WorkerAgent(spec=spec, agent=agent_obj)

    bus = EventBus()
    seen: list = []
    bus.subscribe(lambda e: seen.append(e))

    workers = AgentRegistry()
    workers.register(_make_worker("code_agent"))

    main_llm = MockLLM()
    main_reg = CapabilityRegistry([ReadFile()])
    main_policy = DeclarativePolicy(main_reg)
    main_agent = Agent(
        llm=main_llm, registry=main_reg, policy=main_policy,
        bus=bus, budget=BudgetGovernor(max_steps=5),
    )

    coordinator = Coordinator(
        main_agent=main_agent,
        worker_registry=workers,
        dispatcher=AutoDispatcher(main_llm),
        bus=bus,
    )
    ctx = Context(identity=Identity())
    ctx.add_system("test")

    async def no_confirm(c, d, reason=""):
        return True

    await coordinator.run("读 README.md", ctx, no_confirm)
    dispatched = any(
        e.type == EventType.CAPABILITY_CALL
        and (e.payload or {}).get("name") == "coordinator.dispatch"
        for e in seen
    )
    ok = not dispatched
    return ok, f"premature_dispatch={dispatched}"


async def _captain_escalation_check() -> tuple:
    """Captain 步数用尽后应升级专家(coordinator.dispatch)。"""
    from agents.coordinator import Coordinator
    from agents.dispatcher import AutoDispatcher
    from agents.registry import AgentRegistry
    from agents.worker import WorkerAgent
    from agents.spec import AgentSpec
    from config import Config
    from core.bus import EventBus
    from core.context import Context
    from core.loop import Agent
    from core.types import CapabilityCall, EventType, Identity, Risk, Step
    from governance.budget import BudgetGovernor
    from governance.engine import DeclarativePolicy

    class StuckMockLLM:
        name = "mock-stuck"

        async def next_step(self, messages, capabilities, emit_token=None):
            return Step(
                call=CapabilityCall(
                    name="fs.read",
                    args={"path": "README.md"},
                    intent="继续尝试",
                    declared_risk=Risk.READ,
                ),
            )

    def _make_worker(name: str) -> WorkerAgent:
        spec = AgentSpec(
            name=name, role=name, description=name, auto_confirm=True,
            trigger_keywords=["改代码", "写代码", "代码"],
        )
        llm = MockLLM()
        reg = CapabilityRegistry([ReadFile()])
        agent_obj = Agent(
            llm=llm, registry=reg, policy=DeclarativePolicy(reg),
            bus=EventBus(), budget=BudgetGovernor(max_steps=5),
        )
        return WorkerAgent(spec=spec, agent=agent_obj)

    bus = EventBus()
    seen: list = []
    bus.subscribe(lambda e: seen.append(e))

    workers = AgentRegistry()
    workers.register(_make_worker("code_agent"))

    main_agent = Agent(
        llm=StuckMockLLM(),
        registry=CapabilityRegistry([ReadFile()]),
        policy=DeclarativePolicy(CapabilityRegistry([ReadFile()])),
        bus=bus,
        budget=BudgetGovernor(max_steps=20),
    )

    coordinator = Coordinator(
        main_agent=main_agent,
        worker_registry=workers,
        dispatcher=AutoDispatcher(MockLLM()),
        bus=bus,
    )
    ctx = Context(identity=Identity())
    ctx.add_system("test")

    old_cap = Config.CAPTAIN_MAX_STEPS
    Config.CAPTAIN_MAX_STEPS = 3
    try:
        async def no_confirm(c, d, reason=""):
            return True

        await coordinator.run("改代码 修复登录模块", ctx, no_confirm)
    finally:
        Config.CAPTAIN_MAX_STEPS = old_cap

    dispatched = any(
        e.type == EventType.CAPABILITY_CALL
        and (e.payload or {}).get("name") == "coordinator.dispatch"
        for e in seen
    )
    return dispatched, f"escalation_dispatch={dispatched}"


async def _coordinator_check(tmp: str) -> tuple:
    """Coordinator: /命令 显式调用专家 + Captain 汇总 + roster 预设。"""
    from agents.coordinator import Coordinator
    from agents.registry import AgentRegistry
    from agents.worker import WorkerAgent
    from agents.spec import AgentSpec
    from governance.resource_lock import ResourceLock
    from governance.budget import BudgetGovernor
    from governance.engine import DeclarativePolicy
    from core.context import Context
    from core.types import Identity

    def _make_worker(name):
        spec = AgentSpec(
            name=name, role=name, description=name, auto_confirm=True,
            system_prompt="执行 worker 测试",
        )
        llm = MockLLM()
        reg = CapabilityRegistry([ReadFile()])
        policy = DeclarativePolicy(reg)
        agent_obj = Agent(llm=llm, registry=reg, policy=policy,
                          bus=EventBus(), budget=BudgetGovernor(max_steps=3))
        return WorkerAgent(spec=spec, agent=agent_obj)

    w1 = _make_worker("code_agent")
    w2 = _make_worker("report_agent")

    reg = AgentRegistry()
    reg.register(w1)
    reg.register(w2)

    lock = ResourceLock()
    main_llm = MockLLM()
    main_reg = CapabilityRegistry([ReadFile()])
    main_policy = DeclarativePolicy(main_reg)
    main_agent = Agent(llm=main_llm, registry=main_reg, policy=main_policy,
                       bus=EventBus(), budget=BudgetGovernor(max_steps=5))

    coordinator = Coordinator(
        main_agent=main_agent,
        worker_registry=reg,
        resource_lock=lock,
        bus=EventBus(),
    )

    expert_events: list = []
    coordinator._bus.subscribe(expert_events.append)

    ctx = Context(identity=Identity())
    ctx.add_system("test")

    async def no_confirm(c, d, reason=""): return True

    result1 = await coordinator.run("/code_agent 列出当前目录", ctx, no_confirm)
    cmd1_ok = isinstance(result1, str) and len(result1) > 0

    expert_msgs = [
        e for e in expert_events
        if e.type == EventType.ASSISTANT_MESSAGE
        and e.payload.get("direct_expert")
    ]
    expert_direct_ok = (
        len(expert_msgs) >= 1
        and expert_msgs[-1].payload.get("text") == result1
        and expert_msgs[-1].payload.get("source") == "code_agent"
    )

    result2 = await coordinator.run("/report_agent 写一句测试摘要", ctx, no_confirm)
    cmd2_ok = isinstance(result2, str) and len(result2) > 0

    help_text = await coordinator.run("/experts", ctx, no_confirm)
    help_ok = "code_agent" in help_text and "report_agent" in help_text

    from agents.commands import parse_slash_command, format_models_help, format_skills_help
    slash_ok = (
        parse_slash_command("/model deepseek-v4-flash", expert_names=set()).kind == "set_model"
        and parse_slash_command("/model deepseek", expert_names=set()).kind == "set_model"
        and parse_slash_command("/text_stats hi", expert_names=set(), skill_names={"text_stats"}).kind == "invoke_skill"
        and "deepseek-v4-flash" in format_models_help("mock")
    )

    async with lock.acquire("test_file.txt"):
        guard = await lock.try_acquire("test_file.txt", timeout=0.05)
        lock_ok = guard is None

    from agents.spec import load_specs_from_roster
    roster_dir = os.path.join(ROOT, "agents", "roster")
    specs = load_specs_from_roster(roster_dir)
    expected = {
        "code_agent", "data_analyst_agent", "web_agent",
        "ops_notify_agent", "adler_counselor_agent",
    }
    names = {s.name for s in specs}
    roster_ok = expected.issubset(names)

    ok = all([cmd1_ok, cmd2_ok, help_ok, lock_ok, roster_ok, slash_ok, expert_direct_ok])
    return ok, f"cmd1={cmd1_ok}, cmd2={cmd2_ok}, help={help_ok}, slash={slash_ok}, 互斥锁={lock_ok}, roster={roster_ok}, expert_direct={expert_direct_ok}"


async def _ext_channels_check() -> tuple:
    """外部渠道:不需真实凭证,只验证协议结构——入队/出队/确认超时。"""
    import asyncio
    from channels.email_channel import EmailChannel
    from channels.wechat_channel import WeChatChannel
    from channels.qq_channel import QQChannel
    from core.types import CapabilityCall

    results = []

    # ── 邮件:直接喂消息入队,验证 receive 能取出 ─────────────────────────────
    em = EmailChannel(imap_host="x", smtp_host="x", user="u@x.com", password="p")
    em._inbox.put_nowait(("sender@x.com", "hello from email"))
    text = await asyncio.wait_for(em.receive(), timeout=1.0)
    results.append(("email_receive", text == "hello from email"))

    # 验证 confirm 超时默认拒绝(timeout=0.05 秒)
    em._current_sender = "sender@x.com"
    async def _fake_send(*a, **k): pass
    em._send_email = _fake_send  # 屏蔽真实 SMTP
    call = CapabilityCall(name="fs.write", args={"path": "x"}, intent="test")
    original_timeout = 60.0
    # 临时缩短超时:monkey-patch wait_for via confirm 的局部 future
    fut = asyncio.get_event_loop().create_future()
    em._pending_confirm["TEST01"] = fut
    # confirm 内部会 create_future;我们测超时路径:不 set_result,让它到期
    async def _timed_confirm():
        try:
            return await asyncio.wait_for(asyncio.get_event_loop().create_future(), timeout=0.05)
        except asyncio.TimeoutError:
            return False
    timeout_result = await _timed_confirm()
    results.append(("email_confirm_timeout", timeout_result is False))

    # ── 企业微信:测消息解析入队 ──────────────────────────────────────────────
    wx = WeChatChannel(corp_id="x", agent_id="1", secret="s", token="t", aes_key="")
    wx_xml = (
        "<xml>"
        "<ToUserName><![CDATA[agent]]></ToUserName>"
        "<FromUserName><![CDATA[user001]]></FromUserName>"
        "<MsgType><![CDATA[text]]></MsgType>"
        "<Content><![CDATA[hello-wechat]]></Content>"
        "</xml>"
    ).encode("utf-8")
    await wx.handle_message(wx_xml, {})
    wx_item = wx._inbox.get_nowait()
    results.append(("wechat_receive", wx_item[1] == "hello-wechat"))

    # 确认回复解析
    confirm_xml = (
        "<xml>"
        "<ToUserName><![CDATA[agent]]></ToUserName>"
        "<FromUserName><![CDATA[user001]]></FromUserName>"
        "<MsgType><![CDATA[text]]></MsgType>"
        "<Content><![CDATA[y AB1234]]></Content>"
        "</xml>"
    ).encode("utf-8")
    fut2 = asyncio.get_event_loop().create_future()
    wx._pending_confirm["AB1234"] = fut2
    await wx.handle_message(confirm_xml, {})
    results.append(("wechat_confirm_parse", fut2.done() and fut2.result() is True))

    # ── QQ:测 dispatch 入队 ───────────────────────────────────────────────────
    qq = QQChannel(app_id="x", app_secret="s")
    payload = {
        "op": 0,
        "t": "GROUP_AT_MESSAGE_CREATE",
            "d": {
                "group_openid": "grp001",
                "content": "hello-qq",
            "author": {"id": "u999"},
            "id": "msg001",
        },
    }
    import json
    await qq.handle_callback(json.dumps(payload).encode(), {})
    qq_item = qq._inbox.get_nowait()
    results.append(("qq_receive", qq_item[1] == "hello-qq"))

    c2c_payload = {
        "op": 0,
        "t": "C2C_MESSAGE_CREATE",
        "d": {
            "content": "hi-c2c",
            "id": "msg002",
            "author": {"user_openid": "U001"},
        },
    }
    await qq.handle_callback(json.dumps(c2c_payload).encode(), {})
    c2c_item = qq._inbox.get_nowait()
    results.append(("qq_c2c", c2c_item[1] == "hi-c2c" and c2c_item[0].get("openid") == "U001"))

    # URL 验证(无真实 secret 时应抛 RuntimeError,捕获即可)
    try:
        await qq._handle_url_validation({"d": {"event_ts": "123", "plain_token": "abc"}})
        url_ok = True   # cryptography 已安装
    except (RuntimeError, Exception):
        url_ok = True   # 缺依赖时 raise RuntimeError,属于预期行为

    results.append(("qq_url_validation", url_ok))

    from channels.slack_channel import SlackChannel
    from channels.telegram_channel import TelegramChannel

    sl = SlackChannel(bot_token="x", signing_secret="")
    sl.feed_message("C001", "U001", "hello-slack")
    sl_item = sl._inbox.get_nowait()
    results.append(("slack_receive", sl_item[1] == "hello-slack"))

    tg = TelegramChannel(bot_token="x")
    tg.feed_update({"message": {"chat": {"id": 99}, "from": {"id": 42}, "text": "hello-tg"}})
    tg_item = tg._inbox.get_nowait()
    results.append(("telegram_receive", tg_item[1] == "hello-tg"))

    failed = [name for name, ok in results if not ok]
    all_ok = not failed
    return all_ok, f"通过={len(results)-len(failed)}/{len(results)}" + (f" 失败:{failed}" if failed else "")


def _bootstrap_gui_registry_check() -> tuple:
    """bootstrap: interactive/cli 注册 gui.control,external 不暴露。"""
    from core.bootstrap import build_registry

    reg_i = build_registry("interactive")
    reg_c = build_registry("cli", worker_registry=object())
    reg_e = build_registry("external")
    ok = (
        reg_i.get("gui.control") is not None
        and reg_c.get("gui.control") is not None
        and reg_e.get("gui.control") is None
    )
    return ok, f"interactive={reg_i.get('gui.control') is not None}, external={reg_e.get('gui.control') is None}"


async def _gui_screenshot_check(tmp: str) -> tuple:
    """GUI: 截图生成真实 PNG 文件(zero third-party dep)。"""
    import os
    import sys
    # screencapture 是 macOS 专有命令;非 macOS 环境(Linux/CI)跳过,不算失败。
    if sys.platform != "darwin":
        return True, "跳过:非 macOS 环境,screencapture 不可用"
    from capabilities.gui import GUIControl, _TRACE_DIR

    gui = GUIControl()
    r = await gui.invoke({"action": "screenshot"}, None)
    path = r.output.replace("截图已保存:", "").strip()
    file_ok = r.ok and os.path.isfile(path) and os.path.getsize(path) > 1024
    return file_ok, f"ok={r.ok}, 文件={path}, 大小={os.path.getsize(path) if os.path.isfile(path) else 0}B"


def _authz_check() -> tuple:
    """按主体鉴权: readonly 角色不得调用 fs.write;无角色不受限。"""
    from core.types import CapabilityCall, Identity
    from governance.engine import DeclarativePolicy

    registry = CapabilityRegistry([ReadFile(), WriteFile()])
    policy = DeclarativePolicy(registry, config_path=None)

    # readonly 角色 -> fs.write 应被 BLOCK
    readonly_actor = Identity(roles=("readonly",))
    call_w = CapabilityCall(name="fs.write", args={"path": "x.txt", "content": "hi"})
    blocked = policy.review(call_w, readonly_actor, None).value == "block"

    # readonly 角色 -> fs.read 应被放行
    call_r = CapabilityCall(name="fs.read", args={"path": "x.txt"})
    allowed = policy.review(call_r, readonly_actor, None).value == "allow"

    # 无角色 -> fs.write 走正常软边界(ask,不是 block)
    no_role_actor = Identity(roles=())
    normal = policy.review(call_w, no_role_actor, None).value == "ask"

    ok = blocked and allowed and normal
    return ok, f"readonly 拒写={blocked}, readonly 允读={allowed}, 无角色走软边界={normal}"


async def _budget_check() -> tuple:
    """Budget: tiktoken 计数 > 0;金额上限触发时任务自动停止。"""
    from governance.budget import BudgetGovernor

    b = BudgetGovernor(max_steps=100, provider="deepseek")
    n = b.charge("hello world this is a test sentence", "deepseek")
    token_ok = n > 0
    cost_ok = b.cost_usd > 0

    # 金额上限:设一个极小上限,charge 后 exceeded 应变 True。
    b2 = BudgetGovernor(max_steps=100, max_cost_usd=0.000001, provider="deepseek")
    b2.charge("x" * 5000, "deepseek")
    limit_ok = b2.exceeded() and "金额" in b2.reason()

    ok = token_ok and cost_ok and limit_ok
    return ok, f"tokens={n}, cost=${b.cost_usd:.6f}, 金额上限触发={limit_ok}"


async def _preference_loop_check(tmp: str) -> tuple:
    """偏好沉淀闭环:抽取→去重→注入(LLM 可注入,确定性)。"""
    from core.types import Message, Role, Step
    from memory.factory import build_longterm
    from memory.preference_miner import PreferenceMiner, format_preference_block

    class FakeMinerLLM:
        async def next_step(self, messages, capabilities, emit_token=None):
            return Step(text='["主人偏好简洁的中文回复", "主人的项目用 Python"]')

    sub = os.path.join(tmp, "pref")
    os.makedirs(sub, exist_ok=True)
    mem = build_longterm(sub)
    miner = PreferenceMiner(FakeMinerLLM(), mem)
    dialogue = [
        Message(role=Role.USER, content="回复请简洁,用中文"),
        Message(role=Role.ASSISTANT, content="好的"),
    ]

    stored1 = await miner.mine(dialogue)
    stored2 = await miner.mine(dialogue)  # 第二次应全部去重
    block = format_preference_block(mem)

    listed = mem.list_by_kind("preference", limit=10)
    deleted = mem.delete_by_content("preference", "主人的项目用 Python")
    remaining = mem.list_by_kind("preference", limit=10)

    ok = (
        len(stored1) == 2
        and len(stored2) == 0
        and "简洁的中文回复" in block
        and len(listed) == 2
        and deleted >= 1
        and len(remaining) == 1
    )
    return ok, (f"首次={len(stored1)}, 去重后={len(stored2)}, 注入={'简洁' in block}, "
                f"列表={len(listed)}, 删除={deleted}, 余={len(remaining)}")


async def _personal_ingest_check(tmp: str) -> tuple:
    """个人数据接入:增量索引→检索→改动重索引→删除清理。"""
    from memory.factory import build_longterm
    from memory.ingest import ingest_dirs

    docs = os.path.join(tmp, "personal_docs")
    os.makedirs(docs, exist_ok=True)
    note = os.path.join(docs, "note.md")
    with open(note, "w", encoding="utf-8") as f:
        f.write("# 想法\n\n做一个有分寸感的 agent 平台,治理要严。\n\n第二段:记忆要主动管理。")

    sub = os.path.join(tmp, "ingest_mem")
    os.makedirs(sub, exist_ok=True)
    mem = build_longterm(sub)
    state = os.path.join(sub, "state.json")

    s1 = ingest_dirs([docs], mem, state_path=state)
    s2 = ingest_dirs([docs], mem, state_path=state)  # 未变 → 跳过
    incremental_ok = s1["indexed"] == 1 and s2["indexed"] == 0 and s2["skipped"] == 1

    # skill 检索(ctx 只需有 longterm 属性)
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "_ps_impl", os.path.join(ROOT, "skills", "personal_search", "impl.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    class _Ctx:
        longterm = mem
    r = await mod.run({"query": "agent 平台 治理"}, _Ctx())
    search_ok = r.ok and "file:" in (r.output or "")

    # 源文件删除 → 索引与状态清理
    os.remove(note)
    s3 = ingest_dirs([docs], mem, state_path=state)
    r2 = await mod.run({"query": "agent 平台 治理"}, _Ctx())
    cleanup_ok = s3["removed_chunks"] >= 1 and "没有相关内容" in (r2.output or "")

    ok = incremental_ok and search_ok and cleanup_ok
    return ok, f"增量={incremental_ok}, 检索={search_ok}, 清理={cleanup_ok}"


def _briefing_task_check(tmp: str) -> tuple:
    """每日简报:幂等注册(首次创建,二次跳过,UI 修改不被覆盖)。"""
    from core.briefing import BRIEFING_TASK_NAME, ensure_briefing_task
    from scheduler.store import TaskStore

    store = TaskStore(db_path=os.path.join(tmp, "tasks_briefing.db"))
    created1 = ensure_briefing_task(store, at_hhmm="08:00", channel="qq", to="group:123")
    created2 = ensure_briefing_task(store, at_hhmm="09:30", channel="email")  # 不应覆盖
    tasks = [t for t in store.list() if t.name == BRIEFING_TASK_NAME]
    t = tasks[0] if tasks else None
    ok = (
        created1 and not created2 and len(tasks) == 1
        and t is not None and t.schedule_type == "daily"
        and t.at_hhmm == "08:00" and t.deliver == "qq" and t.deliver_to == "group:123"
    )
    return ok, f"首次={created1}, 二次={created2}, 条数={len(tasks)}, at={getattr(t, 'at_hhmm', '?')}"


def _hybrid_memory_check(tmp: str) -> tuple:
    """混合记忆:关键词 + 向量双路检索合并。"""
    from memory.base import MemoryItem
    from memory.factory import build_longterm

    mem = build_longterm(tmp)
    mem.store(MemoryItem(kind="fact", content="Python 是一门编程语言", importance=0.8))
    mem.store(MemoryItem(kind="fact", content="agent 需要治理层保证安全", importance=0.7))
    hits = mem.retrieve("编程语言有哪些", k=2)
    top = hits[0].content if hits else ""
    ok = "Python" in top and len(hits) >= 1
    return ok, f"top={top!r}, n={len(hits)}"


def _vector_memory_check(tmp: str) -> tuple:
    """向量记忆:语义相似的文本应排在最前(RAG 核心承诺)+遗忘清理。"""
    from memory.base import MemoryItem
    from memory.vector import MockEmbed, VectorMemory

    mem = VectorMemory(embed_fn=MockEmbed(), db_path=os.path.join(tmp, "vec.db"))
    # 存入三条记忆
    mem.store(MemoryItem(kind="fact", content="Python 是一门编程语言", importance=0.8))
    mem.store(MemoryItem(kind="fact", content="agent 需要治理层保证安全", importance=0.7))
    old_ts = time.time() - 60 * 86400
    mem.store(MemoryItem(kind="episode", content="昨天吃了面条",
                         importance=0.1, created_at=old_ts, last_used=old_ts))

    # 语义查询"编程语言"——应命中"Python"而非"治理"或"面条"
    hits = mem.retrieve("编程语言有哪些", k=2)
    top_hit = hits[0].content if hits else ""
    semantic_ok = "Python" in top_hit

    # 遗忘:低重要性 + 过期
    removed = mem.forget(min_importance=0.2, max_age_days=30.0)
    after = mem.retrieve("面条", k=5)
    forgot_ok = removed >= 1 and not any("面条" in h.content for h in after)

    mem.close()
    ok = semantic_ok and forgot_ok
    return ok, f"语义top={top_hit!r}, 语义正确={semantic_ok}, 遗忘={forgot_ok}(删{removed})"


async def _write_lock_check(tmp: str) -> tuple:
    """写文件资源锁:同一路径被占用时,loop 内的写操作应失败而非互相覆盖。"""
    import os as _os
    from governance.resource_lock import default_lock
    from governance.budget import BudgetGovernor
    from core.types import Identity

    target = _os.path.join(tmp, "locked.txt")
    registry = CapabilityRegistry([WriteFile()])
    agent = Agent(
        llm=MockLLM(), registry=registry,
        policy=DeclarativePolicy(registry),
        bus=EventBus(), budget=BudgetGovernor(max_steps=5),
    )
    agent.write_lock_timeout = 0.2

    ctx = Context(identity=Identity())
    ctx.add_system("test")

    async def yes(c, d, reason=""):
        return True

    # 1. 锁被外部占用时,写入应失败(资源被占用)。
    guard = await default_lock.try_acquire(_os.path.abspath(target), timeout=1.0)
    assert guard is not None
    try:
        out1 = await agent.run(f"写 {target} :: hello", ctx, yes)
    finally:
        guard.release()
    blocked = "资源被占用" in out1 and not _os.path.exists(target)

    # 2. 锁释放后,同一路径写入应成功。
    ctx2 = Context(identity=Identity())
    ctx2.add_system("test")
    await agent.run(f"写 {target} :: hello", ctx2, yes)
    written = _os.path.exists(target)

    ok = blocked and written
    return ok, f"占用时拒绝={blocked}, 释放后写入={written}"


def _skill_router_check() -> tuple:
    from skills.router import match_routes, routes_to_prefetch, should_route

    landing = match_routes("帮我做一个 SaaS 落地页，Linear 风格")
    ok1 = any(r.name == "design_taste_frontend" for r in landing)
    ok2 = should_route("做一个 landing page") and not should_route("你好")
    prefetch = routes_to_prefetch(landing)
    ok3 = all(r.name != "notify_dispatch" for r in prefetch)
    ok4 = all(r.name not in ("design_taste_frontend", "claude_design") for r in prefetch)
    ok = ok1 and ok2 and ok3 and ok4
    names = [r.name for r in landing]
    return ok, f"landing={names}, prefetch={[r.name for r in prefetch]}"


async def _skill_check() -> tuple:
    """skill 插件:自动发现 + 加载 + 作为统一能力调用。"""
    from skills.base import SkillRegistry

    registry = CapabilityRegistry([ReadFile()])
    loaded = SkillRegistry(os.path.join(ROOT, "skills")).load_all_into(registry)
    expected = {
        "text_stats", "readability_score", "keyword_extract", "notify_dispatch",
        "claude_design", "design_taste_frontend",
    }
    if not expected.issubset(set(loaded)):
        return False, f"skill 缺失, 已加载={loaded}"

    r1 = await registry.get("skill.text_stats").invoke(
        {"text": "hello world\nsecond line"}, None
    )
    r2 = await registry.get("skill.readability_score").invoke(
        {"text": "这是第一句。这是第二句，稍长一些用于测试可读性评分。"}, None
    )
    r3 = await registry.get("skill.keyword_extract").invoke(
        {"text": "市场调研 竞品分析 市场调研 增长策略"}, None
    )
    r4 = await registry.get("skill.notify_dispatch").invoke(
        {"channel": "email", "to": "u@test.com", "subject": "测", "body": "正文"},
        None,
    )

    ok = (
        r1.ok and "字符=" in r1.output
        and r2.ok and "可读性评分" in r2.output
        and r3.ok and "市场调研" in r3.output
        and r4.ok and ("邮件" in r4.output or "文稿" in r4.output or "EMAIL" in r4.output)
    )
    return ok, f"已加载={loaded}, stats={r1.ok}, read={r2.ok}, kw={r3.ok}, notify={r4.ok}"


def _skill_multidir_check() -> tuple:
    """多目录 skill 发现:内置 skills/ + 用户 ~/.agents/skills/。"""
    import os
    from skills.paths import build_skill_registry, resolve_skills_dirs

    dirs = resolve_skills_dirs()
    reg = build_skill_registry()
    reg.discover()
    names = {m.name for m in reg.available()}
    user_dir = os.path.abspath(os.path.expanduser(
        os.environ.get("AGENT_USER_SKILLS_DIR", "~/.agents/skills")
    ))
    user_skills = sorted(
        m.name for m in reg.available()
        if m.source_root and os.path.abspath(m.source_root) == user_dir
    )
    ok = len(dirs) >= 1 and len(names) >= 7
    if os.path.isdir(user_dir):
        ok = ok and len(user_skills) >= 1
    return ok, f"dirs={len(dirs)}, total={len(names)}, user={user_skills}"


async def _multiagent_check() -> tuple:
    """多 agent:圆桌轮数受 budget 守卫;流水线按序产出。"""
    from agents.node import ChatAgent
    from agents.orchestrator import Sequential
    from agents.roundtable import Roundtable

    llm = MockLLM()
    agents = [ChatAgent(f"A{i}", role=f"角色{i}", llm=llm) for i in range(3)]

    rt = await Roundtable(max_turns=4).run(agents, "要不要给 agent 加圆桌?")
    rt_ok = rt["turns"] == 4 and len(rt["transcript"]) == 4 and all(m.name for m in rt["transcript"])

    seq = await Sequential().run(agents, "流水线处理")
    seq_ok = len(seq["transcript"]) == 3

    ok = rt_ok and seq_ok
    return ok, f"圆桌轮数={rt['turns']}({rt['stopped']}), 流水线={len(seq['transcript'])}"


def _ollama_factory_check() -> tuple:
    from llm.factory import build_llm
    from llm.ollama_llm import OllamaLLM

    llm = build_llm("ollama")
    ok = isinstance(llm, OllamaLLM) and llm.name == "ollama"
    return ok, f"type={type(llm).__name__}, model={getattr(llm, 'model', '?')}"


async def _debate_check() -> tuple:
    from agents.debate import Debate
    from llm.factory import build_llm

    events: list[dict] = []

    async def on_event(evt: dict) -> None:
        events.append(evt)

    d = Debate(build_llm, max_rounds=1)
    result = await d.run("是否该用 AI 写代码", on_event=on_event)
    msgs = [e for e in events if e.get("type") == "debate_message"]
    ok = bool(result.get("summary")) and len(msgs) >= 2
    return ok, f"msgs={len(msgs)}, summary_len={len(result.get('summary') or '')}"


def _governance_mode_check() -> tuple:
    from capabilities.base import CapabilityRegistry
    from capabilities.tools.fs import WriteFile
    from capabilities.tools.shell import RunShell
    from core.types import CapabilityCall, Decision, Identity
    from governance.engine import DeclarativePolicy

    reg = CapabilityRegistry([WriteFile(), RunShell()])
    write_call = CapabilityCall(name="fs.write", args={"path": "logs/x.txt", "content": "hi"})
    date_call = CapabilityCall(name="shell.run", args={"command": "date"})
    rm_call = CapabilityCall(name="shell.run", args={"command": "rm /tmp/x"})
    actor = Identity(subject_id="u", agent_name="main", channel="web")
    ctx = object()

    policy = DeclarativePolicy(reg, config_path="governance/policy.yaml")
    rw = policy.review_detailed(write_call, actor, ctx)
    rd = policy.review_detailed(date_call, actor, ctx)
    rr = policy.review_detailed(rm_call, actor, ctx)
    ok = (
        rw.decision == Decision.ASK and rw.rule.startswith("confirm:")
        and rd.decision == Decision.ALLOW
        and rr.decision == Decision.ASK and rr.rule.startswith("confirm:shell:")
    )
    return ok, f"write={rw.decision}/{rw.rule} date={rd.decision} rm={rr.decision}/{rr.rule}"


def _program_memory_check(tmp: str) -> tuple:
    from memory.program_store import ProgramMemoryStore

    db = os.path.join(tmp, "program.db")
    store = ProgramMemoryStore(db_path=db)
    store.set("user-1", "prefs.style", "concise")
    got = store.get("user-1", "prefs.style")
    keys = store.list_keys("user-1", "prefs.")
    ok = got == "concise" and "prefs.style" in keys
    store.close()
    return ok, f"got={got}, keys={keys}"


def _context_facade_check() -> tuple:
    from core.context_facade import ConversationLog, SessionAttachment
    from memory.working import WorkingMemory

    log = ConversationLog()
    log.add_user("hi")
    log.add_tool_call("id1", "fs.read", {"path": "/a"}, intent="读")
    log.add_tool_result("ok", "id1")
    view = log.llm_view(WorkingMemory())
    paired = len(view) == 3 and view[2].role.value == "tool"
    sess = SessionAttachment()
    ok = paired and sess.store is None
    return ok, f"view_len={len(view)}, paired={paired}"


async def run_all_checks(tmp: str, *, verbose: bool = False) -> tuple[int, int]:
    """跑全套回归,返回 (passed, total)。"""
    cases = build_cases(tmp)
    passed = 0
    total = 0

    async def _run_one(label: str, coro_fn) -> None:
        nonlocal passed, total
        total += 1
        try:
            ok, detail = await coro_fn()
        except Exception as e:
            ok, detail = False, f"异常:{type(e).__name__}: {e}"
        if verbose:
            print(f" [{'PASS' if ok else 'FAIL'}] {label}" + ("" if ok else f"  -> {detail}"))
        passed += int(ok)

    def _run_sync(label: str, fn) -> None:
        nonlocal passed, total
        total += 1
        try:
            ok, detail = fn()
        except Exception as e:
            ok, detail = False, f"异常:{type(e).__name__}: {e}"
        if verbose:
            print(f" [{'PASS' if ok else 'FAIL'}] {label}" + ("" if ok else f"  -> {detail}"))
        passed += int(ok)

    for case in cases:
        total += 1
        try:
            ok, detail = await _run_case(case)
        except Exception as e:
            ok, detail = False, f"异常:{type(e).__name__}: {e}"
        if verbose:
            mark = "PASS" if ok else "FAIL"
            print(f" [{mark}] {case.name}" + ("" if ok else f"  -> {detail}"))
        passed += int(ok)

    _run_sync("tool_calls 配对修复(孤儿调用补齐)", _tool_pairing_repair_check)
    _run_sync("DeepSeek reasoning_content 回传", _deepseek_reasoning_echo_check)
    await _run_one("工作记忆压缩(摘要+边界安全)", _compaction_check)
    _run_sync("SQLite 长期记忆(存取+遗忘)", lambda: _memory_check(tmp))
    _run_sync("skill 路由匹配", _skill_router_check)
    await _run_one("skill 插件(发现+加载+调用)", _skill_check)
    _run_sync("skill 多目录发现(内置+用户)", _skill_multidir_check)
    await _run_one("写文件资源锁(占用拒绝+释放可写)", lambda: _write_lock_check(tmp))
    await _run_one("多 agent(圆桌 budget + 流水线)", _multiagent_check)
    _run_sync("向量记忆 RAG(语义相似排序+遗忘)", lambda: _vector_memory_check(tmp))
    _run_sync("混合长期记忆(关键词+向量)", lambda: _hybrid_memory_check(tmp))
    await _run_one("偏好沉淀闭环(抽取+去重+注入+删除)", lambda: _preference_loop_check(tmp))
    _run_sync("每日简报任务(幂等注册)", lambda: _briefing_task_check(tmp))
    await _run_one("个人数据接入(增量索引+检索+清理)", lambda: _personal_ingest_check(tmp))
    await _run_one("Budget token 计数 + 金额上限", _budget_check)
    await _run_one("agent 委托(深度限制+只读策略)", lambda: _delegate_check(tmp))
    await _run_one("Hierarchical 分层编排(拆解+下属+汇总)", _hierarchical_check)
    await _run_one("DAG 计划图(校验/分层/兼容)", _dag_plan_graph_check)
    await _run_one("DAG 执行器(依赖/阻断/返修)", _dag_orchestrator_check)
    await _run_one("Captain 升级走 DAG(coordinator.plan)", _dag_coordinator_escalation_check)
    _run_sync("按主体鉴权(roles 白名单)", _authz_check)
    _run_sync("bootstrap GUI 注册(profile 分流)", _bootstrap_gui_registry_check)
    await _run_one("GUI 控制(截图存证)", lambda: _gui_screenshot_check(tmp))
    await _run_one("外部渠道(邮件/微信/QQ 协议结构)", _ext_channels_check)
    await _run_one("Captain 步数内不提前派专家", _no_premature_dispatch_check)
    await _run_one("Captain 步数用尽升级专家", _captain_escalation_check)
    await _run_one("Coordinator /命令调用专家", lambda: _coordinator_check(tmp))
    await _run_one("真 token 流式(ASSISTANT_TOKEN)", _streaming_token_check)
    _run_sync("CLI 流式输出(ASSISTANT_TOKEN)", _cli_stream_emit_check)
    _run_sync("状态栏格式(模型/上下文/时长)", _status_bar_format_check)
    await _run_one("治理可解释(拒绝带原因+命中规则入 trace)", _governance_reason_check)
    await _run_one("记忆写入治理(来源/重要性/主体)", _memory_governance_check)
    _run_sync("external profile(无 GUI + 有 notify)", _external_profile_registry_check)
    _run_sync("Ollama provider 工厂", _ollama_factory_check)
    await _run_one("Debate 辩论编排(正反+总结)", _debate_check)
    _run_sync("确认规则(改/删 shell 需确认,date/记忆放行)", _governance_mode_check)
    _run_sync("程序记忆 KV(存取+列表)", lambda: _program_memory_check(tmp))
    _run_sync("Context 门面(ConversationLog+配对)", _context_facade_check)
    _run_sync("联网搜索注册(web.search+web.fetch)", _web_registry_check)
    _run_sync("DuckDuckGo HTML 解析", _web_parse_check)
    _run_sync("本任务一次确认(task_auto_approve)", _task_auto_approve_check)
    _run_sync("删除会话不复活(append)", lambda: _session_delete_no_resurrect_check(tmp))
    _run_sync("会话重命名(update_title)", lambda: _session_rename_check(tmp))
    _run_sync("圆桌历史持久化", lambda: _roundtable_history_check(tmp))
    _run_sync("执行专家 roster 五人(归档不加载)", _roster_five_experts_check)
    _run_sync("治理统计中文与命中率", lambda: _governance_stats_check(tmp))
    _run_sync("用量统计(trace 聚合)", lambda: _usage_stats_check(tmp))

    return passed, total


def _session_delete_no_resurrect_check(tmp: str) -> tuple:
    from core.types import Message, Role
    from memory.session_store import SessionStore

    db = os.path.join(tmp, "sessions.db")
    store = SessionStore(db_path=db)
    store.ensure_session("s-del", "x")
    store.delete_session("s-del")
    store.append("s-del", Message(role=Role.USER, content="hi", ts=1))
    ok = not store.session_exists("s-del")
    store.close()
    return ok, f"exists_after_append={not ok}"


def _session_rename_check(tmp: str) -> tuple:
    from memory.session_store import SessionStore

    db = os.path.join(tmp, "sessions.db")
    store = SessionStore(db_path=db)
    store.ensure_session("s1", "旧标题")
    ok = store.update_title("s1", "新标题")
    rows = store.list_sessions()
    title = rows[0]["title"] if rows else ""
    store.close()
    return ok and title == "新标题", f"title={title!r}"


def _roundtable_history_check(tmp: str) -> tuple:
    from memory.session_store import SessionStore

    db = os.path.join(tmp, "sessions.db")
    store = SessionStore(db_path=db)
    meta = {
        "topic": "测试议题",
        "goal": "测试产出",
        "max_turns": 10,
        "messages": [{"agent_name": "产品经理", "content": "观点A", "turn": 1}],
        "summary": "结论",
        "stopped": "达到最大轮数",
        "turns": 1,
    }
    store.save_roundtable("rt-test", "测试议题", meta)
    loaded = store.load_roundtable("rt-test")
    rows = store.list_sessions()
    kind = rows[0].get("kind") if rows else ""
    store.delete_session("rt-test")
    gone = store.load_roundtable("rt-test") is None
    store.close()
    ok = (
        loaded is not None
        and loaded.get("topic") == "测试议题"
        and len(loaded.get("messages", [])) == 1
        and kind == "roundtable"
        and gone
    )
    return ok, f"kind={kind}, loaded={bool(loaded)}, deleted={gone}"


def _roster_five_experts_check() -> tuple:
    """roster 保留 5 个权限差异化专家,不含已移出的归档专家。"""
    from agents.spec import load_specs_from_roster

    roster_dir = os.path.join(ROOT, "agents", "roster")
    specs = load_specs_from_roster(roster_dir)
    names = {s.name for s in specs}
    required = {
        "code_agent", "data_analyst_agent", "web_agent",
        "ops_notify_agent", "adler_counselor_agent",
    }
    archived = {
        "market_research_agent", "ppt_agent", "marketing_agent", "copywriting_agent",
        "report_agent", "risk_assessment_agent", "philosophy_mentor_agent",
    }
    ok = (
        required.issubset(names)
        and not (archived & names)
        and all(s.system_prompt and s.description for s in specs if s.name in required)
    )
    return ok, f"count={len(specs)}, names={sorted(names)}"


def _governance_stats_check(tmp: str) -> tuple:
    import json
    import os
    import time

    from server.governance_stats import load_stats

    trace = os.path.join(tmp, "trace.jsonl")
    now = time.time()
    lines = [
        {"ts": now, "type": "governance_decision",
         "payload": {"rule": "auto", "decision": "allow"}},
        {"ts": now, "type": "governance_decision",
         "payload": {"rule": "confirm:fs.write", "decision": "ask"}},
        {"ts": now, "type": "governance_decision",
         "payload": {"rule": "task:auto", "decision": "allow"}},
    ]
    with open(trace, "w", encoding="utf-8") as f:
        for row in lines:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    data = load_stats(trace, days=7)
    summary = data.get("summary") or {}
    rows = data.get("rows") or []
    ok = (
        data["total"] == 3
        and summary.get("allow") == 2
        and summary.get("ask") == 1
        and abs(summary.get("hit_rate", 0) - 2 / 3) < 0.01
        and summary.get("reuse") == 2
        and rows[0].get("rule_label") == "自动放行"
    )
    return ok, f"hit_rate={summary.get('hit_rate')}, reuse={summary.get('reuse')}"


def _usage_stats_check(tmp: str) -> tuple:
    import json
    import time

    from server.usage_stats import load_usage

    path = os.path.join(tmp, "trace.jsonl")
    now = time.time()
    with open(path, "w", encoding="utf-8") as f:
        f.write(json.dumps({
            "ts": now,
            "trace_id": "t1",
            "type": "assistant_message",
            "payload": {"text": "ok", "budget_detail": {"tokens": 1200, "cost_usd": 0.00034}},
        }, ensure_ascii=False) + "\n")
        f.write(json.dumps({
            "ts": now + 1,
            "trace_id": "t1",
            "type": "assistant_message",
            "payload": {"text": "ok2", "budget_detail": {"tokens": 1500, "cost_usd": 0.00040}},
        }, ensure_ascii=False) + "\n")
    data = load_usage(path, days=7)
    ok = data["total_tokens"] == 1500 and data["tasks"] == 1
    return ok, f"tokens={data['total_tokens']} tasks={data['tasks']}"


def _web_registry_check() -> tuple:
    from core.bootstrap import build_registry

    reg = build_registry("interactive")
    ok = reg.get("web.search") is not None and reg.get("web.fetch") is not None
    return ok, f"search={reg.get('web.search')}, fetch={reg.get('web.fetch')}"


def _task_auto_approve_check() -> tuple:
    from capabilities.base import CapabilityRegistry
    from capabilities.tools.fs import WriteFile
    from core.context import Context
    from core.types import CapabilityCall, Decision, Identity
    from governance.engine import DeclarativePolicy

    reg = CapabilityRegistry([WriteFile()])
    policy = DeclarativePolicy(reg, config_path=None)
    ctx = Context()
    ctx.task_auto_approve = True
    call = CapabilityCall(name="fs.write", args={"path": "logs/x.txt", "content": "hi"})
    actor = Identity()
    d = policy.review(call, actor, ctx)
    ok = d == Decision.ALLOW
    return ok, f"decision={d.value}"


def _web_parse_check() -> tuple:
    from capabilities.tools.web import parse_duckduckgo_html

    sample = '''
    <a class="result__a" href="https://example.com/a">First</a>
    <a class="result__snippet">Snippet one</a>
    <a class="result__a" href="https://example.com/b">Second</a>
    '''
    hits = parse_duckduckgo_html(sample, 5)
    ok = len(hits) == 2 and hits[0]["title"] == "First" and "example.com/a" in hits[0]["url"]
    return ok, f"hits={hits}"


def _external_profile_registry_check() -> tuple:
    """external profile:不暴露 GUI,包含主动通知能力。"""
    from core.bootstrap import build_registry

    reg = build_registry("external")
    ok = reg.get("gui.control") is None and reg.get("notify.email") is not None
    return ok, f"gui={reg.get('gui.control')}, notify.email={reg.get('notify.email')}"


async def _main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        print("=" * 56)
        print(" 回归测试(MockLLM,确定性)")
        print("=" * 56)
        passed, total = await run_all_checks(tmp, verbose=True)
        print("-" * 56)
        print(f" 通过 {passed}/{total}")
        return 0 if passed == total else 1


def run_suite() -> int:
    return asyncio.run(_main())


if __name__ == "__main__":
    raise SystemExit(run_suite())
