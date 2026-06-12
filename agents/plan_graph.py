"""执行计划图(DAG)—— 编排的"乐谱"。

把"一个复杂任务"表示成一张有向无环图:每个节点是一个子任务,边是依赖。
相比扁平的 DispatchPlan(只有 全并行/全串行),DAG 能表达"C 依赖 A 和 B 的产出",
于是执行器可以:无依赖的并行跑、有依赖的等上游产出再跑。

设计原则:
- 只放"数据"和拓扑算法,不碰执行(执行在 graph_orchestrator)。
- 校验从严:重复 id、悬空依赖、成环都视为非法,fail-safe 退回更简单的计划。
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class PlanNode:
    id: str                                   # 节点唯一标识(如 "n1")
    agent: str                                # 执行者 worker 名;"" 表示交给 Captain 自己
    sub_task: str                             # 该节点要执行的具体任务
    depends_on: list[str] = field(default_factory=list)  # 上游节点 id(其产出会喂给本节点)
    acceptance: str = ""                      # 验收标准(Phase 2 verifier 据此判达标)


@dataclass
class PlanGraph:
    nodes: list[PlanNode] = field(default_factory=list)
    reason: str = ""

    def is_empty(self) -> bool:
        return not self.nodes

    def by_id(self) -> dict[str, PlanNode]:
        return {n.id: n for n in self.nodes}

    # ── 校验:非法图应被拒绝(调用方据此 fail-safe)──────────────────────────────
    def validate(self) -> tuple[bool, str]:
        ids = [n.id for n in self.nodes]
        if len(ids) != len(set(ids)):
            return False, "存在重复的节点 id"
        idset = set(ids)
        for n in self.nodes:
            for dep in n.depends_on:
                if dep not in idset:
                    return False, f"节点 {n.id} 依赖了不存在的 {dep}"
                if dep == n.id:
                    return False, f"节点 {n.id} 依赖了自己"
        if self._has_cycle():
            return False, "依赖图存在环"
        return True, ""

    def _has_cycle(self) -> bool:
        # 拓扑消解:能把所有节点排完即无环。
        return len(self._topo_order()) != len(self.nodes)

    def _topo_order(self) -> list[str]:
        deps = {n.id: set(n.depends_on) for n in self.nodes}
        done: list[str] = []
        done_set: set[str] = set()
        progress = True
        while progress and len(done) < len(self.nodes):
            progress = False
            for n in self.nodes:
                if n.id in done_set:
                    continue
                if deps[n.id] <= done_set:        # 所有依赖都已完成
                    done.append(n.id)
                    done_set.add(n.id)
                    progress = True
        return done

    # ── 拓扑分层:同层节点无相互依赖,可并行执行 ──────────────────────────────────
    def layers(self) -> list[list[PlanNode]]:
        by_id = self.by_id()
        remaining = set(by_id)
        done: set[str] = set()
        out: list[list[PlanNode]] = []
        while remaining:
            ready = [nid for nid in remaining
                     if set(by_id[nid].depends_on) <= done]
            if not ready:        # 有环或悬空依赖(validate 应已拦截);兜底防死循环
                break
            # 保持原始顺序稳定,便于可观测
            layer = [by_id[nid] for nid in self.nodes_order() if nid in ready]
            out.append(layer)
            for nid in ready:
                remaining.discard(nid)
                done.add(nid)
        return out

    def nodes_order(self) -> list[str]:
        return [n.id for n in self.nodes]


def from_dispatch_plan(plan) -> PlanGraph:
    """把旧的扁平 DispatchPlan 转成 PlanGraph(向后兼容)。

    parallel=True  → 各节点无依赖(一层并行)
    parallel=False → 串成一条链(n1→n2→…),后者依赖前者
    """
    nodes: list[PlanNode] = []
    prev_id: str | None = None
    for i, a in enumerate(getattr(plan, "assignments", []) or []):
        nid = f"n{i + 1}"
        deps = [] if getattr(plan, "parallel", False) else ([prev_id] if prev_id else [])
        nodes.append(PlanNode(id=nid, agent=a.agent_name, sub_task=a.sub_task, depends_on=deps))
        prev_id = nid
    return PlanGraph(nodes=nodes, reason=getattr(plan, "reason", ""))
