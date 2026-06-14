"""DAG 规划器 + 执行器 + Coordinator 集成 —— L2/L3/L4。"""
from __future__ import annotations

import asyncio
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from agents.graph_dispatcher import GraphDispatcher, _parse_graph
from agents.graph_orchestrator import GraphOrchestrator
from agents.plan_graph import PlanGraph, PlanNode
from agents.registry import AgentRegistry
from core.types import Step


# ── 测试用假 worker / 假 LLM ────────────────────────────────────────────────

class _Worker:
    def __init__(self, name: str, *, result: str = "", fail: bool = False):
        self.name = name
        self.calls: list[str] = []
        self._result = result or f"[{name}] done"
        self._fail = fail

    async def run(self, task: str, **kwargs) -> str:
        self.calls.append(task)
        if self._fail:
            return "执行失败: mock"
        return self._result


def _registry(*workers: _Worker) -> AgentRegistry:
    reg = AgentRegistry()
    for w in workers:
        reg.register(w)
    return reg


class _PlannerLLM:
    def __init__(self, json_text: str):
        self._json = json_text

    async def next_step(self, messages, capabilities, emit_token=None):
        return Step(text=self._json)


class _FakeGraphDispatcher:
    def __init__(self, graph: PlanGraph):
        self.graph = graph
        self.calls = 0

    async def route(self, task, workers):
        self.calls += 1
        return self.graph


# ── L2: graph_dispatcher ─────────────────────────────────────────────────────

def test_parse_graph_basic():
    class W:
        def __init__(self, name):
            self.name = name

    text = """{
      "nodes": [
        {"id": "n1", "agent": "code_agent", "sub_task": "读 README", "depends_on": []},
        {"id": "n2", "agent": "unknown_x", "sub_task": "汇总", "depends_on": ["n1"]}
      ],
      "reason": "test"
    }"""
    g = _parse_graph(text, [W("code_agent")])
    assert g is not None
    assert len(g.nodes) == 2
    assert g.nodes[0].agent == "code_agent"
    assert g.nodes[1].agent == ""
    assert g.validate()[0]


def test_graph_dispatcher_llm_route():
    class W:
        def __init__(self, name):
            self.name = name

    async def _run():
        llm = _PlannerLLM(
            '{"nodes":[{"id":"n1","agent":"code_agent","sub_task":"分析","depends_on":[]}],"reason":"ok"}'
        )
        return await GraphDispatcher(llm).route("改代码", [W("code_agent")])

    g = asyncio.run(_run())
    assert not g.is_empty()
    assert g.validate()[0]
    assert g.nodes[0].agent == "code_agent"


def test_graph_dispatcher_invalid_json_fallback():
    class W:
        def __init__(self, name):
            self.name = name
            self.description = name

    async def _run():
        return await GraphDispatcher(_PlannerLLM("not json at all")).route(
            "改代码 写代码", [W("code_agent")])

    g = asyncio.run(_run())
    assert g.validate()[0]


# ── L3: graph_orchestrator ───────────────────────────────────────────────────

def test_orchestrator_parallel_layer():
    async def _run():
        w1 = _Worker("a", result="OUT-A")
        w2 = _Worker("b", result="OUT-B")
        g = PlanGraph(nodes=[
            PlanNode("n1", "a", "task a"),
            PlanNode("n2", "b", "task b"),
        ])
        events: list[dict] = []
        return await GraphOrchestrator(
            _registry(w1, w2),
            on_event=lambda p: events.append(p),
        ).run(g, "原始任务"), w1, w2, events

    result, w1, w2, events = asyncio.run(_run())
    bb = result["blackboard"]
    assert bb["n1"]["status"] == "done"
    assert bb["n2"]["status"] == "done"
    assert len(w1.calls) == 1 and len(w2.calls) == 1
    assert any(e.get("type") == "plan" for e in events)


def test_orchestrator_upstream_in_task():
    async def _run():
        w1 = _Worker("a", result="上游产出内容")
        w2 = _Worker("b")
        g = PlanGraph(nodes=[
            PlanNode("n1", "a", "第一步"),
            PlanNode("n2", "b", "第二步", depends_on=["n1"]),
        ])
        await GraphOrchestrator(_registry(w1, w2)).run(g, "原始任务")
        return w1, w2

    w1, w2 = asyncio.run(_run())
    assert len(w1.calls) == 1
    assert len(w2.calls) == 1
    assert "上游产出内容" in w2.calls[0]
    assert "【上游已完成的产出" in w2.calls[0]


def test_orchestrator_failure_blocks_downstream():
    async def _run():
        w1 = _Worker("a", fail=True)
        w2 = _Worker("b")
        g = PlanGraph(nodes=[
            PlanNode("n1", "a", "会失败"),
            PlanNode("n2", "b", "应被跳过", depends_on=["n1"]),
        ])
        return (await GraphOrchestrator(_registry(w1, w2)).run(g, "t"))["blackboard"], w2

    bb, w2 = asyncio.run(_run())
    assert bb["n1"]["status"] == "failed"
    assert bb["n2"]["status"] == "blocked"
    assert len(w2.calls) == 0


def test_orchestrator_verifier_revision():
    async def _run():
        w = _Worker("a", result="第一版")
        attempts = {"n1": 0}

        async def verifier(node, output):
            attempts[node.id] += 1
            return attempts[node.id] > 1, "请补充细节"

        g = PlanGraph(nodes=[PlanNode("n1", "a", "写报告", acceptance="必须含路径")])
        bb = (await GraphOrchestrator(
            _registry(w),
            verifier=verifier,
            max_revisions=1,
        ).run(g, "原始"))["blackboard"]
        return bb, w

    bb, w = asyncio.run(_run())
    assert bb["n1"]["status"] == "revised"
    assert bb["n1"]["revisions"] == 1
    assert len(w.calls) == 2
    assert "请补充细节" in w.calls[1]


# ── L4: coordinator DAG 升级路径 ───────────────────────────────────────────

def test_coordinator_dag_escalation():
    from agents.coordinator import Coordinator
    from agents.dispatcher import AutoDispatcher
    from agents.spec import AgentSpec
    from agents.worker import WorkerAgent
    from capabilities.base import CapabilityRegistry
    from capabilities.tools.fs import ReadFile
    from config import Config
    from core.bus import EventBus
    from core.context import Context
    from core.loop import Agent
    from core.types import CapabilityCall, EventType, Identity, Risk, Step
    from governance.budget import BudgetGovernor
    from governance.engine import DeclarativePolicy
    from llm.mock_llm import MockLLM

    class StuckCaptainLLM:
        name = "mock-stuck"

        async def next_step(self, messages, capabilities, emit_token=None):
            return Step(
                call=CapabilityCall(
                    name="fs.read",
                    args={"path": "README.md"},
                    intent="继续",
                    declared_risk=Risk.READ,
                ),
            )

    def _make_worker(name: str) -> WorkerAgent:
        spec = AgentSpec(name=name, role=name, description=name, auto_confirm=True)
        llm = MockLLM()
        reg = CapabilityRegistry([ReadFile()])
        agent_obj = Agent(
            llm=llm, registry=reg, policy=DeclarativePolicy(reg),
            bus=EventBus(), budget=BudgetGovernor(max_steps=5),
        )
        return WorkerAgent(spec=spec, agent=agent_obj)

    async def _run():
        bus = EventBus()
        seen: list = []
        bus.subscribe(lambda e: seen.append(e))

        workers = AgentRegistry()
        workers.register(_make_worker("code_agent"))

        main_agent = Agent(
            llm=StuckCaptainLLM(),
            registry=CapabilityRegistry([ReadFile()]),
            policy=DeclarativePolicy(CapabilityRegistry([ReadFile()])),
            bus=bus,
            budget=BudgetGovernor(max_steps=20),
        )

        fake_graph = PlanGraph(nodes=[
            PlanNode("n1", "code_agent", "分析代码结构"),
        ], reason="fake dag")

        coordinator = Coordinator(
            main_agent=main_agent,
            worker_registry=workers,
            dispatcher=AutoDispatcher(MockLLM()),
            graph_dispatcher=_FakeGraphDispatcher(fake_graph),
            bus=bus,
        )
        ctx = Context(identity=Identity())
        ctx.add_system("test")

        old_cap = Config.CAPTAIN_MAX_STEPS
        Config.CAPTAIN_MAX_STEPS = 2
        try:
            result = await coordinator.run("改代码 分析项目结构", ctx, lambda *a, **k: True)
        finally:
            Config.CAPTAIN_MAX_STEPS = old_cap
        return result, seen

    result, seen = asyncio.run(_run())
    plan_called = any(
        e.type == EventType.CAPABILITY_CALL
        and (e.payload or {}).get("name") == "coordinator.plan"
        for e in seen
    )
    plan_update = any(e.type == EventType.PLAN_UPDATE for e in seen)
    assert plan_called
    assert plan_update
    assert isinstance(result, str) and len(result) > 0
