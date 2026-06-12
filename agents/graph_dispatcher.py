"""图规划器 —— 把任务规划成带依赖的子任务 DAG(PlanGraph)。

相比 dispatcher.py 的扁平方案,这里让 LLM 输出"谁依赖谁",从而支持:
  - 无依赖子任务并行
  - 有依赖子任务等上游产出再跑
  - 每个子任务带"验收标准"(供 Phase 2 的验证回路用)

两级:LLM 规划(JSON DAG)→ 失败/无 key 时退回关键词兜底(扁平、无依赖)。
解析出的图会做合法性校验,非法则 fail-safe 退回兜底,保证执行器拿到的永远是合法 DAG。
"""
from __future__ import annotations

import json
import re

from agents.plan_graph import PlanGraph, PlanNode
from agents.dispatcher import KeywordDispatcher
from agents.plan_graph import from_dispatch_plan


_PLANNER_PROMPT = """你是 Captain 的任务规划器。把用户任务分解成一张"子任务依赖图"。

可用执行专家(worker):
{roster}

规则:
- 能并行就并行(相互独立的子任务不要设依赖);有先后/数据依赖才用 depends_on。
- 每个子任务要可执行、可验收;acceptance 写清"怎样算做对了"(便于核验)。
- 纯聊天/简单问答/无需动手的,nodes 返回 [](交给 Captain 自己)。
- depends_on 里只能引用本图中已定义的其他节点 id。

用户任务:
{task}

严格只输出 JSON(不要其他内容):
{{
  "nodes": [
    {{"id": "n1", "agent": "worker名", "sub_task": "具体任务", "depends_on": [], "acceptance": "验收标准"}},
    {{"id": "n2", "agent": "worker名", "sub_task": "...", "depends_on": ["n1"], "acceptance": "..."}}
  ],
  "reason": "一句话说明分解思路"
}}"""


class GraphDispatcher:
    def __init__(self, llm) -> None:
        self._llm = llm
        self._kw = KeywordDispatcher()

    async def route(self, task: str, workers: list) -> PlanGraph:
        if not workers:
            return PlanGraph(reason="无可用 worker")
        graph = await self._llm_route(task, workers)
        if graph is not None and not graph.is_empty():
            ok, _ = graph.validate()
            if ok:
                return graph
        # 兜底:关键词扁平方案 → 转成无依赖 PlanGraph
        flat = self._kw.route(task, workers)
        return from_dispatch_plan(flat)

    async def _llm_route(self, task: str, workers: list) -> PlanGraph | None:
        from core.types import Message, Role
        roster = "\n".join(f"  - {w.name}: {getattr(w,'description','') or getattr(w,'role','')}"
                           for w in workers)
        prompt = _PLANNER_PROMPT.format(roster=roster, task=task)
        try:
            step = await self._llm.next_step([Message(role=Role.USER, content=prompt)], [])
        except Exception:
            return None
        return _parse_graph(step.text or "", workers)


def _parse_graph(text: str, workers: list) -> PlanGraph | None:
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        return None
    try:
        data = json.loads(m.group())
    except json.JSONDecodeError:
        return None
    worker_names = {w.name for w in workers}
    nodes: list[PlanNode] = []
    for i, item in enumerate(data.get("nodes", []) or []):
        if not isinstance(item, dict):
            continue
        nid = str(item.get("id") or f"n{i + 1}")
        agent = str(item.get("agent") or "")
        sub = str(item.get("sub_task") or "").strip()
        if not sub:
            continue
        if agent and agent not in worker_names:
            agent = ""   # 未知专家 → 交给 Captain 自己,不凭空造专家
        deps = [str(d) for d in (item.get("depends_on") or []) if d]
        nodes.append(PlanNode(id=nid, agent=agent, sub_task=sub,
                              depends_on=deps, acceptance=str(item.get("acceptance") or "")))
    if not nodes:
        return PlanGraph(nodes=[], reason=str(data.get("reason", "")))
    return PlanGraph(nodes=nodes, reason=str(data.get("reason", "")))
